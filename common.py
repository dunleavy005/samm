import numpy as np
import re
import random
import warnings

DEBUG = False

NUM_NUCLEOTIDES = 4
NUCLEOTIDES = "acgt"
DEGENERATE_NUCLEOTIDE = "n"
NUCLEOTIDE_SET = set(["a", "c", "g", "t"])
NUCLEOTIDE_DICT = {
    "a": 0,
    "c": 1,
    "g": 2,
    "t": 3,
}
ZSCORE = 1.65
ZSCORE_95 = 1.96
ZERO_THRES = 1e-6
MAX_TRIALS = 10

COMPLEMENT_DICT = {
    'A': 'T',
    'G': 'C',
    'C': 'G',
    'T': 'A',
    'Y': 'R',
    'R': 'Y',
    'S': 'S',
    'W': 'W',
    'M': 'K',
    'K': 'M',
    'B': 'V',
    'D': 'H',
    'H': 'D',
    'V': 'B',
    'N': 'N',
}

DEGENERATE_BASE_DICT = {
    'A': 'a',
    'G': 'g',
    'C': 'c',
    'T': 't',
    'Y': '[ct]',
    'R': '[ag]',
    'S': '[gc]',
    'W': '[at]',
    'M': '[ac]',
    'K': '[gt]',
    'B': '[cgt]',
    'D': '[agt]',
    'H': '[act]',
    'V': '[acg]',
    'N': '[agct]',
}

HOT_COLD_SPOT_REGS = [
        {'central': 'G', 'left_flank': 'R', 'right_flank': 'YW', 'hot_or_cold': 'hot'},
        {'central': 'A', 'left_flank': 'W', 'right_flank': '', 'hot_or_cold': 'hot'},
        {'central': 'C', 'left_flank': 'SY', 'right_flank': '', 'hot_or_cold': 'cold'},
        {'central': 'G', 'left_flank': '', 'right_flank': 'YW', 'hot_or_cold': 'hot'},
]
INT8_MAX = 127

FUSED_LASSO_PENALTY_RATIO = [1./4, 1./2, 1., 2., 4.]

def process_mutating_positions(motif_len_vals, positions_mutating):
    max_motif_len = max(motif_len_vals)
    if positions_mutating is None:
        # default to central base mutating
        positions_mutating = [[m/2] for m in motif_len_vals]
        max_mut_pos = [[max_motif_len/2]]
    else:
        positions_mutating = [[int(m) for m in positions.split(',')] for positions in positions_mutating.split(':')]
        max_mut_pos = get_max_mut_pos(motif_len_vals, positions_mutating)
    return positions_mutating, max_mut_pos

def get_max_mut_pos(motif_len_vals, positions_mutating):
    max_motif_len = max(motif_len_vals)
    for motif_len, positions in zip(motif_len_vals, positions_mutating):
        for m in positions:
            assert(m in range(motif_len))
    max_mut_pos = [mut_pos for mut_pos, motif_len in zip(positions_mutating, motif_len_vals) if motif_len == max_motif_len]
    return max_mut_pos

def get_batched_list(my_list, num_batches):
    batch_size = max((int(len(my_list)/num_batches) + 1), 1)
    batched_list = []
    for i in range(num_batches + 1):
        additional_batch = my_list[i * batch_size: (i+1) * batch_size]
        if len(additional_batch):
            batched_list.append(additional_batch)
    return batched_list

def return_complement(kmer):
    return ''.join([COMPLEMENT_DICT[nuc] for nuc in kmer[::-1]])

def compute_known_hot_and_cold(hot_or_cold_dicts, motif_len=5, left_motif_flank_len=None):
    """
    Known hot and cold spots were constructed on a 5mer model, so "N" pad
    longer motifs and subset shorter ones
    """
    if left_motif_flank_len is None:
        left_motif_flank_len = motif_len / 2
    kmer_list = []
    hot_or_cold_list = []
    hot_or_cold_complements = []
    for spot in hot_or_cold_dicts:
        hot_or_cold_complements.append({'central': return_complement(spot['central']),
                'left_flank': return_complement(spot['right_flank']),
                'right_flank': return_complement(spot['left_flank']),
                'hot_or_cold': spot['hot_or_cold']})

    for spot in hot_or_cold_dicts + hot_or_cold_complements:
        if len(spot['left_flank']) > left_motif_flank_len or \
            len(spot['right_flank']) > motif_len - left_motif_flank_len - 1:
                # this hot/cold spot is not a part of our motif size
                continue

        left_pad = spot['left_flank'].rjust(left_motif_flank_len, 'N')
        right_pad = spot['right_flank'].ljust(motif_len - left_motif_flank_len - 1, 'N')
        kmer_list.append(left_pad + spot['central'] + right_pad)
        hot_or_cold_list.append(spot['hot_or_cold'])

    hot_cold_regs = []
    for kmer, hot_or_cold in zip(kmer_list, hot_or_cold_list):
        hot_cold_regs.append([' - '.join([kmer.replace('N', ''), hot_or_cold]),
            ''.join([DEGENERATE_BASE_DICT[nuc] for nuc in kmer])])
    return hot_cold_regs

