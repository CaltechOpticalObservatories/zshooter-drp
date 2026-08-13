import numpy as np
import os
from abc import ABC, abstractmethod
from contextlib import contextmanager
from tqdm.auto import tqdm as auto_tqdm

import pyreduce.extract as extract_module
from pyreduce.combine_frames import combine_calibrate
from pyreduce.trace import trace
from pyreduce.trace_model import save_traces, load_traces
from pyreduce.slit_curve import Curvature
from pyreduce.extract import extract_normalize, extract
from pyreduce.spectra import ExtractionParams, Spectra
from pyreduce.instruments.common import Instrument

@contextmanager
def _patched_extract_tqdm(disable: bool):
    if not disable:
        yield
        return

    old_tqdm = getattr(extract_module, "tqdm", None)
    old_trange = getattr(extract_module, "trange", None)

    def _silent_tqdm(*args, **kwargs):
        kwargs.setdefault("disable", True)
        return auto_tqdm(*args, **kwargs)

    extract_module.tqdm = _silent_tqdm
    if old_trange is not None:
        extract_module.trange = lambda *a, **k: _silent_tqdm(range(*a), **k)
    try:
        yield
    finally:
        if old_tqdm is not None:
            extract_module.tqdm = old_tqdm
        if old_trange is not None:
            extract_module.trange = old_trange

class Step(ABC):
    @staticmethod
    @abstractmethod
    def run(*args, **kwargs):
        pass

    @staticmethod
    def save(*args, **kwargs):
        pass

    @staticmethod
    def load(*args, **kwargs):
        pass


class MaskWrapper(Step):
    name = 'mask'

    @staticmethod
    def run(instrument: Instrument, channel: str) -> np.ndarray:
        maskfile = instrument.get_mask_filename(channel)
        return np.load(maskfile).astype(bool)

    @staticmethod
    def save(mask: np.ndarray, filename: str):
        np.save(filename, mask)

    @staticmethod
    def load(instrument, channel):
        return MaskWrapper.run(instrument, channel)


class TraceWrapper(Step):
    name = 'trace'

    @staticmethod
    def run(image, step_cfg, order_centers=None, **kwargs):
        mapping = {'split_sigma': 'sigma'}
        params = {mapping.get(k,k): v for k, v in step_cfg.items()}
        params.pop('bias_scaling') if 'bias_scaling' in params else None
        params.pop('norm_scaling') if 'norm_scaling' in params else None
        params['order_centers'] = order_centers
        if kwargs.get('print_params', True):
            print(f"Tracing parameters: {params}")

        return trace(image, **params)

    @staticmethod
    def save(traces, filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        save_traces(filename, traces, steps=[TraceWrapper.name])

    @staticmethod
    def load(filename):
        return load_traces(filename)


class CurvatureWrapper(Step):
    name = 'curvature'

    @staticmethod
    def run(image, traces, step_cfg, **kwargs):
        mapping = {'degree': 'fit_degree', 'curvature_cutoff': 'sigma_cutoff', 'dimensionality': 'mode'}
        params = {mapping.get(k,k): v for k, v in step_cfg.items()}
        params.pop('bias_scaling') if 'bias_scaling' in params else None
        params.pop('norm_scaling') if 'norm_scaling' in params else None
        params.pop('extraction_method') if 'extraction_method' in params else None
        params.pop('collapse_function') if 'collapse_function' in params else None
        if kwargs.get('print_params', True):
            print(f"Curvature parameters: {params}")

        curvmod = Curvature(traces=traces, **params)
        curvature = curvmod.execute(image)

        # Update traces in-place with curvature data
        fitted_coeffs = curvature["fitted_coeffs"]
        slitdeltas = curvature["slitdeltas"]
        for i, t in enumerate(traces):
            if fitted_coeffs is not None and i < fitted_coeffs.shape[0]:
                t.slit = fitted_coeffs[i]
            if slitdeltas is not None and i < slitdeltas.shape[0]:
                t.slitdelta = slitdeltas[i]
        return traces

class NormflatWrapper(Step):
    name = 'norm_flat'

    @staticmethod
    def run(image, header, traces, step_cfg, **kwargs):
        mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
                   'extraction_reject': 'reject_threshold'}
        params = {mapping.get(k,k): v for k, v in step_cfg.items()}
        params['reject_threshold'] = params.get('reject_threshold', 6)
        params.update({'gain': header["e_gain"], 'readnoise': header["e_readn"], 'dark': header["e_drk"]})
        params['scatter'] = kwargs.get('scatter', None)
        if kwargs.get('print_params', True):
            print(f"Normflat parameters: {params}")

        disable_tqdm = kwargs.get('disable_tqdm', True)
        with _patched_extract_tqdm(disable_tqdm):
            norm, _, blaze, slitfunc, column_range = extract_normalize(image, traces, **params)

        blaze = np.ma.filled(blaze, 0)
        norm = np.ma.filled(norm, 1)
        norm = np.nan_to_num(norm, nan=1)

        # Metadata for slitfunc
        n_traces = len(traces)
        slitfunc_meta = {
            "extraction_height": params["extraction_height"],
            "osample": params["osample"],
            "trace_range": (0, n_traces),
            "n_traces_selected": n_traces,
        }
        return norm, blaze, slitfunc, slitfunc_meta

    @staticmethod
    def save(norm, blaze, slitfunc, slitfunc_meta, filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        if filename.endswith('.npz'):
            np.savez(filename, norm=norm, blaze=blaze, slitfunc=np.array(slitfunc, dtype=object),
                        slitfunc_meta=slitfunc_meta)
        else:
            raise ValueError("Filename must end with .npz")

    @staticmethod
    def load(filename):
        if filename.endswith('.npz'):
            return np.load(filename, allow_pickle=True)
        else:
            raise ValueError("Filename must end with .npz")


class ScienceWrapper(Step):
    name = 'science'

    @staticmethod
    def run(images, traces, instrument, channel, bias, bhead, norm, step_cfg, **kwargs):
        """
        Preproc science images (combine_calibrate), run tracing, then run extraction.
        :param images: list of science images that belong to same target
        :param traces: traces to extract
        :param instrument: Instrument instance
        :param channel: Channel name
        :param bias: Bias image
        :param bhead: Bias header
        :param norm: Norm image
        :param step_cfg: Step configuration for science extraction
        """
        mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
                   'extraction_reject': 'reject_threshold', 'extraction_method':'extraction_type'}
        params = {mapping.get(k,k): v for k,v in step_cfg.items()}

        im, head = combine_calibrate(images, instrument=instrument, channel=channel, bias=bias, bhead=bhead, norm=norm,
                                     extraction_height=params['extraction_height'], bias_scaling=params.pop('bias_scaling'),
                                     norm_scaling=params.pop('norm_scaling'))
        params.update({'gain': head["e_gain"], 'readnoise': head["e_readn"], 'dark': head["e_drk"]})
        params['scatter'] = kwargs.get('scatter', None)
        if kwargs.get('print_params', True):
            print(f"Science extraction parameters: {params}")

        meta = ExtractionParams(
            osample=params.get("osample", 10),
            lambda_sf=params.get("lambda_sf", 1.0),
            lambda_sp=params.get("lambda_sp", 0.0),
            swath_width=params.get("swath_width"),
        )

        disable_tqdm = kwargs.get('disable_tqdm', True)
        with _patched_extract_tqdm(disable_tqdm):
            spec = extract(im, traces, **params)
        spec_obj = Spectra(header=head, data=spec, params=meta)
        return spec_obj

