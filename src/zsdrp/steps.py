import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml
from astropy.constants import c as speed_of_light
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from astropy.modeling.fitting import (
    FittingWithOutlierRemoval,
    LinearLSQFitter,
)
from astropy.modeling.models import Chebyshev1D, Spline1D
from astropy.stats import sigma_clip
from pyreduce.combine_frames import combine_bias, combine_calibrate
from pyreduce.clipnflip import clipnflip
from pyreduce.extract import extract, extract_normalize
from pyreduce.instruments.common import Instrument
from pyreduce.slit_curve import Curvature
from pyreduce.spectra import ExtractionParams, Spectra, Spectrum
from pyreduce.trace import trace
from pyreduce.trace_model import load_traces, save_traces
from pyreduce.wavelength_calibration import (
    WavelengthCalibration,
    WavelengthCalibrationInitialize,
)
from scipy.interpolate import make_interp_spline
from scipy.ndimage import median_filter
from scipy.optimize import curve_fit
from scipy import sparse
from scipy.signal import find_peaks
from scipy.special import erf

from zsdrp.utils import patched_extract_tqdm, detector_to_extraction, extraction_to_detector

logger = logging.getLogger(__name__)


class Step(ABC):
    @staticmethod
    @abstractmethod
    def run(*args, **kwargs):
        """ Main step logic goes here. This method should be overridden by subclasses. """

    @staticmethod
    def save(*args, **kwargs):
        pass

    @staticmethod
    def load(*args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self.run(*args, **kwargs)


class MaskWrapper(Step):
    name = 'mask'

    @staticmethod
    def run(filename: str | Path | None = None,
            *,
            instrument: Instrument | None = None,
            channel: str = '',
            default_shape: tuple[int, int] | None = None
            ) -> np.ndarray:
        """
        Loads and returns a mask from a .npz or .npy file. Returns a default mask of zeros if filename is None, or
        file does not exist or file format is unsupported.

        :param filename: Path to the mask file (.npz or .npy). If None, a default mask of zeros is returned.
        :param instrument: Instrument instance to determine the shape of the default mask if filename is None.
                           Calls instrument.detector_shape(channel) to get the shape.
        :param channel: Channel name to determine the shape of the default mask if filename is None.
        :param default_shape: Tuple specifying the shape of the default mask if filename is None and instrument/channel are not provided.
        :return: A numpy ndarray representing the mask.
        """
        mask = MaskWrapper.load(str(filename), channel) if filename else None
        if mask is None:
            if instrument is not None and channel is not None and hasattr(instrument, 'detector_shape'):
                mask = np.zeros(instrument.detector_shape(channel), dtype=bool)
            elif default_shape is not None:
                mask = np.zeros(default_shape, dtype=bool)
            else:
                raise ValueError("No valid mask source provided.")
        return mask

    @staticmethod
    def save(masks: dict[str, np.ndarray] | np.ndarray, filename: str):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        if isinstance(masks, np.ndarray):
            np.savez(filename, mask=masks)
        else:
            np.savez(filename, **masks)

    @staticmethod
    def load(filename: str, channel: str = '') -> np.ndarray | None:
        if not os.path.exists(filename):
            raise FileNotFoundError(f"File not found: {filename}")

        with np.load(filename, allow_pickle=True) as data:
            if '.npy' in filename:
                return data
            else:
                if channel != '' and channel in data:
                    logger.info(f"Loading mask from {filename}, at key '{channel}'")
                    return data[channel]
                elif 'mask' in data:
                    logger.info(f"Loading mask from {filename}, at key 'mask'")
                    return data['mask']
                else:
                    raise ValueError(f"Neither key 'mask' nor {channel} found in {filename}, "
                                     f"save the mask with the appropriate key.")


class BiasWrapper(Step):
    name = 'bias'

    @staticmethod
    def run(filenames: Sequence[str], *,
            instrument: Instrument,
            channel: str,
            **kwargs):
        """
        Run the bias step on the provided filenames using the specified instrument and channel.
        :param filenames: List of filenames to process.
        :param instrument: The instrument to use for the bias step.
        :param channel: The channel to use for the bias step.
        :return: The result of the bias step.
        """
        if filenames is None or len(filenames) == 0:
            logger.warning(f"No bias files provided for channel {channel}, check your input files. "
                           f"Skipping bias combination for this channel.")
            return None, None
        return combine_bias(files=list(filenames), instrument=instrument, channel=channel)


class FlatWrapper(Step):
    name = 'flat'

    @staticmethod
    def run(filenames: Sequence[str], *,
            instrument: Instrument,
            channel: str,
            bias: np.ndarray | None = None,
            bhead: dict | None = None,
            step_cfg: dict,
            **kwargs):
        """
        Run the flat step on the provided filenames using the specified instrument and channel.
        :param filenames: List of filenames to process.
        :param instrument: The instrument to use for the flat step.
        :param channel: The channel to use for the flat step.
        :param bias: Optional bias for the flat step.
        :param bhead: Optional bias for the flat step.
        :param step_cfg: Dictionary containing the settings for the flat step.
        :return: The result of the flat step.
        """
        if filenames is None or len(filenames) == 0:
            logger.warning(f"No flat files found for channel {channel}, check your input files. "
                           f"Skipping flat combination for this channel.")
            return None, None
        else:
            return combine_calibrate(files=list(filenames), instrument=instrument, channel=channel, bias=bias,
                                     bhead=bhead, **step_cfg)


class TraceWrapper(Step):
    name = 'trace'

    @staticmethod
    def run(image: np.ndarray,
            *,
            step_cfg: dict,
            order_centers: dict[int, int | float] | None = None,
            **kwargs):
        """
        Run the tracing step on the provided image using the specified configuration.
        :param image: The input image to trace. Should be a flat field image (e.g., from a flat lamp).
        :param step_cfg: Dictionary containing the settings for the tracing step.
        :param order_centers: Optional dictionary mapping order numbers to their approximate center positions in pixels.
                                If provided, these will be used to guide the tracing.
        :keyword print_params: If True, prints the supplied parameters used for tracing. Default is True.
        :return: A list of Trace objects representing the traced orders in the image.
        """
        mapping = {'split_sigma': 'sigma'}
        params = {mapping.get(k, k): v for k, v in step_cfg.items()}
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
        return load_traces(filename)[0]


class CurvatureWrapper(Step):
    name = 'curvature'

    @staticmethod
    def run(image: np.ndarray,
            traces: list,
            *,
            step_cfg: dict,
            **kwargs):
        """
        Run the curvature fitting step on the provided image and traces using the specified configuration.
        :param image: The input image to fit curvature. Should be an arc lamp image.
        :param traces: List of Trace objects representing the traced orders in the image.
        :param step_cfg: Dictionary containing the settings for the curvature fitting step.
        :keyword print_params: If True, prints the supplied parameters used for curvature fitting. Default is True.
        :return: The updated list of Trace objects with curvature information added.
        """
        mapping = {'degree': 'fit_degree', 'curvature_cutoff': 'sigma_cutoff', 'dimensionality': 'mode'}
        params = {mapping.get(k, k): v for k, v in step_cfg.items()}
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
    def run(image: np.ndarray,
            header: dict,
            traces: list,
            *,
            step_cfg: dict,
            **kwargs):
        """
        Run the flat norm and blaze calculation on the provided image and traces using the specified configuration.
        :param image: The input flat field image to normalize. Should be a flat lamp image.
        :param header: The header associated with the image, containing gain, readnoise, and dark information.
        :param traces: List of Trace objects representing the traced orders in the image.
        :param step_cfg: Dictionary containing the settings for the norm flat calculation step.
        :keyword scatter: Optional scatter parameter to be passed to the extraction function.
        :keyword print_params: If True, prints the supplied parameters used for norm flat calculation.
        :return: A tuple containing the normalized flat (norm), blaze function (blaze), slit function (slitfunc),
        and metadata for the slit function (slitfunc_meta).
        """
        mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
                   'extraction_reject': 'reject_threshold'}
        params = {mapping.get(k, k): v for k, v in step_cfg.items()}
        params['reject_threshold'] = params.get('reject_threshold', 6)
        params.update({'gain': header["e_gain"], 'readnoise': header["e_readn"], 'dark': header["e_drk"]})
        params['scatter'] = kwargs.get('scatter', None)
        if kwargs.get('print_params', True):
            print(f"Normflat parameters: {params}")

        disable_tqdm = kwargs.get('disable_tqdm', True)
        with patched_extract_tqdm(disable_tqdm):
            norm, _, blaze, slitfunc, _ = extract_normalize(image, traces, **params)

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
        np.savez(filename, norm=norm, blaze=blaze, slitfunc=np.array(slitfunc, dtype=object),
                 slitfunc_meta=slitfunc_meta)

    @staticmethod
    def load(filename):
        if not os.path.exists(filename):
            raise FileNotFoundError(f"File not found: {filename}")
        if filename.endswith('.npz'):
            with np.load(filename, allow_pickle=True) as data:
                norm = data['norm']
                blaze = data['blaze']
                slitfunc = data['slitfunc'].tolist()  # Convert back to list
                slitfunc_meta = data['slitfunc_meta'].item()  # Convert back to dict
                return norm, blaze, slitfunc, slitfunc_meta
        else:
            raise ValueError("Filename must end with .npz")


