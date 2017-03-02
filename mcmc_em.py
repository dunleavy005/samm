import time
import numpy as np
import logging as log

from models import *
from common import *
from sampler_collection import SamplerCollection
from profile_support import profile

class MCMC_EM:
    def __init__(self, observed_data, feat_generator, sampler_cls, problem_solver_cls, theta_mask, base_num_e_samples=10, burn_in=10, max_m_iters=500, num_jobs=1, num_threads=1, approx='none'):
        """
        @param observed_data: list of ObservedSequenceMutationsFeatures (start and end sequences, plus base feature info)
        @param feat_generator: an instance of a FeatureGenerator
        @param sampler_cls: a Sampler class
        @param problem_solver_cls: SurvivalProblem class
        @param base_num_e_samples: number of E-step samples to draw initially
        @param burn_in: number of gibbs sweeps to do for burn in
        @param max_m_iters: maximum number of iterations for the M-step
        @param num_jobs: number of jobs to submit for E-step
        @param num_threads: number of threads to use for M-step
        """
        self.observed_data = observed_data
        self.num_data = len(observed_data)
        self.feat_generator = feat_generator
        self.motif_list = self.feat_generator.get_motif_list()
        self.base_num_e_samples = base_num_e_samples
        self.max_m_iters = max_m_iters
        self.burn_in = burn_in
        self.sampler_cls = sampler_cls
        self.problem_solver_cls = problem_solver_cls
        self.num_jobs = num_jobs
        self.num_threads = num_threads
        self.theta_mask = theta_mask
        self.approx = approx

    def run(self, theta, penalty_param=1, max_em_iters=10, diff_thres=1e-6, max_e_samples=20):
        """
        @param theta: initial value for theta in MCMC-EM
        @param penalty_param: the coefficient for the penalty function
        @param max_em_iters: the maximum number of iterations of MCMC-EM
        @param diff_thres: if the change in the objective function changes no more than `diff_thres`, stop MCMC-EM
        @param max_e_samples: maximum number of e-samples to grab per observed sequence
        """
        st = time.time()
        # stores the initialization for the gibbs samplers for the next iteration's e-step
        init_orders = [obs_seq.mutation_pos_dict.keys() for obs_seq in self.observed_data]
        all_traces = []
        # burn in only at the very beginning
        burn_in = self.burn_in
        for run in range(max_em_iters):
            prev_theta = theta
            num_e_samples = self.base_num_e_samples

            sampler_collection = SamplerCollection(
                self.observed_data,
                prev_theta,
                self.sampler_cls,
                self.feat_generator,
                self.num_jobs,
                self.approx,
            )

            e_step_samples = []
            lower_bound_is_negative = True
            while len(e_step_samples)/self.num_data < max_e_samples and lower_bound_is_negative:
                ## Keep grabbing samples until it is highly likely we have increased the penalized log likelihood

                # do E-step
                log.info("E STEP, iter %d, num samples %d, time %f" % (run, len(e_step_samples) + num_e_samples, time.time() - st))
                sampler_results = sampler_collection.get_samples(
                    init_orders,
                    num_e_samples,
                    burn_in,
                )
                # Don't use burn-in from now on
                burn_in = 0
                all_traces.append([res.trace for res in sampler_results])
                sampled_orders_list = [res.samples for res in sampler_results]

                # the last sampled mutation order from each list
                # use this iteration's sampled mutation orders as initialization for the gibbs samplers next cycle
                init_orders = [sampled_orders[-1].mutation_order for sampled_orders in sampled_orders_list]
                # flatten the list of samples to get all the samples
                e_step_samples += [o for orders in sampled_orders_list for o in orders]

                # Do M-step
                log.info("M STEP, iter %d, time %f" % (run, time.time() - st))

                problem = self.problem_solver_cls(self.feat_generator, e_step_samples, penalty_param, self.theta_mask, self.num_threads)

                theta, pen_exp_log_lik, log_lik_diff, lower_bound = problem.solve(
                    init_theta=prev_theta,
                    max_iters=self.max_m_iters,
                )
                log.info("Current Theta")
                log.info(
                    get_nonzero_theta_print_lines(theta, self.motif_list)
                )
                log.info("penalized log likelihood %f" % pen_exp_log_lik)
                lower_bound_is_negative = (lower_bound < 0)
                log.info("lower_bound_is_negative %d" % lower_bound_is_negative)

                num_nonzero = np.count_nonzero(theta)
                if num_nonzero > theta.size/2 or num_nonzero < 4:
                    # Too many nonzeros or too many zeros - just stop and consider a different penalty parameter
                    break

            if lower_bound_is_negative:
                # if penalized log likelihood is decreasing
                break
            elif log_lik_diff < diff_thres:
                # if penalized log likelihood is increasing but not by very much
                break

            log.info("official pen_exp_log_lik %f" % pen_exp_log_lik)

        return theta, all_traces
