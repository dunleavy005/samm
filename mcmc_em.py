import time
import numpy as np

from models import *
from common import *
from feature_generator import SubmotifFeatureGenerator
# from mutation_order_sampler import MutationOrderSampler
from mutation_order_gibbs import MutationOrderGibbsSampler
from survival_problem import SurvivalProblem
from sampler_collection import SamplerCollection

class MCMC_EM:
    def __init__(self, observed_data, feat_generator, sampler_cls, base_num_e_samples=10, burn_in=10, num_threads=1):
        self.observed_data = observed_data
        self.feat_generator = feat_generator
        self.base_num_e_samples = base_num_e_samples
        self.burn_in = burn_in
        self.sampler_cls = sampler_cls
        self.num_threads = num_threads

    # TODO: find a reasonable choice for upper_stop
    def run(self, max_iters=10, verbose=False, upper_stop=1.):
        # initialize theta vector
        theta = np.random.randn(self.feat_generator.feature_vec_len)
        # stores the initialization for the gibbs samplers for the next iteration's e-step
        init_orders = [obs_seq.mutation_pos_dict.keys() for obs_seq in self.observed_data]
        upper_bound_is_large = True
        run = 0
        # TODO: use a separate burn-in value for computing ESS?
        while upper_bound_is_large and run < max_iters:
            prev_samples = []
            lower_bound_is_negative = True
            num_e_samples = self.base_num_e_samples
            # do E-step
            sampler_collection = SamplerCollection(
                self.observed_data,
                theta,
                self.sampler_cls,
                self.feat_generator,
                self.num_threads,
            )

            e_step_samples = []
            while lower_bound_is_negative:
                sampled_orders_list = sampler_collection.get_samples(
                    init_orders,
                    num_e_samples,
                    self.burn_in,
                )
                # the last sampled mutation order from each list
                # use this iteration's sampled mutation orders as initialization for the gibbs samplers next cycle
                init_orders = [sampled_orders[-1].mutation_order for sampled_orders in sampled_orders_list]
                # flatten the list of samples to get all the samples
                e_step_samples += [o for orders in sampled_orders_list for o in orders]

                prev_theta = theta

                # Do M-step
                problem = SurvivalProblem(e_step_samples)
                theta, exp_log_lik = problem.solve(self.feat_generator, verbose=verbose)

                # Get statistics
                log_lik_vec = problem.calculate_log_lik_vec(self.feat_generator, theta, prev_theta, e_step_samples)
                log_lik_ratio_mean = np.mean(log_lik_vec)

                # Calculate lower bound to determine if we need to rerun
                autocorr = self.calculate_autocorr(log_lik_vec)
                neff = len(e_step_samples) / autocorr
                ase = np.sqrt(np.var(log_lik_vec) / neff)

                # TODO: should we just have a table of z scores?
                lower_bound = log_lik_ratio_mean - ZSCORE * ase
                upper_bound = log_lik_ratio_mean + ZSCORE * ase
                lower_bound_is_negative = (lower_bound < 0)
                upper_bound_is_large = (upper_bound > upper_stop)

                # Take enough samples next time to get large enough neff
                assert(autocorr > 1)
                num_e_samples = int(np.ceil((autocorr - 1) * num_e_samples))

            run += 1
        return theta

    def get_e_samples(self, obs_seq, theta, init_order, num_samples):
        mut_order_sampler = MutationOrderGibbsSampler(
            theta,
            self.feat_generator,
            obs_seq
        )
        # TODO: we can also try different amount of burn in for each EM iteration in the future
        mut_order_sampler.sample_burn_in(init_order, self.burn_in)
        # TODO: we definitely want different number of samples at each E-step in the future
        sampled_orders = mut_order_sampler.sample_orders(num_samples)
        return [ImputedSequenceMutations(obs_seq, order) for order in sampled_orders]

    def calculate_autocorr(self, log_lik_ratios):
        # Definition from p. 151 of Carlin/Louis:
        # \kappa = 1 + 2\sum_{k=1}^\infty \rho_k
        # So we don't take the self-correlation
        # TODO: do we worry about cutting off small values?
        # Glynn/Whitt say we could use batch estimation with batch sizes going to
        # infinity. Is this a viable option?
        result = np.correlate(log_lik_ratios, log_lik_ratios, mode='full')
        return 1 + 2*np.sum(result[1+result.size/2:])

