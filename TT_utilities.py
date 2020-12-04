# -*- coding: utf-8 -*-
# %%

# ===================== Librerias Utilizadas ====================== #
from biosppy.utils import ReturnTuple
from matplotlib import pyplot as plt
import matplotlib as mpl
from scipy.signal import find_peaks
from scipy.stats import stats
from collections import Counter
import pyhrv.nonlinear as nl
from wfdb import processing
from itertools import chain
from pathlib import Path
import seaborn as sns
import pandas as pd
import numpy as np
import entropy
import biosppy
import pyhrv
import time
import wfdb
import re

# ================= Funciones y Definiciones ====================== #

def timeit(func):
    def timed_func(*args, **kwargs):
        s_time = time.time()
        r = func(*args, **kwargs)
        e_time = time.time()
        print(f"Function {func.__name__} execution time: {e_time - s_time}")
        return r
    return timed_func


# ================= Importando Bases de Datos
class Case():
    """
    Generador del compendio de registros y señales para un caso particular.

    Object looks for files in the directory provided, to build a list
    of records from the same case.
    """

    def __init__(self, case_dir: Path, sig_thresh: int=1000):
        self.RECORDS = []
        self._case_dir = case_dir
        self._case_name = case_dir.stem
        self._sig_thresh = sig_thresh
        self.pathology = re.search(
            f"([a-z_]*)(_{self._case_name})",
            str(case_dir)
        ).groups()[0]
        self._get_records()

    def __str__(self):
        """Prints data of self and internal records"""
        print(f"Case: {self._case_name} - Records above {self._sig_thresh} samples ->")
        for record in self.RECORDS:
            print(record)
        return f"{5*' * '}End of case {self._case_name}{5*' * '}"

    def __len__(self):
        """Returns the number of records contained in the case"""
        return len(self.RECORDS)

    def __iter__(self):
        return CaseIterator(self)

    def __getitem__(self, index):
        """Extract record as a list"""
        return self.RECORDS[index]

    def _get_records(self):
        for hea_path in self._case_dir.glob(f"{self._case_name}*[0-9].hea"):
            h = wfdb.rdheader(str(hea_path.parent.joinpath(hea_path.stem)))
            self._get_names(h.seg_name, h.seg_len)

    def _get_names(self, seg_names: list, seg_lens: list):
        for name, slen in zip(seg_names, seg_lens):
            if slen < self._sig_thresh or "~" in name:
                continue
            self._get_data(self._case_dir.joinpath(name))

    def _get_data(self, path: Path):
        self.RECORDS.append(
            Record(path, self._case_name)
        )

    def _linear_analysis(self):
        for record in self.RECORDS:
            record._linear_analysis(self._main_signal)

    def _non_linear_analysis(self):
        for record in self.RECORDS:
            record._non_linear_analysis(self._main_signal)

    def process(self, mode: str="nonlinear"):
        def run_all(d: dict):
            [v() for k, v in d.items() if k != "full"]
            return

        analysis_selector = {
            "linear": self._linear_analysis,
            "nonlinear": self._non_linear_analysis
        }

        top_signals = Counter(chain.from_iterable([r.sig_names for r in self.RECORDS])).most_common()
        for s, c in top_signals:
            if s in ["APB", "PLETH R", "RESP"]:
                continue
            self._main_signal = s
            print(f" > Optimal signal found is '{s}', present in {c}/{len(self)}")
            break
        else:
            print(f"> CASE {self._case_name} Has no valid signal for processing.")
            return
        if mode == "full":
            run_all(analysis_selector)
            return
        analysis_selector.get(mode)()
        return
            


class CaseIterator:
    """Iterator class for Case object"""
    def __init__(self, case):
        self._case = case
        self._index = 0

    def __next__(self):
        """Returns the next record from the Case object's list of records"""
        if self._index < len(self._case):
            self._index += 1
            return self._case.RECORDS[self._index-1]
        raise StopIteration