class WavecalWrapper(Step):
    name = 'wavecal'

    @staticmethod
    def run(image: np.ndarray,
            header: dict,
            traces: list,
            *,
            instrument: Instrument,
            channel: str,
            master_step_cfg: dict,
            init_step_cfg: dict,
            step_cfg: dict,
            **kwargs):
        """
        Run the wavelength calibration step on the provided image and traces using the specified configuration.
        :param image: Wavecal image (arc lamp) to extract from.
        :param header: Header associated with the image, containing gain, readnoise, and dark information.
        :param traces: List of Trace objects representing the traced orders in the image.
        :param instrument: Instrument instance to determine the wavelength range and atlas search directories.
        :param channel: Channel name to determine the wavelength range.
        :param master_step_cfg: Dictionary containing the settings for the wavecal_master extraction step.
        :param init_step_cfg: Dictionary containing the settings for the wavecal_init step.
        :param step_cfg: Dictionary containing the settings for the wavecal final step.
        :keyword scatter: Optional scatter parameter to be passed to the extraction function.
        :keyword print_params: If True, prints the supplied parameters used for wavecal extraction.
        :keyword disable_tqdm: If True, disables the progress bar for the extraction function.

        :return: A tuple containing the wavelength image (array of shape (n_trace, n_cols)), wavelength solution,
                 linelist of identified lines, and quality metrics.
        """
        # Wavecal_master substep
        mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
                   'extraction_reject': 'reject_threshold', 'extraction_method': 'extraction_type'}
        params = {mapping.get(k, k): v for k, v in master_step_cfg.items()}
        params.update({'gain': header["e_gain"], 'readnoise': header["e_readn"], 'dark': header["e_drk"]})
        params['scatter'] = kwargs.get('scatter', None)
        if kwargs.get('print_params', True):
            print(f"Wavecal Master extraction parameters: {params}")

        # reset traces wave to None before extraction to avoid using old wavecal data
        for t in traces:
            t.wave = None
        disable_tqdm = kwargs.get('disable_tqdm', True)
        with patched_extract_tqdm(disable_tqdm):
            spectra = extract(image, traces, **params)
        wavecal_spec = np.array([s.spec for s in spectra])

        # Wavecal_init substep
        init_step_cfg['atlas_name'] = init_step_cfg.pop('atlas')
        init_step_cfg['wave_delta'] = init_step_cfg.get('wave_delta', 20)
        if kwargs.get('print_params', True):
            print(f"Wavecal Init parameters: {init_step_cfg}")
        wave_range = instrument.get_wavelength_range(header, channel)
        if wave_range is None:
            raise ValueError(f"Wavelength range not defined for instrument {instrument.name} and channel {channel}")
        module = WavelengthCalibrationInitialize(atlas_search_dirs=[instrument._inst_dir], **init_step_cfg)
        module._init_plot_count = kwargs.get('init_plot_count', 5)
        linelist = module.execute(wavecal_spec, wave_range)

        # wavecal final substep
        step_cfg['atlas_name'] = step_cfg.pop('atlas')
        if kwargs.get('print_params', True):
            print(f"Wavecal Final parameters: {step_cfg}")
        module = WavelengthCalibration(atlas_search_dirs=[instrument._inst_dir], **step_cfg)
        wlen, wave, linelist = module.execute(wavecal_spec, linelist)
        metrics = module.quality_metrics(wave, linelist)
        print(f"Wavecal quality : {metrics["rms_mps"]} m/s")

        obase = linelist.obase
        if obase is not None:
            already_have_m = any(t.m is not None for t in traces)
            if already_have_m:
                logger.debug("Traces already have m values, skipping obase")
            else:
                for idx_in_group, t in enumerate(traces):
                    t.m = obase + idx_in_group
                logger.info("Updated trace order numbers with obase=%d", obase)
        return wlen, wave, linelist, metrics

    @staticmethod
    def save(wave_img, wavesol, filename: str):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        # Save the wavelength calibration data to a .npz file
        np.savez(filename, wave_img=wave_img, wavesol=wavesol)

    @staticmethod
    def load(filename: str):
        if not os.path.exists(filename):
            raise FileNotFoundError(f"File not found: {filename}")
        if filename.endswith('.npz'):
            with np.load(filename, allow_pickle=True) as data:
                wave_img = data['wave_img']
                wavesol = data['wavesol']
                return wave_img, wavesol
        else:
            raise ValueError(f"Unsupported file format, only .npz is supported: {filename}")


