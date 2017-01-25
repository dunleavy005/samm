#!/usr/bin/env scons

# Simulate data under various different settings and fit models

# Packages

import os
from os.path import join
from nestly.scons import SConsWrap
from nestly import Nest
from SCons.Script import Environment, Command, AddOption

# Command line options

AddOption('--nreps',
          dest='nreps',
          default=1,
          type='int',
          nargs=1,
          action='store',
          help='number of replicates')

AddOption('--output_name',
          dest='output_name',
          default='output',
          type='str',
          nargs=1,
          help='name of output directory')

env = Environment(ENV=os.environ,
                  NREPS = GetOption('nreps'),
                  OUTPUT_NAME = GetOption('output_name'))


# Set up state
base = {'nreps': env['NREPS'],
        'output_name': env['OUTPUT_NAME']}

# Potential nests: simulation methods, estimation methods, number of germlines,
# number of taxa from germline, frequency of mutation from germline

nest = SConsWrap(Nest(base_dict=base), '_'+env['OUTPUT_NAME'], alias_environment=env)

# Nest for simulation methods
sim_methods = [
    'survival_mini', # In the future, we should make a survival_big
    'shmulate',
]

nest.add(
    'simulation_methods',
    sim_methods)

# Nest for replicates

nest.add(
    'replicate',
    range(env['NREPS']),
    label_func='{:02d}'.format)

# Set the seed to be the replicate number.
nest.add(
    'seed',
    lambda c: [c['replicate']],
    create_dir=False)

# Targets for simulating fake data

@nest.add_target_with_env(env)
def generate(env, outdir, c):
    if c['simulation_methods'] == "shmulate":
        cmd = ['python simulate_from_sampled_gls.py',
               'simulate',
               '--seed',
               c['seed'],
               '--output-file ${TARGETS[0]}',
               '--output-genes ${TARGETS[1]}']
        return env.Command(
            [join(outdir, 'seqs.csv'), join(outdir, 'genes.csv')],
            [],
            ' '.join(map(str, cmd)))
    elif c['simulation_methods'] == "survival_mini":
        cmd = ['python simulate_from_survival.py',
               '--seed',
               c['seed'],
               '--n-taxa',
               5,
               '--n-germlines',
               40,
               '--motif-len',
               3,
               '--random-gene-len',
               50,
               '--min-censor-time',
               3.0,
               '--ratio-nonzero',
               0.2,
               '--output-true-theta ${TARGETS[0]}',
               '--output-file ${TARGETS[1]}',
               '--output-genes ${TARGETS[2]}']
        return env.Command(
            [join(outdir, 'true_theta.txt'), join(outdir, 'seqs.csv'), join(outdir, 'genes.csv')],
            [],
            ' '.join(map(str, cmd)))
    else:
        raise NotImplementedError()

## Future nests

# Nest for model fitting
@nest.add_target_with_env(env)
def fit_context_model(env, outdir, c):
    cmd = ['python fit_context_model.py',
           '--seed',
           c['seed'],
           '--motif-len',
           3,
           '--lasso-params',
           "0.05,0.01,0.002",
           '--num-threads',
           10,
           '--input-file ${SOURCES[0]}',
           '--input-genes ${SOURCES[1]}',
           '--log-file ${TARGETS[0]}',
           '--out-file ${TARGETS[1]}']
    return env.Command(
        [join(outdir, 'context_log.txt'), join(outdir, 'context_log.pkl')],
        [join(outdir, 'seqs.csv'), join(outdir, 'genes.csv')],
        ' '.join(map(str, cmd)))

# Aggregate over different fitting methods

# Aggregate over all replicates

# Plot results