def get_randint():
    """
    @return a random integer from a large range
    """
    return np.random.randint(low=0, high=2**31)

def get_num_nonzero(theta):
    nonzero_idx = np.logical_and(np.isfinite(theta), np.abs(theta) > ZERO_THRES)
    return np.sum(nonzero_idx)

def get_num_unique_theta(theta):
    theta_flat = theta.flatten()
    sorted_idx = np.argsort(theta_flat)
    diffs = np.diff(theta_flat[sorted_idx])
    num_unique = 1 + np.sum(diffs > ZERO_THRES)
    return num_unique

def is_re_match(regex, submotif):
    match_res = re.match(regex, submotif)
    return match_res is not None

def get_nonzero_theta_print_lines(theta, feat_gen):
    """
    @return a string that summarizes the theta vector/matrix
    """
    lines = []
    for i in range(theta.shape[0]):
        for j in range(theta.shape[1]):
            if np.isfinite(theta[i,j]) and np.abs(theta[i,j]) > ZERO_THRES:
                # print the whole line if any element in the theta is nonzero
                thetas = theta[i,]
                lines.append((
                    thetas[np.isfinite(thetas)].sum(),
                    "%s (%s)" % (thetas, feat_gen.print_label_from_idx(i)),
                ))
                break
    sorted_lines = sorted(lines, key=lambda s: s[0])
    if len(sorted_lines):
        return "\n".join([l[1] for l in sorted_lines])
    else:
        return "ALL ZEROES"

def mutate_string(begin_str, mutate_pos, mutate_value):
    """
    Mutate a string
    """
    return "%s%s%s" % (begin_str[:mutate_pos], mutate_value, begin_str[mutate_pos + 1:])

def sample_multinomial(pvals):
    """
    Sample 1 item from multinomial and get the index of this sample
    will renormalize pvals if needed
    """
    norm_pvals = np.array(pvals)/np.sum(pvals)
    assert(np.sum(norm_pvals) > 1 - 1e-10)
    sample = np.random.multinomial(1, norm_pvals)
    return np.where(sample == 1)[0][0]

def get_random_dna_seq(seq_length, nucleotide_probs=[0.25, 0.25, 0.25, 0.25]):
    """
    Generate a random dna sequence
    """
    random_nucleotides = [
        NUCLEOTIDES[sample_multinomial(nucleotide_probs)] for i in range(seq_length)
    ]
    return "".join(random_nucleotides)

def get_standard_error_ci_corrected(values, zscore, pen_val_diff):
    """
    @param values: the values that are correlated
    @param zscore: the zscore to form the confidence interval
    @param pen_val_diff: difference of the total penalized values (the negative log likelihood plus some penalty)

    @returns
        the standard error of the values correcting for auto-correlation between the values
        the lower bound of the mean of the total penalized value using the standard error and the given zscore
        the upper bound of the mean of the total penalized value using the standard error and the given zscore
        effective sample size (negative if the values are essentially constant)
    Calculate the autocorrelation, then the effective sample size, scale the standard error appropriately the effective sample size
    """
    mean = np.mean(values)
    var = np.var(values)

    # If the values are essentially constant, then the autocorrelation is zero.
    # (There are numerical stability issues if we go thru the usual calculations)
    if var < 1e-10:
        return 0, mean, mean, -1

    # Calculate auto-correlation
    # Definition from p. 151 of Carlin/Louis:
    # \kappa = 1 + 2\sum_{k=1}^\infty \rho_k
    # So we don't take the self-correlation
    # TODO: do we worry about cutting off small values?
    # Glynn/Whitt say we could use batch estimation with batch sizes going to
    # infinity. Is this a viable option?
    result = np.correlate(values - mean, values - mean, mode='full')
    result = result[result.size/2:]
    result /= (var * np.arange(values.size, 0, -1))

    # truncate sum once the autocorrelation is negative
    neg_indices = np.where(result < 0)
    neg_idx = result.size
    if len(neg_indices) > 0 and neg_indices[0].size > 1:
        neg_idx = np.where(result < 0)[0][0]
    autocorr = 1 + 2*np.sum(result[1:neg_idx])

    # Effective sample size calculation
    ess = values.size/autocorr

    if var/ess < 0:
        return None, -np.inf, np.inf, ess
    else:
        # Corrected standard error
        ase = np.sqrt(var/ess)
        return ase, pen_val_diff - zscore * ase, pen_val_diff + zscore * ase, ess