def simple_wavesol(image: np.ndarray,
                   header: fits.Header,
                   traces: list,
                   *,
                   lamp_files: Sequence[str] = ("ThAr_lines.dat", "Ne_IR_MOSFIRE_lines.dat", "Ar_IR_MOSFIRE_lines.dat"),
                   min_snr: float = 30.0,
                   blend_pix: float = 12.0,
                   blend_ratio: float = 0.01,
                   halfwin: int = 7,
                   min_lines: int = 10,
                   min_lines_order: int = 8,
                   trace_list=None,
                   lamp_lines=None):
    """
    Wavelength solution from the ScopeSim analytical trace list that generated the frames, corrected with the arc
    lines exactly as in echelle_reduction.py (ChannelGeometry, arc_check, apply_wavelength_correction).

    Every pixel of an order's bounding box gets a wavelength and slit position xi from the configured SpectralTrace
    through the detector WCS (key 'D'). The arc spectrum of an order is the mean over slit pixels with |xi| < 4 arcsec
    (pixels shared by two orders excluded), at the wavelength of the row closest to xi = 0. Lines are fitted with the
    slit profile (top-hat convolved with a Gaussian) over +-`halfwin` pixels and matched to the lamp line list the
    arcs were simulated from; lines with another list line of more than `blend_ratio` of their amplitude within
    `blend_pix` pixels, or with SNR below `min_snr`, are rejected. dpix = (measured - list) / dispersion. A
    channel-wide a + b x/nx is fitted first; orders with at least `min_lines_order` lines then get their own linear
    term in x, the others a constant, and the corrected wavelength is model - dpix * dispersion. With fewer than
    `min_lines` lines the model is returned uncorrected.
    :param image: Combined arc image (bias subtracted).
    :param header: Header of the combined arc, carrying the detector WCS, image plane ID, irdb package path, gain and
                   read noise.
    :param traces: pyreduce Trace objects; the solution is evaluated along their centres, one row per valid trace.
    :param lamp_files: Lamp line tables in the irdb package lamp_lines/ directory that the arc source was built from.
    :return: Wavelength image in Angstrom of shape (n_trace, n_cols), and a Table of the arc lines measured on the
             uncorrected model (order, line, dlam, dpix, dv, snr, centre_err_pix, width_pix, x, y).
    """
    from scopesim.effects import EchelleSpectralTraceList

    inst_dir = Path(header['SIM CONFIG SIM file local_packages_path']) / header['INSTRUME']
    if trace_list is None:
        with open(inst_dir / 'ZShooter_SPEC.yaml') as f:
            effect = next(e for e in yaml.safe_load(f)['effects'] if e['name'] == 'trace_list_analytical')
        trace_list = EchelleSpectralTraceList(**{**effect['kwargs'], 'filename': str(inst_dir / effect['kwargs']['filename'])})
    spectral_traces = [st for st in trace_list.spectral_traces.values() if st.meta['image_plane_id'] == int(header['ID'])]

    # lamp line list, amplitudes normalised per file as when the arc source was built
    if lamp_lines is None:
        tables = [Table.read(inst_dir / 'lamp_lines' / name, delimiter='|', format='ascii', header_start=0) for name in lamp_files]
        line_waves = np.concatenate([np.asarray(t['wave'], dtype=float) for t in tables])
        line_amps = np.concatenate([np.asarray(t['amplitude'], dtype=float) / np.max(t['amplitude']) for t in tables])
    else:
        line_waves, line_amps = lamp_lines['wave'], lamp_lines['amplitude']
    line_amps, line_waves = line_amps[np.argsort(line_waves)], np.sort(line_waves)

    # per-pixel wavelength [A] and slit position [arcsec] in each order's bounding box
    wcs = WCS(header, key='D')
    ny, nx = image.shape
    orders = []
    for st in spectral_traces:
        xpix, ypix = detector_to_extraction(*wcs.all_world2pix(*st.footprint(), 0), header)
        x0, x1 = int(np.clip(np.floor(xpix.min()) - 2, 0, nx)), int(np.clip(np.ceil(xpix.max()) + 3, 0, nx))
        y0, y1 = int(np.clip(np.floor(ypix.min()) - 2, 0, ny)), int(np.clip(np.ceil(ypix.max()) + 3, 0, ny))
        if x1 - x0 < 20 or y1 - y0 < 10:
            continue
        xraw, yraw = extraction_to_detector(*np.meshgrid(np.arange(x0, x1), np.arange(y0, y1)), header)
        xmm, ymm = wcs.all_pix2world(xraw, yraw, 0)
        lam = st.xy2lam(xmm, ymm) * 1e4
        xi = st.xy2xi(xmm, ymm)
        inside = (np.abs(xi) <= np.abs(st.table['s']).max()) & (lam >= st.wave_min * 1e4) & (lam <= st.wave_max * 1e4)
        orders.append(dict(trace=st, x0=x0, y0=y0, slices=(slice(y0, y1), slice(x0, x1)), lam=lam, xi=xi, inside=inside,
                           dlam=np.abs(np.gradient(lam, axis=1))))
    claims = np.zeros(image.shape, dtype=np.int16)
    for o in orders:
        claims[o['slices']] += o['inside']
    overlap = claims > 1

    # arc_check: fit line centres per order and compare with the line list through the model wavelengths
    gain, readnoise = header['e_gain'], header['e_readn']
    rows = []
    for o in orders:
        sub = image[o['slices']]
        good = o['inside'] & ~overlap[o['slices']] & (np.abs(o['xi']) < 4.0)
        npix = good.sum(axis=0)
        ok = npix > 20
        if ok.sum() < 100:
            continue
        spec = np.where(ok, (sub * good).sum(axis=0) / np.maximum(npix, 1) * np.median(npix[ok]), 0.0)
        noise = np.sqrt(np.maximum(spec, 0) * gain + np.median(npix[ok]) * readnoise ** 2) / gain
        centre_row = np.argmin(np.abs(o['xi']), axis=0)
        cols = np.arange(sub.shape[1])
        lam_col = o['lam'][centre_row, cols]
        dlam_col = o['dlam'][centre_row, cols]
        peaks, _ = find_peaks(spec, prominence=max(10 * np.median(spec[ok]), 50.0), distance=6)
        for p in peaks[(peaks > halfwin + 2) & (peaks < spec.size - halfwin - 3)]:
            win = np.arange(p - halfwin, p + halfwin + 1)
            background = 0.5 * (spec[p - halfwin - 2] + spec[p + halfwin + 2])
            if header['INSTRUME'] == 'XSHOOTER':
                slit_width = float(str(header['SLIT']).removesuffix('JH'))
                width_pix = abs(o['trace'].slit_dispersion(lam_col[p] / 1e4)) * 1e4 * slit_width / dlam_col[p]
                optical_sigma = lam_col[p] / o['trace'].meta['optical_resolving_power'] / 2.35482 / dlam_col[p]
                p0 = [spec[p] - background, p, width_pix, optical_sigma, background]
                bounds = ([0, p - 2.5, width_pix * .5, optical_sigma * .5, -np.inf], [np.inf, p + 2.5, width_pix * 1.5, max(optical_sigma * 2, 1), np.inf])
            else:
                p0 = [spec[p] - background, p, 4.4, 0.6, background]
                bounds = ([0, p - 2.5, 2.5, 0.2, -np.inf], [np.inf, p + 2.5, 7.0, 2.5, np.inf])
            try:
                popt, pcov = curve_fit(slit_line_profile, win, spec[win], p0=p0, sigma=noise[win], bounds=bounds, maxfev=4000)
            except (RuntimeError, ValueError):
                continue
            amplitude, centre, width = popt[0], popt[1], popt[2]
            snr = amplitude * width / np.sqrt((noise[win] ** 2).sum())
            if snr < min_snr or not np.isfinite(pcov[1, 1]):
                continue
            lam_meas = np.interp(centre, cols, lam_col)
            k = np.searchsorted(line_waves, lam_meas)
            candidates = slice(max(k - 1, 0), k + 1)
            line_idx = candidates.start + np.argmin(np.abs(line_waves[candidates] - lam_meas))
            line = line_waves[line_idx]
            if abs(lam_meas - line) > 3 * dlam_col[p]:
                continue
            near = (np.abs(line_waves - line) < blend_pix * dlam_col[p]) & (np.arange(line_waves.size) != line_idx)
            if (line_amps[near] > blend_ratio * line_amps[line_idx]).any():
                continue
            dpix = (lam_meas - line) / dlam_col[p]
            rows.append((o['trace'].trace_id, line, lam_meas - line, dpix, (lam_meas - line) / line * speed_of_light.to_value("m/s"),
                         snr, np.sqrt(pcov[1, 1]), width, o['x0'] + centre, o['y0'] + centre_row[p]))
    names = ["order", "line", "dlam", "dpix", "dv", "snr", "centre_err_pix", "width_pix", "x", "y"]
    arcs = Table(rows=rows, names=names) if rows else Table(names=names, dtype=[str] + [float] * 9)

    # apply_wavelength_correction: channel-wide a + b x/nx, then a per-order linear term or constant
    corrections = {}
    if len(arcs) >= min_lines:
        xn = np.asarray(arcs["x"], dtype=float) / nx
        d = np.asarray(arcs["dpix"], dtype=float)
        w = 1 / np.maximum(np.asarray(arcs["centre_err_pix"], dtype=float), 0.01)
        design = np.vstack([np.ones_like(xn), xn]).T
        keep = np.ones(d.size, dtype=bool)
        for _ in range(3):
            coef, *_ = np.linalg.lstsq(design[keep] * w[keep, None], d[keep] * w[keep], rcond=None)
            resid = d - design @ coef
            keep = np.abs(resid) < 3 * max(np.std(resid[keep]), 0.02)
        order_names = np.asarray(arcs["order"]).astype(str)
        for o in orders:
            sel = keep & (order_names == o['trace'].trace_id)
            if sel.sum() >= min_lines_order:
                co, *_ = np.linalg.lstsq(np.vstack([np.ones(sel.sum()), xn[sel] - 0.5]).T * w[sel, None], resid[sel] * w[sel], rcond=None)
            else:
                co = [np.median(resid[sel]) if sel.sum() >= 3 else 0.0, 0.0]
            corrections[o['trace'].trace_id] = (coef[0] + co[0] - 0.5 * co[1], coef[1] + co[1])  # dpix = a + b x/nx
        print(f"simple_wavesol: {keep.sum()}/{len(arcs)} lines, channel {coef[0]:+.3f} {coef[1]:+.3f} x/nx px, rms {np.std(resid[keep]):.3f} px")
    else:
        print(f"simple_wavesol: only {len(arcs)} arc lines, returning the uncorrected trace-list wavelengths")

    # corrected wavelengths along the pyreduce trace centres
    traces = [t for t in traces if not t.invalid]  # pyreduce extraction returns spectra for valid traces only
    x = np.arange(nx)
    wave_img = np.zeros((len(traces), nx))
    for i, t in enumerate(traces):
        xraw, yraw = extraction_to_detector(x, t.y_at_x(x), header)
        xmm, ymm = wcs.all_pix2world(xraw, yraw, 0)
        cols = slice(*t.column_range)
        st = min(spectral_traces, key=lambda s: np.median(np.abs(s.xy2xi(xmm[cols], ymm[cols]))))
        t.m = int(st.trace_id.rsplit('_', 1)[1])
        wave_img[i] = st.xy2lam(xmm, ymm) * 1e4
        a, b = corrections.get(st.trace_id, (0.0, 0.0))
        wave_img[i] -= (a + b * x / nx) * np.abs(np.gradient(wave_img[i]))
    order_numbers = [t.m for t in traces]
    if len(set(order_numbers)) != len(order_numbers):
        raise ValueError(f"Multiple measured traces assigned to the same physical order: {order_numbers}")
    return wave_img, arcs

