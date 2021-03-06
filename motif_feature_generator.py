import itertools

from common import is_re_match, compute_known_hot_and_cold, NUCLEOTIDES, HOT_COLD_SPOT_REGS, mutate_string
from generic_feature_generator import GenericFeatureGenerator

class MotifFeatureGenerator(GenericFeatureGenerator):
    """
    Feature generator for any kind of motif/kmer model, including nearby motifs and typical context models.

    A motif as it is typically known in a context model will be a feature whose distance to the start makes
    the motif overlap with the mutating position. For example, if
        motif_len=4,
        distance_to_start_of_motif=0
    then this is a 4mer model with the first position mutating. As another example, the classical 5mer model is
        motif_len=5,
        distance_to_start_of_motif=-2
    Effectively, if -distance_to_start_of_motif <= motif_len - 1 then this is a typical submotif model.

    Default is a 3mer with central position mutating.
    """
    def __init__(
            self,
            motif_len=3,
            distance_to_start_of_motif=None,
            model_truncation=None,
            flank_len_offset=0,
            feats_to_remove=None
        ):
        """
        @param motif_len: list of motifs to look for at a distance from mutating position
        @param distance_to_start_of_motif: distance from mutating position to look for nearby motif
        @param model_truncation: ModelTruncation object
        @param feats_to_remove: list of features to remove if a model has not been fit yet
        """
        self.motif_len = motif_len
        if distance_to_start_of_motif is None:
            # default to central base mutating (for odd motif length)
            self.distance_to_start_of_motif = -(motif_len/2)
        else:
            self.distance_to_start_of_motif = distance_to_start_of_motif

        self.flank_len_offset = flank_len_offset

        self.feats_to_remove = model_truncation.feats_to_remove if model_truncation is not None else []
        if feats_to_remove is not None:
            self.feats_to_remove += feats_to_remove

        self.update_feats_after_removing(self.feats_to_remove)

    def update_feats_after_removing(self, feats_to_remove=[]):
        """
        take existing MotifGenerator and update it with features to remove
        """

        all_feature_info_list = [("".join(motif), self.distance_to_start_of_motif) for motif in itertools.product(*([NUCLEOTIDES] * self.motif_len))]
        self.feature_info_list = [feat_tuple for feat_tuple in all_feature_info_list if feat_tuple not in feats_to_remove]

        self.motif_list = [motif for motif, _ in self.feature_info_list]
        self.motif_dict = {motif: i for i, motif in enumerate(self.motif_list)}
        for motif, dist in all_feature_info_list:
            if (motif, dist) in feats_to_remove:
                self.motif_dict[motif] = None

        self.feature_vec_len = len(self.feature_info_list)

    def print_label_from_info(self, info):
        """
        Print what feature this corresponds to.

        @param info: an element of feature_info_list
        """
        if -self.distance_to_start_of_motif in range(self.motif_len):
            # this is a motif feature, so print accordingly
            motif, dist = info
            mut_pos = -self.distance_to_start_of_motif
            print_str = "motif: %s, mut pos: %d" % (motif, mut_pos)
            known_hot_cold = compute_known_hot_and_cold(HOT_COLD_SPOT_REGS, self.motif_len, mut_pos)
            for spot_name, spot_regex in known_hot_cold:
                if is_re_match(spot_regex, motif):
                    print_str += ", %s" % spot_name
                    break
        else:
            print_str = "motif: %s, distance to motif start: %d" % (info[0], info[1])
        return print_str

    def _get_mutating_pos_feat_idx(self, pos, seq_with_flanks, obs_seq_mutation=None):
        """
        The fact that this module takes a flanked sequence means that some of the submotif length information is contained
        in seq_with_flanks, and we need to use flank_len_offset to get the correct feature.

        @param pos: mutating position
        @param seq_with_flanks: sequence to determine motif, flanks included

        @return index of feature vector for this mutating position
        """
        motif = seq_with_flanks[pos + self.flank_len_offset: pos + self.flank_len_offset + self.motif_len]
        feat_idx = self.motif_dict[motif]
        return feat_idx
