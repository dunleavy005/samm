import pickle
import sys
import argparse
import numpy as np
import os
import os.path
import csv
import re

from survival_model_simulator import SurvivalModelSimulatorSingleColumn
from survival_model_simulator import SurvivalModelSimulatorMultiColumn
from submotif_feature_generator import SubmotifFeatureGenerator
from common import *
from read_data import GERMLINE_PARAM_FILE

def parse_args():
    ''' parse command line arguments '''

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--seed',
        type=int,
        help='rng seed for replicability',
        default=1533)
    parser.add_argument('--random-gene-len',
        type=int,
        help='Create random germline genes of this length. If zero, load true germline genes',
        default=24)
    parser.add_argument('--mutability',
        type=str,
        default='gctree/S5F/Mutability.csv',
        help='path to mutability model file')
    parser.add_argument('--substitution',
        type=str,
        default='gctree/S5F/Substitution.csv',
        help='path to substitution model file')
    parser.add_argument('--germline-path',
        type=str,
        help='germline file path',
        default=GERMLINE_PARAM_FILE)
    parser.add_argument('--output-true-theta',
        type=str,
        help='true theta pickle file',
        default='_output/true_theta.pkl')
    parser.add_argument('--output-file',
        type=str,
        help='simulated data destination file',
        default='_output/seqs.csv')
    parser.add_argument('--output-genes',
        type=str,
        help='germline genes used in csv file',
        default='_output/genes.csv')
    parser.add_argument('--lambda0',
        type=float,
        help='base hazard rate in cox proportional hazards model for a single motif (summing over targets)',
        default=0.1)
    parser.add_argument('--n-taxa',
        type=int,
        help='number of taxa to simulate',
        default=2)
    parser.add_argument('--n-germlines',
        type=int,
        help='number of germline genes to sample from (max 350)',
        default=2)
    parser.add_argument('--motif-len',
        type=int,
        help='length of motif (must be odd)',
        default=5)
    parser.add_argument('--min-censor-time',
        type=float,
        help='Minimum censoring time',
        default=1)
    parser.add_argument('--sparsity-ratio',
        type=float,
        help='Proportion of motifs to set to zero',
        default=0.5)
    parser.add_argument('--guarantee-motifs-showup',
        action="store_true",
        help='Make sure the nonzero motifs show up in the germline')
    parser.add_argument('--per-target-model',
        action="store_true",
        help='Allow different hazard rates for different target nucleotides')
    parser.add_argument('--with-replacement',
        action="store_true",
        help='Allow same position to mutate multiple times')

    parser.set_defaults(guarantee_motifs_showup=False, per_target_model=False, with_replacement=False)
    args = parser.parse_args()
    # Only even random gene lengths allowed
    assert(args.random_gene_len % 2 == 0)
    # Only odd motif lengths allowed
    assert(args.motif_len % 2 == 1)

    if args.per_target_model:
        args.lambda0 /= 3

    return args

def _read_mutability_probability_params(motif_list, args):
    """
    Read S5F parameters
    """
    theta_dict = {}
    with open(args.mutability, "rb") as mutability_f:
        mut_reader = csv.reader(mutability_f, delimiter=" ")
        mut_reader.next()
        for row in mut_reader:
            motif = row[0].lower()
            motif_hazard = np.log(float(row[1]))
            theta_dict[motif] = motif_hazard

    theta = np.array([theta_dict[m] for m in motif_list])

    substitution_dict = {}
    with open(args.substitution, "rb") as substitution_f:
        substitution_reader = csv.reader(substitution_f, delimiter=" ")
        substitution_reader.next()
        for row in substitution_reader:
            motif = row[0].lower()
            substitution_dict[motif] = [float(row[i]) for i in range(1, 5)]
    probability_matrix = np.array([substitution_dict[m] for m in motif_list])

    if args.per_target_model:
        # Create the S5F target matrix and use this as our true theta
        theta = np.diag(np.exp(theta)) * np.matrix(probability_matrix)
        nonzero_mask = np.where(theta != 0)
        zero_mask = np.where(theta == 0)
        theta[nonzero_mask] = np.log(theta[nonzero_mask])
        theta[zero_mask] = -np.inf
        theta = np.array(theta)
        probability_matrix = None
    num_cols = NUM_NUCLEOTIDES if args.per_target_model else 1
    return theta.reshape((len(motif_list), num_cols)), probability_matrix