def slit_line_profile(x, amplitude, centre, width, sigma, background):
    """Slit image of an unresolved lamp line: a top-hat of `width` pixels convolved with a Gaussian of `sigma`."""
    upper = (x - centre + width / 2) / (np.sqrt(2) * sigma)
    lower = (x - centre - width / 2) / (np.sqrt(2) * sigma)
    return 0.5 * amplitude * (erf(upper) - erf(lower)) + background


def load_prepared_science(filename, instrument, channel, mask=None):
    """Read an explicitly combined sky-subtracted frame and its pixel variance."""
    image, header = instrument.load_fits(filename, channel, mask=mask)
    if header['BUNIT'].lower() != 'electron' or header['GAIN'] != 1:
        raise ValueError('Prepared science must load as accumulated electrons with GAIN=1')
    if not header['SUBTRACTED']:
        raise ValueError('Prepared science must already include bias/background subtraction and its variance')
    with fits.open(filename) as hdul:
        raw_header = hdul[0].header.copy()
        raw_header.update(hdul[1].header)
        scale = 1.
        if raw_header['BUNIT'].lower() == 'adu':
            scale = raw_header['GAIN'] * (raw_header['NDIT'] if raw_header['COMBINE'] == 'average' else 1)
        variance = clipnflip(hdul['VARIANCE'].data, header) * scale**2
    if variance.shape != image.shape:
        raise ValueError('Science and variance images have different shapes')
    valid = ~np.ma.getmaskarray(image)
    if np.any(~np.isfinite(variance[valid])) or np.any(variance[valid] <= 0):
        raise ValueError('Unmasked science pixels require finite positive input variance')
    header['COVCOND'] = ('calibrations fixed', 'Pixel noise propagated conditional on measured calibration products')
    return image, variance, header


