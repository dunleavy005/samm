#ifndef MODELS_H
#define MODELS_H

#include <string>
#include <vector>

using namespace std;

typedef int Nuc; // 0 = A, 1 = T, 2 = C, G = 3
typedef vector<Nuc> VectorNucleotide; // Nucleotide sequence

// Indices of the feature at each position
// Positions at risk of mutating have a nonnegative feature index
// Positions no longer in the risk group have a -1 feature index
typedef vector<int> VectorFeature;
typedef vector<int> VectorOrder; // Position indices by observed mutation order
typedef vector<double> ThetaSums; // Theta * psi for every position in sequence

class ObservedSample {
  public:
    VectorNucleotide start_seq;
    VectorNucleotide end_seq;
    VectorFeature start_seq_features;
    ObservedSample(
      VectorNucleotide s,
      VectorNucleotide e,
      VectorFeature f
    ):start_seq{s}, end_seq{e}, start_seq_features{f} { };
};

class MutationStep {
  public:
    VectorNucleotide nuc_vec;
    VectorFeature feature_vec;
    // A container that might contain a ThetaSums object
    // CHeck if the first elem is True before reading the second value
    pair<bool, ThetaSums> theta_sum_option;

    MutationStep(
      VectorNucleotide nucs,
      VectorFeature feats,
      pair<bool, ThetaSums> t_sum_option
    ): nuc_vec{nucs}, feature_vec{feats}, theta_sum_option{t_sum_option} {};
};

class OrderedMutationSteps {
  public:
    vector<shared_ptr<MutationStep>> mut_steps;
    VectorOrder order_vec;

    // Initialize with the observed sample and the order under consideration
    OrderedMutationSteps(
      const ObservedSample &obs_sample,
      VectorOrder order_vec
    );
    // Update the mutation step with mut_step
    void set(
      int step_i,
      shared_ptr<MutationStep> mut_step
    );
};

#endif
