class ObservedSequenceMutations:
    def __init__(self, start_seq, end_seq, motif_len=1):
        """
        @param start_seq: start sequence
        @param end_seq: ending sequence with mutations
        @param motif_len: needed to determine flanking ends/mutations to trim sequence

        This class goes through half the sequence forward and finds the position where
        there are motif_len/2 conserved nucleotides, and does the same in reverse.

        Additionally, since we aren't generating features for any of the flanking nucleotides,
        it keeps an extra property self.flanks while saying that the start and end sequence
        are their corresponding subsequences after removing the flanks. This minimizes a lot
        of code rewriting and off-by-one errors with a minor increase in keeping around a little
        extra data.

        self.mutation_pos_dict is a dictionary with key as position and value as target nucleotide
        """

        assert(len(start_seq) == len(end_seq))

        start_idx = 0
        end_idx = len(start_seq)
        flank_len = motif_len/2

        # Go through half the sequence forward to find beginning conserved nucleotides
        for flank_start_idx in range(len(start_seq)/2):
            if start_seq[flank_start_idx] != end_seq[flank_start_idx]:
                start_idx = flank_start_idx + 1
            elif start_idx == flank_start_idx:
                break

        # Go through remaining half the sequence backward to find ending conserved nucleotides
        for flank_end_idx in reversed(range(len(start_seq)/2, len(start_seq))):
            if start_seq[flank_end_idx] != end_seq[flank_end_idx]:
                end_idx = flank_end_idx
            elif end_idx - flank_len == flank_end_idx:
                break

        self.left_flank = start_seq[start_idx:start_idx + flank_len]
        self.right_flank = start_seq[end_idx - flank_len:end_idx]

        start_seq = start_seq[start_idx + flank_len:end_idx - flank_len]
        end_seq = end_seq[start_idx + flank_len:end_idx - flank_len]

        self.mutation_pos_dict = dict()
        for i in range(len(start_seq)):
            if start_seq[i] != end_seq[i]:
                self.mutation_pos_dict[i] = end_seq[i]

        self.num_mutations = len(self.mutation_pos_dict.keys())
        self.start_seq = start_seq
        self.end_seq = end_seq
        self.seq_len = len(self.start_seq)
        assert(self.seq_len > 0)

    def __str__(self):
        return "Seq %s, Mutations %s" % (
            self.start_seq,
            self.mutation_pos_dict,
        )

class ImputedSequenceMutations:
    def __init__(self, obs_seq_mutation, mutation_order):
        """
        @param obs_seq_mutation: any object that needs to get augmented by a mutation order
                                (e.g. ObservedSequenceMutations or ObservedSequenceMutationsFeatures)
        @param mutation_order: a list of the positions in the order they mutated
        """
        self.obs_seq_mutation = obs_seq_mutation
        self.mutation_order = mutation_order

    def __str__(self):
        return "Seq %s, Mutation Order %s" % (
            self.obs_seq_mutation.start_seq,
            self.mutation_order,
        )

class FullSequenceMutations:
    def __init__(self, obs_seq_mutation, mutations):
        """
        @param obs_seq_mutation: ObservedSequenceMutations
        @param mutations: an ordered list of MutationPosTime
        """
        self.obs_seq_mutation = obs_seq_mutation
        self.mutations = mutations

    def get_mutation_order(self):
        return [m.pos for m in self.mutations]

    def __str__(self):
        return "%s => %s" % (
            self.obs_seq_mutation.start_seq,
            self.obs_seq_mutation.end_seq
        )

class MutationEvent:
    """
    Stores information on what happened during a mutation event
    """
    def __init__(self, time, pos, target_nucleotide):
        self.time = time
        self.pos = pos
        self.target_nucleotide = target_nucleotide

    def __str__(self):
        return "%d=%s (%.2g)" % (self.pos, self.target_nucleotide, self.time)