class Record():
    def __init__(self, record_dir: Path, case: str):
        reco = wfdb.rdrecord(str(record_dir))
        head = wfdb.rdheader(str(record_dir))
        self.record_dir = record_dir
        self.case = case
        self.name = head.record_name
        self.time = head.base_time
        self.date = head.base_date
        self.fs = reco.fs
        self.slen = reco.sig_len
        self.n_sig = reco.n_sig
        self.sig_names = reco.sig_name
        self.units = reco.units
        self.rr = None

    def __str__(self):
        return f"\t Record: {self.name}, Length:{self.slen}, \t# of signals: {self.n_sig} -> {self.sig_names}"

    def __getitem__(self, item):
        try:
            sig_idx = self.sig_names.index(item)
            signals = self._get_signals()
            return signals[:, sig_idx]
        except ValueError:
            raise KeyError(f"'{item}' isn't a valid key. Signals in record:{self.sig_names}")

    def _get_signals(self):
        reco = wfdb.rdrecord(str(self.record_dir))
        return reco.p_signal

    def _linear_analysis(self, signal: str):
        if self.rr is None:
            # get RR
            raw_signal = self[signal]
            self.rr = np.diff(get_peaks(raw_signal, self.fs))
        print("raw: ", raw_signal[:10])
        print("rr: ", self.rr[:10])
        m, v, s, k = linearWindowing(self.rr, w_len=1024, over=0.95)
        self.LINEAR = {
            "means": m,
            "var": v,
            "skewness": s,
            "kurtosis": k
        }
        return
    
    def _non_linear_analysis(self, signal: str):
        if self.rr is  None:
            # get RR
            raw_signal = self[signal]
            self.rr = np.diff(get_peaks(raw_signal, self.fs))
        a, s, h, d = nonLinearWindowing(self.rr, w_len=2048, over=0.95)
        self.N_LINEAR = {
            "app_ent": a,
            "samp_ent": s,
            "hfd": h,
            "dfa": d
        }
        return
        
        


    def plot(self):
        fig, axs = plt.subplots(self.n_sig, 1)
        signals = self._get_signals()

        fig.suptitle(f"Record {self.name} of case {self.case}")
        for a, n, u, s in zip(axs, self.sig_names, self.units, list(zip(*signals))):
            a.set_ylabel(f"{n}/{u}")
            a.plot(s)
        axs[-1].set_xlabel("Samples")
        plt.show()


def get_peaks(raw_signal: np.ndarray, fs: int) -> np.ndarray:
    MAX_BPM = 220
    raw_peaks, _ = find_peaks(raw_signal, distance=int((60/MAX_BPM)/(1/fs)))
    med_peaks = processing.correct_peaks(raw_signal, raw_peaks, 30, 35, peak_dir='up')
    wel_peaks = processing.correct_peaks(raw_signal, med_peaks, 30, 35, peak_dir='up')
    return wel_peaks[~np.isnan(wel_peaks)]


# ================= Ventaneo de señales

def linearWindowing(rr_signal: np.ndarray, w_len: int, over: float):
    """
    Evaluates rr with linear functions based on a rolling window.

    rr_signal   :: RR vector of time in seconds
    w_len       :: Amount of data points per window analysis
    over        :: Defines overlapping between windows
    """
    means, var, skew, kurt = list(), list(), list(), list()
    step = int(w_len*(1-over))

    for idx in range(0, len(rr_signal)-w_len, step):
        window_slice = slice(idx, idx+w_len)
        ds = stats.describe(rr_signal[window_slice])
        means.append(ds[2])
        var.append(ds[3])
        skew.append(ds[4])
        kurt.append(ds[5])

    return means, var, skew, kurt


def nonLinearWindowing(rr_signal: np.ndarray, w_len: int, over: float):
    """
    Evaluates rr with non-linear functions based on a rolling window.

    rr_signal   :: RR vector of time in seconds
    w_len       :: Amount of data points per window analysis
    over        :: Defines overlapping between windows
    """
    app_ent, samp_ent, hfd, dfa = list(), list(), list(), list()
    step = int(w_len*(1-over))

    for idx in range(0, len(rr_signal)-w_len, step):
        window_slice = slice(idx, idx+w_len)
        rr_window = rr_signal[window_slice]
        app_ent.append(entropy.app_entropy(rr_window, order=2, metric='chebyshev'))
        samp_ent.append(entropy.sample_entropy(rr_window, order=2, metric='chebyshev'))
        hfd.append(entropy.fractal.higuchi_fd(rr_window, kmax=10))
        dfa.append(entropy.fractal.detrended_fluctuation(rr_window))

    return app_ent, samp_ent, hfd, dfa


