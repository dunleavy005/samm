import scipy.sparse

from feature_generator import FeatureGenerator, MultiFeatureMutationStep

class GenericFeatureGenerator(FeatureGenerator):
    """
    Subclass this to have various types of feature vector generators.
    We assume all feature vectors are composed of ones and zeros.
    Each feature vector will be a dictionary keyed on some property of the sequence being the
    corresponding index in the list of properties.
    We call these "sparse feature vectors".
    """

    def get_base_features(self, obs_seq_mutation, feature_vec_len):
        """
        Create the feature matrices and feature vector dictionary
        before any mutations have occurred

        @return ObservedSequenceMutations augmented with a feature matrix and dictionary
        """
        indices = []
        start_idx = 0
        indptr = [start_idx]
        num_entries = 0

        for pos in range(obs_seq_mutation.seq_len):
            feat_idx = self._get_mutating_pos_feat_idx(pos, obs_seq_mutation.start_seq_with_flanks)
            if feat_idx:
                start_idx += len(feat_idx)
                indices += feat_idx
            indptr.append(start_idx)

        data = [True] * start_idx
        feat_matrix = scipy.sparse.csr_matrix(
            (data, indices, indptr),
            shape=(obs_seq_mutation.seq_len, feature_vec_len),
            dtype=bool,
        )
        return feat_matrix

    def create_for_mutation_steps(self, seq_mut_order):
        """
        Calculate the feature values for the mutation steps
        Only returns the deltas at each mutation step

        @param seq_mut_order: ImputedSequenceMutations

        @return list of FeatureMutationStep (correponding to after first mutation to before last mutation)
        """
        feat_mutation_steps = []

        old_mutation_pos = None
        intermediate_seq = seq_mut_order.obs_seq_mutation.start_seq_with_flanks

        feat_dict_prev = dict()
        already_mutated_pos = set()
        for mutation_step, mutation_pos in enumerate(seq_mut_order.mutation_order):
            feat_dict_curr, feat_dict_future = self.update_mutation_step(
                mutation_step,
                mutation_pos,
                old_mutation_pos,
                seq_mut_order,
                intermediate_seq,
                already_mutated_pos,
            )
            mutating_pos_feat_idx = self._get_mutating_pos_feat_idx(mutation_pos, intermediate_seq)
            feat_mutation_steps.append(MultiFeatureMutationStep(
                mutating_pos_feat_idx,
                [mutation_pos],
                neighbors_feat_old=feat_dict_prev,
                neighbors_feat_new=feat_dict_curr,
            ))

            # Apply mutation
            intermediate_seq = self._get_mutated_seq(
                intermediate_seq,
                mutation_pos,
                seq_mut_order.obs_seq_mutation.end_seq,
            )
            already_mutated_pos.add(mutation_pos)
            feat_dict_prev = feat_dict_future
            old_mutation_pos = mutation_pos

        if len(feat_mutation_steps) != seq_mut_order.obs_seq_mutation.num_mutations:
            raise AssertionError("%d vs %d" % (len(feat_mutation_steps), seq_mut_order.obs_seq_mutation.num_mutations))
        return feat_mutation_steps

    def create_remaining_mutation_steps(
        self,
        seq_mut_order,
        update_step_start,
    ):
        """
        Calculate the feature values for the mutation steps starting the the `update_step_start`-th step
        Only returns the deltas at each mutation step

        @param seq_mut_order: ImputedSequenceMutations
        @param update_step_start: which mutation step to start calculating features for

        @return list of FeatureMutationStep (correponding to after `update_step_start`-th mutation
                    to before last mutation)
        """
        feat_mutation_steps = []

        old_mutation_pos = None
        feat_dict_prev = dict()
        flanked_seq = seq_mut_order.get_seq_at_step(update_step_start, flanked=True)

        already_mutated_pos = set(seq_mut_order.mutation_order[:update_step_start])
        for mutation_step in range(update_step_start, seq_mut_order.obs_seq_mutation.num_mutations):
            mutation_pos = seq_mut_order.mutation_order[mutation_step]
            feat_dict_curr, feat_dict_future = self.update_mutation_step(
                mutation_step,
                mutation_pos,
                old_mutation_pos,
                seq_mut_order,
                flanked_seq,
                already_mutated_pos,
            )
            mutating_pos_feat_idx = self._get_mutating_pos_feat_idx(mutation_pos, flanked_seq)
            feat_mutation_steps.append(MultiFeatureMutationStep(
                mutating_pos_feat_idx,
                [mutation_pos],
                neighbors_feat_old=feat_dict_prev,
                neighbors_feat_new=feat_dict_curr,
            ))

            # Apply mutation
            flanked_seq = self._get_mutated_seq(
                flanked_seq,
                mutation_pos,
                seq_mut_order.obs_seq_mutation.end_seq,
            )
            already_mutated_pos.add(mutation_pos)
            feat_dict_prev = feat_dict_future
            old_mutation_pos = mutation_pos
        return feat_mutation_steps

    def get_shuffled_mutation_steps_delta(
        self,
        seq_mut_order,
        update_step,
        flanked_seq,
        already_mutated_pos,
    ):
        """
        @param seq_mut_order: a list of the positions in the mutation order
        @param update_step: the index of the mutation step being shuffled with the (`update_step` + 1)-th step
        @param flanked_seq: must be a FLANKED sequence
        @param already_mutated_pos: set of positions that already mutated - dont calculate feature vals for these

        @return a tuple with the feature at this mutation step and the feature mutation step of the next mutation step
        """
        feat_mutation_steps = []
        first_mutation_pos = seq_mut_order.mutation_order[update_step]
        second_mutation_pos = seq_mut_order.mutation_order[update_step + 1]

        _, feat_dict_future = self.update_mutation_step(
            update_step,
            first_mutation_pos,
            None,
            seq_mut_order,
            flanked_seq,
            already_mutated_pos,
        )

        # Apply mutation
        flanked_seq = self._get_mutated_seq(
            flanked_seq,
            first_mutation_pos,
            seq_mut_order.obs_seq_mutation.end_seq,
        )

        feat_dict_curr, _ = self.update_mutation_step(
            update_step + 1,
            second_mutation_pos,
            first_mutation_pos,
            seq_mut_order,
            flanked_seq,
            already_mutated_pos,
            calc_future_dict=False,
        )

        first_mut_pos_feat_idx = self._get_mutating_pos_feat_idx(first_mutation_pos, flanked_seq)
        second_mut_pos_feat_idx = self._get_mutating_pos_feat_idx(second_mutation_pos, flanked_seq)
        return first_mut_pos_feat_idx, MultiFeatureMutationStep(
            second_mut_pos_feat_idx,
            [second_mutation_pos],
            neighbors_feat_old=feat_dict_future,
            neighbors_feat_new=feat_dict_curr,
        )

    def update_mutation_step(
            self,
            mutation_step,
            mutation_pos,
            old_mutation_pos,
            seq_mut_order,
            intermediate_seq,
            already_mutated_pos,
            calc_future_dict=True,
        ):
        """
        Does the heavy lifting for calculating feature vectors at a given mutation step
        @param mutation_step: mutation step index
        @param mutation_pos: the position that is mutating
        @param old_mutation_pos: the position that mutated previously - None if this is first mutation
        @param seq_mut_order: ImputedSequenceMutations
        @param intermediate_seq: nucleotide sequence INCLUDING flanks - before the mutation step occurs

        @return tuple with
            1. the feature index of the position that mutated
            2. a dict with the positions next to the previous mutation and their feature index
            3. a dict with the positions next to the current mutation and their feature index
        """
        feat_dict_curr = dict()
        feat_dict_future = dict()
        # Calculate features for positions in the risk group at the time of this mutation step
        # Only requires updating feature values that were close to the previous mutation
        # Get the feature vectors for the positions that might be affected by the previous mutation
        if old_mutation_pos is not None:
            feat_dict_curr = self._get_feature_dict_for_region(
                old_mutation_pos,
                intermediate_seq,
                seq_mut_order.obs_seq_mutation.seq_len,
                already_mutated_pos,
            )

        # Calculate the features in these special positions for updating the next mutation step's risk group
        # Get the feature vectors for the positions that will be affected by current mutation
        if calc_future_dict:
            feat_dict_future = self._get_feature_dict_for_region(
                mutation_pos,
                intermediate_seq,
                seq_mut_order.obs_seq_mutation.seq_len,
                already_mutated_pos,
            )
        return feat_dict_curr, feat_dict_future

    # feature generator--specific functions

    def _get_feature_dict_for_region(
        self,
        position,
        intermediate_seq,
        seq_len,
        already_mutated_pos,
    ):
        """
        @param position: the position around which to calculate the feature indices for
        @param intermediate_seq: the nucleotide sequence
        @param seq_len: the length of this sequence
        @param already_mutated_pos: which positions already mutated - dont calculate features for these positions

        @return a dict with the positions next to the given position and their feature index
        """
        raise NotImplementedError()

    def _get_mutating_pos_feat_idx(self, pos, seq_with_flanks):
        """
        """
        raise NotImplementedError()

    def _get_mutated_seq(self, intermediate_seq, mutation_pos, end_seq):
        """
        """
        raise NotImplementedError()
