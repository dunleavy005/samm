import time
import numpy as np
import logging as log

from models import *
from common import *
from feature_generator import SubmotifFeatureGenerator
from mutation_order_gibbs import MutationOrderGibbsSampler
from survival_problem import SurvivalProblem
from sampler_collection import SamplerCollection
from survival_problem_grad_descent import SurvivalProblemGradientDescent

class MCMC_EM:
    def __init__(self, observed_data, feat_generator, sampler_cls, base_num_e_samples=10, burn_in=10, max_m_iters=500, num_threads=1):
        self.observed_data = observed_data
        self.feat_generator = feat_generator
        self.base_num_e_samples = base_num_e_samples
        self.max_m_iters = max_m_iters
        self.burn_in = burn_in
        self.sampler_cls = sampler_cls
        self.num_threads = num_threads

    def run(self, theta=None, lasso_param=1, max_em_iters=10, diff_thres=1e-6):
        # initialize theta vector
        if theta is None:
            theta = np.random.randn(self.feat_generator.feature_vec_len)
        # stores the initialization for the gibbs samplers for the next iteration's e-step
        init_orders = [obs_seq.mutation_pos_dict.keys() for obs_seq in self.observed_data]
        prev_exp_log_lik = None
        for run in range(max_em_iters):
            lower_bound_is_negative = True
            prev_theta = theta
            num_e_samples = self.base_num_e_samples
            burn_in = self.burn_in

            sampler_collection = SamplerCollection(
                self.observed_data,
                prev_theta,
                self.sampler_cls,
                self.feat_generator,
                self.num_threads,
            )

            e_step_samples = []
            while lower_bound_is_negative:
                # do E-step
                log.info("E STEP, iter %d, num samples %d" % (run, len(e_step_samples) + num_e_samples))
                sampled_orders_list = sampler_collection.get_samples(
                    init_orders,
                    num_e_samples,
                    burn_in,
                )
                burn_in = 0

                # the last sampled mutation order from each list
                # use this iteration's sampled mutation orders as initialization for the gibbs samplers next cycle
                init_orders = [sampled_orders[-1].mutation_order for sampled_orders in sampled_orders_list]
                # flatten the list of samples to get all the samples
                e_step_samples += [o for orders in sampled_orders_list for o in orders]

                # Do M-step
                log.info("M STEP, iter %d" % run)

                problem = SurvivalProblemGradientDescent(self.feat_generator, e_step_samples, lasso_param)
                theta, exp_log_lik = problem.solve(
                    init_theta=prev_theta,
                    max_iters=self.max_m_iters,
                )
                log.info("Current Theta")
                log.info("\n".join(["%d: %.2g" % (i, theta[i]) for i in range(theta.size) if np.abs(theta[i]) > 1e-5]))
                log.info("penalized negative log likelihood %f" % exp_log_lik)

                # Get statistics
                log_lik_vec = problem.calculate_log_lik_ratio_vec(theta, prev_theta)

                # Calculate lower bound to determine if we need to rerun
                ase, lower_bound, _ = get_standard_error_ci_corrected(log_lik_vec, ZSCORE)

                lower_bound_is_negative = (lower_bound < 0)
                log.info("lower_bound_is_negative %d" % lower_bound_is_negative)
            if prev_exp_log_lik is not None and exp_log_lik - prev_exp_log_lik < diff_thres:
                break
            prev_exp_log_lik = exp_log_lik

        return theta