def poincarePlot(nni=None, rpeaks=None, show=True, figsize=None, ellipse=True, vectors=True, legend=True, marker='o'):
    
    # Check input values
    nn = pyhrv.utils.check_input(nni, rpeaks)

    # Prepare Poincaré data
    x1 = np.asarray(nn[:-1])
    x2 = np.asarray(nn[1:])

    # SD1 & SD2 Computation
    sd1 = np.std(np.subtract(x1, x2) / np.sqrt(2))
    sd2 = np.std(np.add(x1, x2) / np.sqrt(2))

    # Area of ellipse
    area = np.pi * sd1 * sd2

        
    # Show plot
    if show == True:

        # Area of ellipse
        area = np.pi * sd1 * sd2

        # Prepare figure
        if figsize is None:
            figsize = (6, 6)
            fig = plt.figure(figsize=figsize)
            fig.tight_layout()
            ax = fig.add_subplot(111)

            ax.set_title(r'Diagrama de $Poincar\acute{e}$')
            ax.set_ylabel('$RR_{i+1}$ [ms]')
            ax.set_xlabel('$RR_i$ [ms]')
            ax.set_xlim([np.min(nn) - 50, np.max(nn) + 50])
            ax.set_ylim([np.min(nn) - 50, np.max(nn) + 50])
            ax.grid()
            ax.plot(x1, x2, 'r%s' % marker, markersize=2, alpha=0.5, zorder=3)

            # Compute mean NNI (center of the Poincaré plot)
            nn_mean = np.mean(nn)

            # Draw poincaré ellipse
        if ellipse:
            ellipse_ = mpl.patches.Ellipse((nn_mean, nn_mean), sd1 * 2, sd2 * 2, angle=-45, fc='k', zorder=1)
            ax.add_artist(ellipse_)
            ellipse_ = mpl.patches.Ellipse((nn_mean, nn_mean), sd1 * 2 - 1, sd2 * 2 - 1, angle=-45, fc='lightyellow', zorder=1)
            ax.add_artist(ellipse_)

        # Add poincaré vectors (SD1 & SD2)
        if vectors:
            arrow_head_size = 3
            na = 4
            a1 = ax.arrow(
                nn_mean, nn_mean, (-sd1 + na) * np.cos(np.deg2rad(45)), (sd1 - na) * np.sin(np.deg2rad(45)),
                head_width=arrow_head_size, head_length=arrow_head_size, fc='g', ec='g', zorder=4, linewidth=1.5)
            a2 = ax.arrow(
                nn_mean, nn_mean, (sd2 - na) * np.cos(np.deg2rad(45)), (sd2 - na) * np.sin(np.deg2rad(45)),
                head_width=arrow_head_size, head_length=arrow_head_size, fc='b', ec='b', zorder=4, linewidth=1.5)
            a3 = plt.patches.Patch(facecolor='white', alpha=0.0)
            a4 = plt.patches.Patch(facecolor='white', alpha=0.0)
            ax.add_line(plt.lines.Line2D(
                (min(nn), max(nn)),
                (min(nn), max(nn)),
                c='b', ls=':', alpha=0.6))
            ax.add_line(plt.lines.Line2D(
                (nn_mean - sd1 * np.cos(np.deg2rad(45)) * na, nn_mean + sd1 * np.cos(np.deg2rad(45)) * na),
                (nn_mean + sd1 * np.sin(np.deg2rad(45)) * na, nn_mean - sd1 * np.sin(np.deg2rad(45)) * na),
                c='g', ls=':', alpha=0.6))

            # Add legend
            if legend:
                ax.legend(
                    [a1, a2, a3, a4],
                    ['SD1: %.3f$ms$' % sd1, 'SD2: %.3f$ms$' % sd2, 'S: %.3f$ms^2$' % area, 'SD1/SD2: %.3f' % (sd1/sd2)],
                    framealpha=1)

        plt.show()
            # Output
        args = (fig, sd1, sd2, sd2/sd1, area)
        names = ('poincare_plot', 'sd1', 'sd2', 'sd_ratio', 'ellipse_area')

    elif show == False:
        # Output
        args = (sd1, sd2, sd2/sd1, area)
        names = ('sd1', 'sd2', 'sd_ratio', 'ellipse_area')
        #result = biosppy.utils.ReturnTuple(args, names)

        
    return biosppy.utils.ReturnTuple(args, names)