class ScienceWrapper(Step):
    name = 'science'

    @staticmethod
    def run(images: list[str],
            traces: list,
            *,
            instrument: Instrument,
            channel: str,
            bias: np.ndarray | None = None,
            bhead: dict | None = None,
            norm: np.ndarray | None = None,
            mask: np.ndarray | None = None,
            step_cfg: dict,
            **kwargs) -> dict[str, Spectra]:
        """
        Preprocess science images (combine_calibrate), run tracing, then run extraction.
        :param images: list of science images
        :param traces: traces to extract
        :param instrument: Instrument instance
        :param channel: Channel name
        :param bias: Bias image
        :param bhead: Bias header
        :param norm: Norm image
        :param mask: Mask image
        :param step_cfg: Step configuration for science extraction
        :keyword scatter: Optional scatter parameter to be passed to the extraction function.
        :keyword print_params: If True, prints the supplied parameters used for science extraction.
        :return: dict of Spectra objects containing the extracted spectra and associated metadata, keyed by object name.
        """
        mapping = {'smooth_slitfunction': 'lambda_sf', 'smooth_spectrum': 'lambda_sp', 'oversampling': 'osample',
                   'extraction_reject': 'reject_threshold', 'extraction_method': 'extraction_type'}
        params = {mapping.get(k, k): v for k, v in step_cfg.items()}
        bias_scaling = params.pop('bias_scaling')
        norm_scaling = params.pop('norm_scaling')
        params['scatter'] = kwargs.get('scatter', None)

        groups = {}
        for img in images:
            objname = fits.getheader(img, ext=0)['OBJECT']
            groups[objname] = groups.get(objname, []) + [img]

        group_spectra = {}
        for objname, imgs in groups.items():
            logger.info(f"Processing {objname} for science extraction with {len(imgs)} images.")

            with fits.open(imgs[0]) as hdul:
                supplied_variance = kwargs.get('require_variance', False) or 'VARIANCE' in hdul
            variance = None
            if supplied_variance:
                if len(imgs) != 1:
                    raise ValueError('Combine source and sky exposures with explicit coefficients before extraction; supply one SCI+VARIANCE file per object and arm')
                im, variance, head = load_prepared_science(imgs[0], instrument, channel, mask=mask)
                if norm is not None and norm_scaling == 'divide':
                    im = im / norm
                    variance = variance / norm**2
                elif norm is not None and norm_scaling != 'none':
                    raise ValueError(f'Unsupported flat normalization {norm_scaling}')
            elif fits.getheader(imgs[0], ext=0).get("SUBTRACTED", False):
                logger.info("This is a subtracted image from AB pair, combining without bias.")
                im, head = combine_calibrate(imgs, instrument=instrument, channel=channel, bias=None, bhead=bhead,
                                             norm=norm, mask=mask, extraction_height=params['extraction_height'],
                                             bias_scaling=bias_scaling, norm_scaling=norm_scaling)
            else:
                im, head = combine_calibrate(imgs, instrument=instrument, channel=channel, bias=bias, bhead=bhead,
                                             norm=norm, mask=mask, extraction_height=params['extraction_height'],
                                             bias_scaling=bias_scaling, norm_scaling=norm_scaling)

            params.update({'gain': head["e_gain"], 'readnoise': head["e_readn"], 'dark': head["e_drk"]})
            if kwargs.get('print_params', True):
                print(f"Science extraction parameters: {params}")
            meta = ExtractionParams(
                osample=params.get("osample", 10),
                lambda_sf=params.get("lambda_sf", 1.0),
                lambda_sp=params.get("lambda_sp", 0.0),
                swath_width=params.get("swath_width"),
            )

            disable_tqdm = kwargs.get('disable_tqdm', True)
            with patched_extract_tqdm(disable_tqdm):
                spectrum = extract(im, traces, variance=variance, **params)
            group_spectra[objname] = Spectra(header=head, data=spectrum, params=meta)

        return group_spectra