def soft_threshold(theta, thres):
    """
    The soft thresholding function S is zero in the range [-thresh, thresh],
    theta+thresh when theta < -thresh and theta-thresh when theta > thresh.

    @param theta: a numpy vector
    @param thres: the amount to threshold theta by
    @return theta that is soft-thresholded with constant thres
    """
    return np.maximum(theta - thres, 0) + np.minimum(theta + thres, 0)

def process_degenerates_and_impute_nucleotides(start_seq, end_seq, max_flank_len, threshold=0.1):
    """
    Process the degenerate characters in sequences:
    1. Replace unknown characters with "n"
    2. Collapse runs of "n"s into one of max_flank_len
    3. Replace all interior "n"s with nonmutating random nucleotide

    @param start_seq: starting sequence
    @param end_seq: ending sequence
    @param max_flank_len: max flank length; needed to determine length of collapsed "n" run
    @param threshold: if proportion of "n"s in a sequence is larger than this then
        throw a warning

    @return processed_start_seq: starting sequence with interior "n"s collapsed and imputed
    @return processed_end_seq: ending sequence with same
    @return collapse_list: list of tuples of (index offset, start index of run of "n"s, end index of run of "n"s) for bookkeeping later
    """
    assert(len(start_seq) == len(end_seq))

    # replace all unknowns with an "n"
    processed_start_seq = re.sub('[^agctn]', 'n', start_seq)
    processed_end_seq = re.sub('[^agctn]', 'n', end_seq)

    # conform unknowns and collapse "n"s
    repl = 'n' * (max_flank_len)
    pattern = repl + 'n+' if max_flank_len > 0 else 'n'
    collapse_list = []
    if re.search('n', processed_end_seq) or re.search('n', processed_start_seq):
        # if one sequence has an "n" but the other doesn't, make them both have "n"s
        start_list = list(processed_start_seq)
        end_list = list(processed_end_seq)
        for idx in re.finditer('n', processed_end_seq):
            start_list[idx.start()] = 'n'
        processed_start_seq = ''.join(start_list)
        for idx in re.finditer('n', processed_start_seq):
            end_list[idx.start()] = 'n'
        processed_end_seq = ''.join(end_list)

        # ensure there are not too many internal "n"s
        seq_len = len(processed_end_seq)
        start_idx = re.search('[^n]', processed_end_seq).start()
        end_idx = seq_len - re.search('[^n]', processed_end_seq[::-1]).start()
        interior_end_seq = processed_end_seq[start_idx:end_idx]
        num_ns = interior_end_seq.count('n')
        seq_len = len(interior_end_seq)
        if num_ns > threshold * seq_len:
            warnings.warn("Sequence of length {0} had {1} unknown bases".format(seq_len, num_ns))

        # now collapse interior "n"s
        for match in re.finditer(pattern, interior_end_seq):
            # num "n"s removed
            # starting position of "n"s removed
            collapse_list.append((max_flank_len, match.regs[0][0], match.regs[0][1]))

        interior_start_seq = processed_start_seq[start_idx:end_idx]
        interior_start_seq = re.sub(pattern, repl, interior_start_seq)
        interior_end_seq = re.sub(pattern, repl, interior_end_seq)

        # generate random nucleotide if an "n" occurs in the middle of a sequence
        for match in re.compile('n').finditer(interior_start_seq):
            random_nuc = random.choice(NUCLEOTIDES)
            interior_start_seq = mutate_string(interior_start_seq, match.start(), random_nuc)
            interior_end_seq = mutate_string(interior_end_seq, match.start(), random_nuc)

        out_start_seq = processed_start_seq[:start_idx] + interior_start_seq + processed_start_seq[end_idx:]
        out_end_seq = processed_end_seq[:start_idx] + interior_end_seq + processed_end_seq[end_idx:]
    else:
        out_start_seq = processed_start_seq
        out_end_seq = processed_end_seq

    return out_start_seq, out_end_seq, collapse_list

