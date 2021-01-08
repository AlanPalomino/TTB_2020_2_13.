from TT_utilities import Case, NL_METHODS, RR_WLEN
from TT_utilities import Record
from multiprocessing import Pool
from scipy.stats import stats
from pathlib import Path
from entropy import spectral_entropy
from hurst import compute_Hc
import pandas as pd
import numpy as np
import pickle
import sys
import re


def hurst_eval(rr):
    H, _, _ = compute_Hc(rr)
    return H


def generate_csv():
    condition_ids = dict(
        atrial_fibrillation=0,
        congestive_heartfailure=1,
        myocardial_infarction=2
    )
    cases_list = unpickle_data()
    csv_name = 'complete_data.csv'
    columns = [
        'case',
        'record',
        'condition',
        'cond_id',
        'hurst',
        'cvnni',
        'cvsd',
        'mean_nni',
        'lf_hf_ratio',
        'total_power',
        'ratio_sd2_sd1',
        'sampen',
    ]
    for m in NL_METHODS:
        columns.extend([
            m['tag'] + '_mean',
            m['tag'] + '_variance',
            m['tag'] + '_skewness',
            m['tag'] + '_spectral_entropy'
        ])
    FULL_CSV = pd.DataFrame(columns=columns)
    for c in cases_list:
        print(f"    > Case {c._case_name}")
        for r in c:
            print(f"\t\t + RECORD {r.name}", end="")
            values = list()
            for k, v in r.N_LINEAR.items():
                s = stats.describe(v)
                values.extend([
                    s[2],                                       # Mean
                    s[3],                                       # Variance
                    s[4],                                       # Skewness
                    spectral_entropy(v, sf=r.fs, method='fft')  # Spectral Entropy
                ])
            row_data = [
                c._case_name,               # Case
                r.name,                     # Record 
                c.pathology,                # Condition
                condition_ids[c.pathology], # Condition ID
                r.hurst,                    # RR Hurst value
                r.time_domain['cvnni'],
                r.time_domain['cvsd'],
                r.time_domain['mean_nni'],
                r.freq_domain['lf_hf_ratio'],
                r.freq_domain['total_power'],
                r.poin_features['ratio_sd2_sd1'],
                r.samp_entropy['sampen']
            ] + values
            FULL_CSV = FULL_CSV.append(
                pd.Series(
                    data=row_data,
                    index=columns
                ), ignore_index=True
            )
            print("[v]")
    FULL_CSV.to_csv(csv_name, index=False)


def unpickle_data():
    p_paths = list(Path('./Pickled').glob('*.pkl')) 
    UNPICKLED = list()
    for pkl in p_paths:
        with pkl.open('rb') as pf:
            UNPICKLED.append(
                pickle.load(pf)
            )
    return UNPICKLED


def process_case(case_path: Path):
    c = Case(case_path)
    c.process()
    print(f"\n\n\t\tCASE {c._case_name} has {len(c)} RECORDS\n\n")
    if len(c) > 0:
        with open(f'Pickled/case_{c._case_name}.pkl', 'wb') as pf:
            pickle.dump(c, pf)


def gen_name(path):
    c_name = re.search('p[0-9]{6}', str(path))[0]
    return path.joinpath(c_name)


def pickle_data():
    RECORD_DIRS = list(Path("./Data").glob("*_p0*")) 
    RECORD_DIRS = [gen_name(p) for p in RECORD_DIRS]
    try:
        RECORD_DIRS = RECORD_DIRS[:int(sys.argv[2])]
        print(f'About to pickle first {len(RECORD_DIRS)} cases')
    except IndexError:
        print(f'About to pickle full data')

    p = Pool()
    p.map(process_case, RECORD_DIRS)
    p.close()


def help():
    global OPTS
    print("""
    SERVER SCRIPT OPTIONS
        Exclusive options for use in server!!
          """)
    for opt in OPTS:
        print(f"{', '.join(opt['opts'])} :")
        print(f"\n{opt['desc']}")


def test_case(ddir: Path):
    c = Case(ddir)
    c.process()
    print(f'\n\n\tTEST CASE with {len(c)} records processed and saved to: case_{c._case_name}.pkl\n\n')
    if len(c) > 0:
        with open(f'Test_{RR_WLEN}ws/case_{c._case_name}.pkl', 'wb') as pf:
            pickle.dump(c, pf)


def run_test():
    n = int(sys.argv[2])
    
    af_dirs = list(Path('Data/').glob('atrial_fibrillation_p*'))[:n]
    mi_dirs = list(Path('Data/').glob('myocardial_infarction_p*'))[:n]
    ch_dirs = list(Path('Data/').glob('congestive_heartfailure_p*'))[:n]

    data_dirs = [ gen_name(d) for d in af_dirs + mi_dirs + ch_dirs]

    p = Pool()
    p.map(test_case, data_dirs)
    p.close()


def main(argv):
    global OPTS
    for opt in OPTS:
        print(f'is {argv} in {opt["opts"]}')
        if argv in opt['opts']:
            opt['func']()
            break
    else:
        print("""
        No valid parameter detected
        Check bellow for valid options:
              """)
        help()


OPTS = [
    {
        'opts': ['-h', '--help'],
        'desc': 'Prints valid options to use the script.',
        'func': help
    },{
        'opts': ['-pd', '--pickle_data'],
        'desc': 'Processes and pickles downloaded data',
        'func': pickle_data
    },{
        'opts': ['-gc', '--generate_csv'],
        'desc': 'Unpickles data and generates the corresponding csv.',
        'func': generate_csv
    },{
        'opts': ['-rt', '--run_test'],
        'desc': 'Run selected test with [n] number of cases per pathology.',
        'func': run_test
    }
]


if __name__ == '__main__':
    print(sys.argv)
    main(sys.argv[1])