class BlazeNormalization(Step):
    name = 'blaze'

    @staticmethod
    def run(group_spectra: dict[str, Spectra],
            wave: np.ndarray,
            blaze: np.ndarray,
            free_spectral_range: dict[int, np.ndarray],
            **kwargs) -> dict[str, Spectra]:
        """
        Run the continuum normalization step on the provided spectra using traces and blaze function.
        :param group_spectra: dict of Spectra objects, keyed by object name.
        :param wave: Wavelength solution array of shape (n_trace, n_cols)
        :param blaze: Blaze function array corresponding to the spectra of shape (n_trace, n_cols).
        :param free_spectral_range: Physical order number -> lower/upper FSR wavelengths in Angstrom.
        :keyword print_params: If True, prints the supplied parameters used for continuum normalization.
        :return: A new Spectra object containing the continuum-normalized spectra and associated metadata.
        """
        for objname, spectra in group_spectra.items():
            data = []
            for i, sp in enumerate(spectra.data):
                assert sp.spec.shape == wave[i].shape == blaze[i].shape
                valid = np.isfinite(sp.spec) & np.isfinite(sp.sig) & np.isfinite(blaze[i]) & (blaze[i] > 0)
                validspec = sp.spec[valid]
                validsig = sp.sig[valid]
                validblaze = blaze[i][valid]
                validwave = wave[i][valid]
                lower, upper = free_spectral_range[sp.m]
                sel = (validwave > lower) & (validwave < upper)
                spec = (validspec / validblaze)[sel]
                sig = (validsig / validblaze)[sel]
                covariance = None
                if sp.covariance is not None:
                    index = np.flatnonzero(valid)[sel]
                    scale = 1 / blaze[i, index]
                    covariance = sp.covariance[index][:, index].multiply(scale[:, None]).multiply(scale[None, :]).tocsr()
                    sig = np.sqrt(covariance.diagonal())
                newsp = Spectrum(m=sp.m, spec=spec, sig=sig, wave=validwave[sel], cont=validblaze[sel], covariance=covariance)
                data.append(newsp)
            new_spectra = Spectra(header=spectra.header, data=data, params=spectra.params)
            group_spectra[objname] = splice(new_spectra, simple=kwargs.get('simple', True))
        return group_spectra