def get_idx_differ_by_one_character(s1, s2):
    """
    Return the index at strings s1 and s2 which differ by one character. If the strings
    are the same or differ by more than one character, return None
    """
    count_diffs = 0
    idx_differ = None
    for i, (a, b) in enumerate(zip(s1, s2)):
        if a != b:
            if count_diffs:
                return None
            count_diffs += 1
            idx_differ = i
    return idx_differ

def get_target_col(sample, mutation_pos):
    """
    @param sample: ObservedSequenceMutations
    @returns the index of the column in the hazard rate matrix for the target nucleotide
    """
    return NUCLEOTIDE_DICT[sample.end_seq[mutation_pos]] + 1

def initialize_theta(theta_shape, possible_theta_mask, zero_theta_mask):
    """
    Initialize theta
    @param possible_theta_mask: set the negative of this mask to negative infinity theta values
    @param zero_theta_mask: set the negative of this mask to negative infinity theta values
    """
    theta = np.random.randn(theta_shape[0], theta_shape[1]) * 1e-3
    # Set the impossible thetas to -inf
    theta[~possible_theta_mask] = -np.inf
    # Set particular thetas to zero upon request
    theta[zero_theta_mask] = 0
    return theta

def create_theta_idx_mask(zero_theta_mask_refit, possible_theta_mask):
    """
    From an aggregate theta, creates a matrix with the index of the hierarchical theta
    """
    theta_idx_counter = np.ones(possible_theta_mask.shape, dtype=int) * -1
    theta_mask = ~zero_theta_mask_refit & possible_theta_mask
    idx = 0
    for col in range(theta_mask.shape[1]):
        for row in range(theta_mask.shape[0]):
            if theta_mask[row, col]:
                theta_idx_counter[row, col] = idx
                idx += 1
    return theta_idx_counter

def pick_best_model(fitted_models):
    """
    Select the one with largest (pseudo) log lik ratio
    """
    if isinstance(fitted_models[0], list):
        good_models = [f_model for f_model_list in fitted_models for f_model in f_model_list if f_model.has_refit_data]
    else:
        good_models = [f_model for f_model in fitted_models if f_model.has_refit_data]
    if len(good_models) == 0:
        return None

    for max_idx in reversed(range(len(good_models))):
        if good_models[max_idx].log_lik_ratio_lower_bound > 0:
            break
    best_model = good_models[max_idx]
    return best_model

def get_interval(xs, zscore):
    """
    @return the interval around the mean of `xs` with width std_err * `zscore`
    """
    mean = np.mean(xs)
    std_err = np.sqrt(np.var(xs)/xs.size)
    return (mean - zscore * std_err, mean + zscore * std_err)

def get_zero_theta_mask(theta):
    zeroed_thetas = (np.abs(theta) < ZERO_THRES)
    zeroed_or_inf_thetas = zeroed_thetas | (~np.isfinite(theta))
    feats_to_remove_mask = np.sum(zeroed_or_inf_thetas, axis=1) == theta.shape[1]
    return zeroed_thetas[~feats_to_remove_mask,:]

def get_model_result_print_lines(model_result):
    """
    @return a string that summarizes the theta vector/matrix
    """
    feat_gen = model_result.refit_feature_generator
    lines = []
    if model_result.has_refit_data:
        theta = model_result.refit_theta
    else:
        theta = model_result.penalized_theta
    for i in range(theta.shape[0]):
        for j in range(theta.shape[1]):
            if np.isfinite(theta[i,j]) and np.abs(theta[i,j]) > ZERO_THRES:
                # print the whole line if any element in the theta is nonzero
                thetas = theta[i,]
                print_str = "%.3f" % theta[i,0]
                if model_result.has_conf_ints:
                    print_str += ", [%.3f, %.3f]" % (model_result.conf_ints[i, 0], model_result.conf_ints[i, 2])
                print_str += ", (%s)" % feat_gen.print_label_from_idx(i)
                lines.append((thetas[np.isfinite(thetas)].sum(), print_str))
                break
    sorted_lines = sorted(lines, key=lambda s: s[0])
    return "\n".join([l[1] for l in sorted_lines])