def Poincare_Windowing(rr_signal, w_len, over, mode="sample",plotter=False):
    """
    rr_signal :: RR vector of time in seconds
    w_time    :: Defines window time in seconds
    over      :: Defines overlapping between windows
    l_thresh  :: Gets lower threshold of window
    mode      :: Sets mode of windowing;
                    "sample" - Same sized windows, iterates by sample count.
                    "time" - Variable sized windows, iterates over time window.
    """
        
    poin_r =list()

    step = int(w_len*(1-over))
        
    if mode == "time":
        time_vec = np.cumsum(rr_signal)
        l_thresh = time_vec[0]
        while l_thresh < max(time_vec)-w_len:
            window = np.where(np.bitwise_and((l_thresh < time_vec), (time_vec < (l_thresh+w_len))))
            rr_window = RR[window]
                
            if plotter == True:
                poincare_results = nl.poincare(rr_window,show=True,figsize=None,ellipse=True,vectors=True,legend=True)
                poin_r.append(poincare_results["sd_ratio"])
            elif plotter == False:
                poincare_results = poincarePlot(rr_window,show=False)
                poin_r.append(poincare_results["sd_ratio"])
            
        
            l_thresh += step

    elif mode == "sample":
        for rr_window in [rr_signal[i:i+w_len] for i in range(0, len(rr_signal)-w_len, step)]:
            if plotter == True:
                poincare_results = nl.poincare(rr_window,show=True,figsize=None,ellipse=True,vectors=True,legend=True)
                poin_r.append(poincare_results["sd_ratio"])
            elif plotter == False:
                poincare_results = poincarePlot(rr_window,show=False)
                poin_r.append(poincare_results["sd_ratio"])
            
    return poin_r



_m_config = {"window": 1024, "overlap": 0.95}
def add_moments(row: pd.Series, mo_config: dict=_m_config):
    """Applies five moments to Series object"""
    means, var, skew, kurt = linearWindowing(row.rr, mo_config["window"], mo_config["overlap"])

    row["M1"] = means
    row["M2"] = var
    row["M3"] = skew
    row["M4"] = kurt
    row["CV"] = np.divide(var, means)
    return row


_nonm_config = {"window": 2048, "overlap": 0.95}
def add_nonlinear(row: pd.Series, mo_config: dict=_nonm_config):
    """Applies four non-linear equations to Series object"""
    app_ent, samp_ent, hfd, dfa = nonLinearWindowing(row.rr, mo_config["window"], mo_config["overlap"])
    poin = Poincare_Windowing(row.rr, mo_config["window"], mo_config["overlap"], mode="sample",plotter=False)

    row["AppEn"] = app_ent
    row["SampEn"] = samp_ent
    row["HFD"] = hfd
    row["DFA"] = dfa
    row["SD_ratio"] = poin
    return row