class SensitivityFunction(Step):
    name = 'sensitivity'

    @staticmethod
    def run(standard_spectra: Spectra,
            reference_spectrum: Spectrum,
            plot: bool = False):
        """
        Compute the sensitivity function by comparing the extracted standard star spectra to the reference spectra.
        """
        reference = make_interp_spline(reference_spectrum.wave, reference_spectrum.spec)
        sens_funcs = []

        exptime = standard_spectra.header.get('EXPTIME', 1.0)
        for standard_spectrum in standard_spectra.data:
            valid = np.isfinite(standard_spectrum.spec) & (standard_spectrum.spec > 0)
            stdwave = standard_spectrum.wave[valid]
            stdspec = standard_spectrum.spec[valid] / float(exptime)
            y = np.log10(reference(stdwave) / stdspec)
            y_smooth = median_filter(y, size=51, mode='nearest')
            fitter = FittingWithOutlierRemoval(LinearLSQFitter(), sigma_clip, niter=5, sigma=3)
            sens, clipped = fitter(Chebyshev1D(degree=6), stdwave, y_smooth)
            sens_funcs.append(sens)
            if plot:
                plt.figure()
                plt.plot(stdwave, 10 ** y, alpha=0.2, label='ratio')
                plt.plot(stdwave, 10 ** y_smooth, lw=1, label='ratio smoothed')
                plt.plot(stdwave[clipped], 10 ** y_smooth[clipped], '.', ms=1, label='clipped')
                plt.plot(stdwave, 10 ** sens(stdwave), label='sensitivity fit')
                plt.xlabel('Wavelength (Angstrom)')
                plt.ylabel('Reference flux / Observed counts')
                plt.title('Sensitivity Function')
                plt.legend()
                plt.show()

        return sens_funcs


