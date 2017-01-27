#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fit a context-sensitive motif model via MCMC-EM
"""

import sys
import argparse
import os
import os.path
import csv
import pickle
import logging as log

import numpy as np
import scipy.stats

from models import ObservedSequenceMutations
from mcmc_em import MCMC_EM
from feature_generator import SubmotifFeatureGenerator
from mutation_order_gibbs import MutationOrderGibbsSampler
from survival_problem_cvxpy import SurvivalProblemLassoCVXPY
from survival_problem_cvxpy import SurvivalProblemFusedLassoCVXPY
from survival_problem_grad_descent import SurvivalProblemGradientDescent
from common import *

def parse_args():
    ''' parse command line arguments '''

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--seed',
        type=int,
        help='rng seed for replicability',
        default=1533)
    parser.add_argument('--input-file',
        type=str,
        help='sequence data in csv',
        default='_output/seqs.csv')
    parser.add_argument('--input-genes',
        type=str,
        help='genes data in csv',
        default='_output/genes.csv')
    parser.add_argument('--num-threads',
        type=int,
        help='number of threads to use during E-step',
        default=4)
    parser.add_argument('--solver',
        type=str,
        help='CL = cvxpy lasso, CFL = cvxpy fused lasso, L = gradient descent lasso',
        choices=["CL", "CFL", "L"],
        default="L")
    parser.add_argument('--motif-len',
        type=int,
        help='length of motif (must be odd)',
        default=5)
    parser.add_argument('--em-max-iters',
        type=int,
        help='number of EM iterations',
        default=20)
    parser.add_argument('--log-file',
        type=str,
        help='log file',
        default='_output/context_log.txt')
    parser.add_argument('--out-file',
        type=str,
        help='file with pickled context model',
        default='_output/context_model.pkl')
    parser.add_argument("--penalty-params",
        type=str,
        help="penalty parameters, comma separated",
        default="0.1")
    parser.add_argument('--theta-file',
        type=str,
        help='file with pickled true context model',
        default='_output/true_theta.pkl')

    args = parser.parse_args()

    args.problem_solver_cls = SurvivalProblemGradientDescent
    if args.solver == "CL":
        args.problem_solver_cls = SurvivalProblemLassoCVXPY
    elif args.solver == "CFL":
        args.problem_solver_cls = SurvivalProblemFusedLassoCVXPY

    assert(args.motif_len % 2 == 1 and args.motif_len > 1)

    return args

def main(args=sys.argv[1:]):
    args = parse_args()
    log.basicConfig(format="%(message)s", filename=args.log_file, level=log.DEBUG)
    np.random.seed(args.seed)
    feat_generator = SubmotifFeatureGenerator(submotif_len=args.motif_len)

    # Load true theta for comparison
    true_theta = pickle.load(open(args.theta_file, 'rb'))

    log.info("Reading data")
    gene_dict, obs_data = read_gene_seq_csv_data(args.input_genes, args.input_file)
    log.info("Number of sequences %d" % len(obs_data))
    log.info("Settings %s" % args)

    log.info("Running EM")

    em_algo = MCMC_EM(
        obs_data,
        feat_generator,
        MutationOrderGibbsSampler,
        args.problem_solver_cls,
        num_threads=args.num_threads,
    )

    motif_list = feat_generator.get_motif_list()

    # Run EM on the lasso parameters from largest to smallest
    penalty_params = [float(l) for l in args.penalty_params.split(",")]
    results_list = []
    theta = None
    for penalty_param in sorted(penalty_params, reverse=True):
        log.info("Penalty parameter %f" % penalty_param)
        theta = em_algo.run(theta=theta, penalty_param=penalty_param, max_em_iters=args.em_max_iters)
        results_list.append((penalty_param, theta))

        log.info("==== FINAL theta, penalty param %f ====" % penalty_param)
        for i in range(theta.size):
            if np.abs(theta[i]) > ZERO_THRES:
                if i == theta.size - 1:
                    log.info("%d: %f (EDGES)" % (i, theta[i]))
                else:
                    log.info("%d: %f (%s)" % (i, theta[i], motif_list[i]))

        log.info(scipy.stats.spearmanr(theta, true_theta))
        log.info(scipy.stats.kendalltau(theta, true_theta))
        log.info("Pearson cor=%f, p=%f" % scipy.stats.pearsonr(theta, true_theta))
        log.info("L2 error %f" % np.linalg.norm(theta - true_theta))

        with open(args.out_file, "w") as f:
            pickle.dump(results_list, f)

if __name__ == "__main__":
    main(sys.argv[1:])
