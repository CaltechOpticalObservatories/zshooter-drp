import numpy as np
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Sequence
from pathlib import Path
import matplotlib.pyplot as plt

from astropy.io import fits
from astropy.modeling.fitting import FittingWithOutlierRemoval, LinearLSQFitter, SplineExactKnotsFitter
from astropy.modeling.models import Chebyshev1D, Spline1D
from scipy.ndimage import median_filter
from astropy.stats import sigma_clip
from scipy.interpolate import make_interp_spline

from zsdrp.utils import patched_extract_tqdm

from pyreduce.combine_frames import combine_calibrate, combine_bias
from pyreduce.trace import trace
from pyreduce.trace_model import save_traces, load_traces
from pyreduce.slit_curve import Curvature
from pyreduce.extract import extract_normalize, extract
from pyreduce.wavelength_calibration import WavelengthCalibrationInitialize, WavelengthCalibration
from pyreduce.spectra import ExtractionParams, Spectra, Spectrum
from pyreduce.instruments.common import Instrument

logger = logging.getLogger(__name__)


class Step(ABC):
    @staticmethod
    @abstractmethod
    def run(*args, **kwargs):
        """ Main step logic goes here. This method should be overridden by subclasses. """
        pass

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
    def run(filename: Optional[str | Path] = None,
            *,
            instrument: Optional[Instrument] = None,
            channel: Optional[str] = None,
            default_shape: Optional[tuple[int, int]] = None
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
    def load(filename: str, channel: Optional[str]=None) -> np.ndarray | None:
        if not os.path.exists(filename):
            raise FileNotFoundError(f"File not found: {filename}")
        try:
            with np.load(filename, allow_pickle=True) as data:
                if '.npy' in filename:
                    return data
                else:
                    if channel and channel in data:
                        logger.info(f"Loading mask from {filename}, at key '{channel}'")
                        return data[channel]
                    elif 'mask' in data:
                        logger.info(f"Loading mask from {filename}, at key 'mask'")
                        return data['mask']
                    else:
                        raise ValueError(f"Neither key 'mask' nor {channel} found in {filename}, "
                                         f"save the mask with the appropriate key.")
        except:
            raise ValueError(f"Unsupported file format for {filename}. Only .npz and .npy are supported.")


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
            bias: Optional[np.ndarray] = None,
            bhead: Optional[dict] = None,
            step_cfg: dict,
            **kwargs):
        """
        Run the flat step on the provided filenames using the specified instrument and channel.
        :param filenames: List of filenames to process.
        :param instrument: The instrument to use for the flat step.
        :param channel: The channel to use for the flat step.
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
            order_centers: Optional[dict[int, int | float]] = None,
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
        params = {mapping.get(k,k): v for k, v in step_cfg.items()}
        params['reject_threshold'] = params.get('reject_threshold', 6)
        params.update({'gain': header["e_gain"], 'readnoise': header["e_readn"], 'dark': header["e_drk"]})
        params['scatter'] = kwargs.get('scatter', None)
        if kwargs.get('print_params', True):
            print(f"Normflat parameters: {params}")

        disable_tqdm = kwargs.get('disable_tqdm', True)
        with patched_extract_tqdm(disable_tqdm):
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
                logger.info("Updated trace order numbers with obase=%d",obase)
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


class ScienceWrapper(Step):
    name = 'science'

    @staticmethod
    def run(images: list[str],
            traces: list,
            *,
            instrument: Instrument,
            channel: str,
            bias: Optional[np.ndarray] = None,
            bhead: Optional[dict] = None,
            norm: Optional[np.ndarray] = None,
            mask: Optional[np.ndarray] = None,
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
                   'extraction_reject': 'reject_threshold', 'extraction_method':'extraction_type'}
        params = {mapping.get(k,k): v for k,v in step_cfg.items()}
        bias_scaling = params.pop('bias_scaling')
        norm_scaling = params.pop('norm_scaling')
        params['scatter'] = kwargs.get('scatter', None)

        groups = dict()
        for img in images:
            objname = fits.getheader(img, ext=0)['OBJECT']
            groups[objname] = groups.get(objname, []) + [img]

        group_spectra = dict()
        for objname, imgs in groups.items():
            logger.info(f"Processing {objname} for science extraction with {len(imgs)} images.")
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
                spectrum = extract(im, traces, **params)
            group_spectra[objname] = Spectra(header=head, data=spectrum, params=meta)

        return group_spectra

class BlazeNormalization(Step):
    name = 'blaze'

    @staticmethod
    def run(group_spectra: dict[str, Spectra],
            wave: np.ndarray,
            blaze: np.ndarray,
            free_spectral_range: np.ndarray,
            **kwargs) -> dict[str, Spectra]:
        """
        Run the continuum normalization step on the provided spectra using traces and blaze function.
        :param group_spectra: dict of Spectra objects, keyed by object name.
        :param wave: Wavelength solution array of shape (n_trace, n_cols)
        :param blaze: Blaze function array corresponding to the spectra of shape (n_trace, n_cols).
        :param free_spectral_range: Free spectral range array corresponding to the spectra of shape (n_trace, 2).
        :keyword print_params: If True, prints the supplied parameters used for continuum normalization.
        :return: A new Spectra object containing the continuum-normalized spectra and associated metadata.
        """
        for objname, spectra in group_spectra.items():
            data = []
            for i, sp in enumerate(spectra.data):
                sel = (wave[i] > free_spectral_range[i][0] - 1.0) & (wave[i] < free_spectral_range[i][1] + 1.0)
                spec = (sp.spec / blaze[i])[sel]
                sig = (sp.sig / blaze[i])[sel]
                newsp = Spectrum(m=sp.m, spec=spec, sig=sig, wave=wave[i][sel], cont=blaze[i][sel])
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


def splice(spectra: Spectra, simple=True, **kwargs):
    """
    Splice the orders of the provided spectra into a single 1D spectrum.
    :param spectra: Spectra object containing the extracted spectra and associated metadata.
    :param simple: If True, simply concatenate the orders without any weighting or overlap handling.
    :return: A new Spectra object containing the spliced 1D spectrum and associated metadata.
    """
    wave, spec, sig, cont = np.array([]), np.array([]), np.array([]), np.array([])
    waveorder = np.argsort([np.median(sp.wave) for sp in spectra.data])
    for i, ind in enumerate(waveorder):
        sp = spectra.data[ind]
        if simple or i == 0:
            wave = np.concatenate((wave, sp.wave))
            spec = np.concatenate((spec, sp.spec))
            sig = np.concatenate((sig, sp.sig))
            cont = np.concatenate((cont, sp.cont))
        else:
            # outer loop already in ascending wavelength order
            # get the spec median in the overlap region for the chain and new order
            overlap_curr = (sp.wave >= wave[0]) & (sp.wave <= max(wave[-1] + 10., sp.wave[int(0.05 * len(sp.wave))]))
            overlap_prev = (wave >= min(sp.wave[0] - 10., wave[int(0.95 * len(wave))])) & (wave <= sp.wave[-1])
            median_curr = np.nanmedian(sp.spec[overlap_curr])
            # std_curr = np.nanstd(sp.spec[overlap_curr]) if np.any(overlap_curr) else 1.0
            # weight_curr = 1.0/(std_curr ** 2) if not np.isnan(std_curr) else 1.0
            median_prev = np.nanmedian(spec[overlap_prev])
            # std_prev = np.nanstd(spec[overlap_prev]) if np.any(overlap_prev) else 1.0
            # weight_prev = 1.0/(std_prev ** 2) if not np.isnan(std_prev) else 1.0
            # new_median = (median_curr * weight_curr + median_prev * weight_prev) / (weight_curr + weight_prev)
            # scale both prev and curr to the new median everywhere
            # prev_fac = new_median / median_prev
            curr_fac = median_prev / median_curr
            spec = np.concatenate((spec, sp.spec * curr_fac))
            sig = np.concatenate((sig, sp.sig * curr_fac))
            cont = np.concatenate((cont, sp.cont * curr_fac))
            wave = np.concatenate((wave, sp.wave))

    sorted_wv = np.argsort(wave)
    new_spectrum = Spectrum(m=None, spec=spec[sorted_wv], sig=sig[sorted_wv], wave=wave[sorted_wv],
                            cont=cont[sorted_wv])
    return Spectra(header=spectra.header, data=[new_spectrum], params=spectra.params)


def fit_smooth_continuum(x, y, degree=3, n_knots=10, sigma=3.0, median_window=51, niter=5):
    """
    Fit a smooth continuum to log10(y) using a spline with iterative sigma clipping.
    FittingWithOutlierRemoval can't wrap the astropy spline fitters, so clipping is done here.
    :param x: 1D array of x values (e.g., wavelength).
    :param y: 1D array of y values (e.g., flux). Non-positive and non-finite values are ignored.
    :param degree: Degree of the spline (1-5).
    :param n_knots: Number of interior knots; fewer knots give a smoother fit.
    :param sigma: Number of standard deviations to use for outlier rejection.
    :param median_window: Size of the median filter window (pixels), applied before fitting.
    :param niter: Maximum number of fit/clip iterations.
    :return: Fitted Spline1D model of log10(y); evaluate as 10 ** model(x).
    """
    valid = np.isfinite(x) & np.isfinite(y) & (y > 0)
    order = np.argsort(x[valid])
    x_valid = x[valid][order]
    ys = median_filter(np.log10(y[valid][order]), size=median_window, mode='nearest')

    fitter = SplineExactKnotsFitter()
    keep = np.ones(len(x_valid), dtype=bool)
    for _ in range(niter):
        # knots at quantiles of the kept points, so every knot interval still has data after clipping
        knots = np.quantile(x_valid[keep], np.linspace(0, 1, n_knots + 2)[1:-1])
        cont_fit = fitter(Spline1D(degree=degree), x_valid[keep], ys[keep], t=knots)
        new_keep = ~sigma_clip(ys - cont_fit(x_valid), sigma=sigma).mask
        if np.array_equal(new_keep, keep):
            break
        keep = new_keep
    return cont_fit