def splice(spectra: Spectra, simple=True, edge_frac=0.1, nsigma=3.0, **kwargs):
    """
    Splice wavelength-adjacent pieces (the orders of one channel, or whole channels) into a single 1D spectrum.
    Each pair of neighbours is cut at one junction wavelength, so no wavelength appears twice. Inside an overlap the
    junction maximizes the kept inverse variance per unit wavelength, 1/(sig^2 dlambda), which for channels puts it
    where the two S/N curves cross through the dichroic. Across a gap the junction is the gap midpoint.
    :param spectra: Spectra whose data are the pieces to splice, all in the same flux units.
    :param simple: If True, only cut at the junctions. If False, also rescale the pieces so that neighbours agree at
        each overlapping junction, anchored to the piece with the highest median S/N.
    :param edge_frac: Half-width of the window around a junction used to measure each piece's flux level, as a
        fraction of that piece's wavelength span.
    :param nsigma: A junction ratio is applied only if the two flux levels differ by more than nsigma times their
        combined uncertainty, so pieces that already agree are not random-walked by noisy factors.
        No ratio is measured across a gap; there the flux calibration alone sets the relative level.
    :return: Spectra with one spliced Spectrum.
    """
    pieces = sorted(spectra.data, key=lambda sp: np.median(sp.wave))
    has_covariance = [sp.covariance is not None for sp in pieces]
    if any(has_covariance) and not all(has_covariance):
        raise ValueError('Cannot splice spectra with missing covariance alongside covariance-aware spectra')
    if any(has_covariance) and not simple:
        raise ValueError('Covariance-aware stitching uses the standard response without fitting extra overlap scale factors; use simple=True')
    good = [np.isfinite(sp.spec) & np.isfinite(sp.sig) for sp in pieces]  # PyReduce marks masked pixels as NaN
    wave = [sp.wave[g] for sp, g in zip(pieces, good)]
    spec = [sp.spec[g] for sp, g in zip(pieces, good)]
    sig = [sp.sig[g] for sp, g in zip(pieces, good)]
    cont = [sp.cont[g] for sp, g in zip(pieces, good)]

    junctions, ratios = [], []
    for wa, sa, ea, wb, sb, eb in zip(wave[:-1], spec[:-1], sig[:-1], wave[1:], spec[1:], sig[1:]):
        lo, hi = wb.min(), wa.max()
        if hi <= lo:
            junctions.append(0.5 * (lo + hi))
            ratios.append(1.0)
            continue
        ov = (wa >= lo) & (wa <= hi)
        ivar_b = np.interp(wa[ov], wb, 1 / (eb ** 2 * np.gradient(wb)))  # per unit wavelength
        gain = np.cumsum(1 / ea[ov] ** 2 - ivar_b * np.gradient(wa)[ov])
        lam = wa[ov][np.argmax(gain)]
        junctions.append(lam)
        if simple:
            ratios.append(1.0)
            continue
        near_a = np.abs(wa - lam) < edge_frac * np.ptp(wa)
        near_b = np.abs(wb - lam) < edge_frac * np.ptp(wb)
        fa, err_a = flux_at(lam, wa[near_a], sa[near_a])
        fb, err_b = flux_at(lam, wb[near_b], sb[near_b])
        detected = fa > 0 and fb > 0 and abs(fa - fb) > nsigma * np.hypot(err_a, err_b)
        ratios.append(fa / fb if detected else 1.0)

    # chain the junction ratios outward from the best piece so errors don't accumulate from the noisy ends
    anchor = np.argmax([np.median(s / e) for s, e in zip(spec, sig)])
    scale = np.ones(len(pieces))
    for i in range(anchor + 1, len(pieces)):
        scale[i] = scale[i - 1] * ratios[i - 1]
    for i in range(anchor - 1, -1, -1):
        scale[i] = scale[i + 1] / ratios[i]
    if not simple:
        logger.info(f"Splice scale factors (anchor piece {anchor}): {np.round(scale, 3)}")

    edges = [-np.inf] + junctions + [np.inf]
    keep = [(w > edges[i]) & (w <= edges[i + 1]) for i, w in enumerate(wave)]
    covariance = None
    if all(has_covariance):
        blocks = []
        for sp, valid, selected, factor in zip(pieces, good, keep, scale):
            index = np.flatnonzero(valid)[selected]
            blocks.append(sp.covariance[index][:, index] * factor**2)
        covariance = sparse.block_diag(blocks, format='csr')
    new_spectrum = Spectrum(m=None, wave=np.concatenate([w[k] for w, k in zip(wave, keep)]),
                            spec=np.concatenate([s[k] * f for s, k, f in zip(spec, keep, scale)]),
                            sig=np.concatenate([e[k] * f for e, k, f in zip(sig, keep, scale)]),
                            cont=np.concatenate([c[k] * f for c, k, f in zip(cont, keep, scale)]), covariance=covariance)
    return Spectra(header=spectra.header, data=[new_spectrum], params=spectra.params)


def flux_at(lam, wave, spec, nbin=10):
    """
    Flux at lam and its 1-sigma error, from a line through the medians of nbin consecutive-pixel bins.
    The medians reject narrow emission/absorption lines, and the error comes from their actual scatter about the line.
    """
    x = np.array([np.median(w) for w in np.array_split(wave, nbin)]) - lam
    y = np.array([np.median(s) for s in np.array_split(spec, nbin)])
    p, cov = np.polyfit(x, y, 1, cov=True)
    return p[1], np.sqrt(cov[1, 1])