def distribution_cases(db, caso):
    caso = str(caso)
    moment =['M1','M2','M3','M4','CV']
    m_label =['Media','Varianza','Skewsness','Curtosis','Coeficiente de Variación ']
    for idx in range(len(moment)):
            
        title = 'Distribución de ' + m_label[idx] +' en Casos de ' + caso
        xlab = 'Valor de '+ m_label[idx]
        plt.figure(figsize=(10,7), dpi= 100)
        plt.gca().set(title=title, ylabel='Frecuencia',xlabel=xlab)
        for i in range(len(db.index)):

            ms = db.iloc[i][moment[idx]]
                
            lab = db.iloc[i]['record']
            # Plot Settings
            kwargs = dict(hist_kws={'alpha':.6}, kde_kws={'linewidth':2})
            sns.distplot(ms, label= lab ,rug=False, hist=False,**kwargs)
                
            #X_axis limits
            #x_min = int(np.min(ms)) + 10
            #x_max = int(np.max(ms))+10
            #plt.xlim(x_min,x_max)
            #lims = plt.gca().get_xlim()
            #i = np.where( (ms > lims[0]) &  (ms < lims[1]) )[0]
            #plt.gca().set_xlim( ms[i].min(), ms[i].max() )
            plt.autoscale(enable=True, axis='y', tight=True)
        #show()
        plt.autoscale()
        plt.legend()
    
def get_all_stats(data, measure):
    """
    DESCRIPCIÓN ESTADISTICA DE TODOS LOS DATOS EN measure
    """
    SERIES = list()
    for condition in data["conditon"].unique():
        CASES = data[(data["conditon"] == condition) & (data["length"] > 5000)]
        if len(CASES) == 0:
            continue
        SERIES.append(CASES[measure].apply(pd.Series).stack().describe().to_frame(name=condition))
    return pd.concat(SERIES, axis=1).round(5)

def distribution_NL(db, caso, histo=False):
    caso = str(caso)
    moment =['AppEn','SampEn','HFD','DFA','SD_ratio']
    m_label =['Ent_Aprox','Ent_Muestra','Higuchi','DFA','R= SD1/SD2']
    for idx in range(len(moment)):
            
        title = 'Distribución de ' + m_label[idx] +' en Casos de ' + caso
        xlab = 'Valor de '+ m_label[idx]
        plt.figure(figsize=(10,7), dpi= 100)
        plt.gca().set(title=title, ylabel='Coeficiente',xlabel=xlab)
        for i in range(len(db.index)):

            ms = db.iloc[i][moment[idx]]
            #x_min =np.min(ms,axis=0)
            #x_max =np.max(ms,axis=0)
                
            lab = db.iloc[i]['record']
            # Plot Settings
            kwargs = dict(hist_kws={'alpha':.6}, kde_kws={'linewidth':2})
            if histo == True:
                sns.distplot(ms, label= lab ,rug=False, hist=True,**kwargs)
                
                #X_axis limits
                #x_min = int(np.min(ms)) + 10
                #x_max = int(np.max(ms))+10
                #plt.xlim(x_min,x_max)
                #lims = plt.gca().get_xlim()
                #i = np.where( (ms > lims[0]) &  (ms < lims[1]) )[0]
                #plt.gca().set_xlim( ms[i].min(), ms[i].max() )
                plt.autoscale(enable=True, axis='y', tight=True)
            else:
                sns.distplot(ms, label= lab ,rug=False, hist=False,**kwargs)
                    
                #X_axis limits
                #x_min = int(np.min(ms)) + 10
                #x_max = int(np.max(ms))+10
                #plt.xlim(x_min,x_max)
                #lims = plt.gca().get_xlim()
                #i = np.where( (ms > lims[0]) &  (ms < lims[1]) )[0]
                #plt.gca().set_xlim( ms[i].min(), ms[i].max() )
                plt.autoscale(enable=True, axis='y', tight=True)
            
        #show()
        plt.autoscale()
        plt.legend()
    
def get_allNL_stats(data, measure):
    """
    DESCRIPCIÓN ESTADISTICA DE TODOS LOS DATOS EN measure
    """
    SERIES = list()
    for condition in data["conditon"].unique():
        CASES = data[(data["conditon"] == condition) & (data["length"] > 5000)]
        if len(CASES) == 0:
            continue
        SERIES.append(CASES[measure].apply(pd.Series).stack().describe().to_frame(name=condition))
    return pd.concat(SERIES, axis=1).round(5)

# %%
def RunAnalysis():
    #ks_test = stats.kstest()
    pass

# %%