def _generate_true_parameters(motif_list, args):
    """
    Read mutability and substitution parameters from S5F
    Make a sparse version if sparsity_ratio > 0
    """
    true_theta, probability_matrix = _read_mutability_probability_params(motif_list, args)
    nonzero_motifs = motif_list
    if args.sparsity_ratio > 0:
        # Let's zero out some motifs now
        num_zero_motifs = int(args.sparsity_ratio * len(motif_list))
        zero_motif_idxs = np.random.choice(len(motif_list), size=num_zero_motifs, replace=False)
        zero_motifs = set()
        for idx in zero_motif_idxs:
            zero_motifs.add(motif_list[idx])
            true_theta[idx,] = 0
            center_nucleotide_idx = NUCLEOTIDE_DICT[motif_list[idx][args.motif_len/2]]
            if args.per_target_model:
                true_theta[idx, center_nucleotide_idx] = -np.inf
            else:
                probability_matrix[idx, :] = 1./3
                probability_matrix[idx, center_nucleotide_idx] = 0
        nonzero_motifs = list(set(motif_list) - zero_motifs)
    return true_theta, probability_matrix, nonzero_motifs

def _get_germline_nucleotides(args, nonzero_motifs=[]):
    if args.random_gene_len > 0:
        germline_genes = ["FAKE-GENE-%d" % i for i in range(args.n_germlines)]
        if args.guarantee_motifs_showup:
            num_nonzero_motifs = len(nonzero_motifs)
            germline_nucleotides = [get_random_dna_seq(args.random_gene_len + args.motif_len) for i in range(args.n_germlines - num_nonzero_motifs)]
            # Let's make sure that our nonzero motifs show up in a germline sequence at least once
            for motif in nonzero_motifs:
                new_str = get_random_dna_seq(args.random_gene_len/2) + motif + get_random_dna_seq(args.random_gene_len/2)
                germline_nucleotides.append(new_str)
        else:
            # If there are very many germlines, just generate random DNA sequences
            germline_nucleotides = [get_random_dna_seq(args.random_gene_len + args.motif_len) for i in range(args.n_germlines)]
    else:
        # Read parameters from file
        params = read_germline_file(args.germline_path)

        # Select, with replacement, args.n_germlines germline genes from our
        # parameter file and place them into a numpy array.
        germline_genes = np.random.choice(params.index.values, size=args.n_germlines)

        # Put the nucleotide content of each selected germline gene into a
        # corresponding list.
        germline_nucleotides = [row[gene] for gene in germline_genes]

    return germline_nucleotides, germline_genes

def dump_parameters(true_thetas, probability_matrix, args, motif_list):
    # Dump a pickle file of simulation parameters
    pickle.dump([true_thetas, probability_matrix], open(args.output_true_theta, 'w'))

    # Dump a text file of theta for easy viewing
    with open(re.sub('.pkl', '.txt', args.output_true_theta), 'w') as f:
        f.write("True Theta\n")
        lines = get_nonzero_theta_print_lines(true_thetas, motif_list)
        f.write(lines)

def dump_germline_data(germline_nucleotides, germline_genes, args):
    # Write germline genes to file with two columns: name of gene and
    # corresponding sequence.
    with open(args.output_genes, 'w') as outgermlines:
        germline_file = csv.writer(outgermlines)
        germline_file.writerow(['germline_name','germline_sequence'])
        for gene, sequence in zip(germline_genes, germline_nucleotides):
            germline_file.writerow([gene,sequence])

def main(args=sys.argv[1:]):
    args = parse_args()

    # Randomly generate number of mutations or use default
    np.random.seed(args.seed)

    feat_generator = SubmotifFeatureGenerator(motif_len=args.motif_len)
    motif_list = feat_generator.get_motif_list()

    true_thetas, probability_matrix, nonzero_motifs = _generate_true_parameters(motif_list, args)

    germline_nucleotides, germline_genes = _get_germline_nucleotides(args, nonzero_motifs)

    if args.per_target_model:
        simulator = SurvivalModelSimulatorMultiColumn(true_thetas, feat_generator, lambda0=args.lambda0)
    else:
        simulator = SurvivalModelSimulatorSingleColumn(true_thetas, probability_matrix, feat_generator, lambda0=args.lambda0)

    dump_parameters(true_thetas, probability_matrix, args, motif_list)

    dump_germline_data(germline_nucleotides, germline_genes, args)

    # For each germline gene, run survival model to obtain mutated sequences.
    # Write sequences to file with three columns: name of germline gene
    # used, name of simulated sequence and corresponding sequence.
    with open(args.output_file, 'w') as outseqs:
        seq_file = csv.writer(outseqs)
        seq_file.writerow(['germline_name','sequence_name','sequence'])
        for run, (gene, sequence) in \
                enumerate(zip(germline_genes, germline_nucleotides)):

            full_data_samples = [
                simulator.simulate(
                    start_seq=sequence.lower(),
                    censoring_time=args.min_censor_time + 0.1 * np.random.rand(), # allow some variation in censor time
                    with_replacement=args.with_replacement,
                ) for i in range(args.n_taxa)
            ]

            # write to file in csv format
            for i, sample in enumerate(full_data_samples):
                seq_file.writerow([gene, "%s-sample-%d" % (gene, i) , sample.left_flank + sample.end_seq + sample.right_flank])

if __name__ == "__main__":
    main(sys.argv[1:])
