import numpy as np

from models import ImputedSequenceMutations
from common import *

from sampler_collection import Sampler

class MutationOrderGibbsSampler(Sampler):
    def run(self, init_order, burn_in, num_samples):
        self.mutated_positions = self.obs_seq_mutation.mutation_pos_dict.keys()
        self.num_mutations = len(self.mutated_positions)

        assert(check_unordered_equal(init_order, self.mutated_positions))

        curr_order = init_order
        samples = []
        for i in range(burn_in + num_samples):
            curr_order = self._do_gibbs_sweep(curr_order)
            samples.append(curr_order)

        sampled_orders = samples[-num_samples:]
        return [ImputedSequenceMutations(self.obs_seq_mutation, order) for order in sampled_orders]

    def _do_gibbs_sweep(self, curr_order):
        """
        One gibbs sweep is a gibbs sampling step for all the positions
        """
        # sample full ordering from conditional prob for this position
        # TODO: make this go through a randomly ordered gibbs sampler
        for position in self.mutated_positions:
            pos_order_idx = curr_order.index(position)
            partial_order = curr_order[0:pos_order_idx] + curr_order[pos_order_idx + 1:]

            # the probabilities of each full ordering
            full_ordering_probs = []
            # the orderings under consideration
            # TODO: we can get rid of this variable and just recompute the order
            # It's here right now cause it makes life easy
            full_orderings = []

            # first consider the full ordering with position under consideration mutating last
            full_order_last = partial_order + [position]
            feat_vec_dicts = self.feature_generator.create_for_mutation_steps(
                ImputedSequenceMutations(
                    self.obs_seq_mutation,
                    full_order_last,
                )
            )
            multinomial_sequence = [
                self._get_multinomial_prob(feat_vec_dict_step, curr_mutate_pos)
                for curr_mutate_pos, feat_vec_dict_step in zip(full_order_last, feat_vec_dicts)
            ]
            full_orderings.append(full_order_last)
            full_ordering_probs.append(np.prod(multinomial_sequence))

            # iterate through the rest of the possible full mutation orders consistent with this partial order
            for i in reversed(range(self.num_mutations - 1)):
                possible_full_order = partial_order[:i] + [position] + partial_order[i:]
                feat_vec_dicts = self.feature_generator.create_for_mutation_steps(
                    ImputedSequenceMutations(
                        self.obs_seq_mutation,
                        possible_full_order
                    )
                )
                # calculate multinomial probs - only need to update 2 values (the one where this position mutates and
                # the position that mutates right after it), rest are the same
                multinomial_sequence[i] = self._get_multinomial_prob(feat_vec_dicts[i], possible_full_order[i])
                multinomial_sequence[i + 1] = self._get_multinomial_prob(feat_vec_dicts[i + 1], possible_full_order[i + 1])

                full_orderings.append(possible_full_order)
                # multiply the sequence of multinomials to get the probability of the full ordering
                # the product in {eq:full_ordering}
                full_ordering_probs.append(np.prod(multinomial_sequence))

            # now perform a draw from the multinomial distribution of full orderings
            # the multinomial folows the distribution in {eq:order_conditional_prob}
            sampled_order_idx = sample_multinomial(full_ordering_probs)
            # update the ordering
            curr_order = full_orderings[sampled_order_idx]
        return curr_order

    def _get_multinomial_prob(self, feat_vec_dict, numerator_pos):
        """
        a single term in {eq:full_ordering}
        """
        # guard against blowups when calculating exp - use a renormalization term
        theta_sums = [np.sum(self.theta[feat_vec]) for feat_vec in feat_vec_dict.values()]
        renorm_factor = np.max(theta_sums)

        numerator = np.exp(np.sum(self.theta[feat_vec_dict[numerator_pos]]) - renorm_factor)
        denominator = np.sum([np.exp(t - renorm_factor) for t in theta_sums])
        return numerator / denominator