from __future__ import annotations
from pathlib import Path
from typing import Optional, Any, Sequence
import logging
import enum
from astropy import units as u

from zsdrp.ZSHOOTER import ZSHOOTER
from zsdrp.steps import *
from zsdrp.utils import load_instrument_settings, save_spectra_to_ascii
from pyreduce.combine_frames import combine_bias, combine_calibrate

logger = logging.getLogger(__name__)

class ReductionStep(enum.StrEnum):
    MASK = "mask"
    # SCATTER = "scatter"
    TRACE = "trace"
    CURVATURE = "curvature"
    NORM_FLAT = "norm_flat"
    WAVECAL = "wavecal"
    SCIENCE = "science"
    CONTINUUM = "continuum"

class Channel(enum.StrEnum):
    BLUE = "BLUE"
    GREEN = "GREEN"
    RED = "RED"
    YJ = "YJ"
    H = "H"
    K = "K"

def _validate_step(stepkey: str | ReductionStep) -> ReductionStep:
    if isinstance(stepkey, ReductionStep):
        return stepkey
    try:
        valkey = ReductionStep(stepkey)
        return valkey
    except ValueError as e:
        raise ValueError(f"Invalid reduction step: {stepkey}. Valid options are: {[step.value for step in ReductionStep]}") from e

def _reduce_cals(instrument: ZSHOOTER, channel: str, channel_cfg: dict, arc_files: Sequence[str],
                flat_files: Sequence[str], bias: Optional[np.ndarray], bhead: Optional[dict],
                disable_steps: list[ReductionStep], output_dir: Optional[str], trace_files=None, **kwargs) -> dict:

    flat, fhead = FlatWrapper.run(flat_files, instrument=instrument, channel=channel, bias=bias, bhead=bhead,
                                  step_cfg=channel_cfg['flat'], **kwargs)

    res = dict()
    # trace
    if ReductionStep.TRACE in disable_steps:
        logger.warning(f"Trace step is disabled. Cannot move forward with any other steps.")
        return res
    if flat is None:
        logger.warning(f"No master flat available for channel {channel}, cannot perform trace step.")
        return res
    trace_image = flat
    if trace_files is not None and list(trace_files) != list(flat_files):
        trace_image, _ = FlatWrapper.run(trace_files, instrument=instrument, channel=channel, bias=bias, bhead=bhead,
                                         step_cfg=channel_cfg['flat'], **kwargs)
    traces = TraceWrapper.run(trace_image, step_cfg=channel_cfg[ReductionStep.TRACE], **kwargs)
    logger.info("Traced order-definition files successfully.")

    # curvature
    if ReductionStep.CURVATURE in disable_steps:
        logger.warning(f"Curvature step is disabled. Skipping curvature correction.")
    if arc_files is None or len(arc_files) == 0:
        logger.warning(f"No arc files found for channel {channel}, check your input files. "
                       f"Skipping arc combination and curvature correction for this channel.")
    else:
        arc = combine_calibrate(files=list(arc_files), instrument=instrument, channel=channel, bias=bias, bhead=bhead)
        logger.info("Combined arc files successfully.")
        traces = CurvatureWrapper.run(arc[0], traces, step_cfg=channel_cfg[ReductionStep.CURVATURE], **kwargs)
        logger.info("Curvature correction created successfully.")

    res['traces'] = traces

    # normflat
    norm, blaze, slitfunc, slitfunc_meta = None, None, None, None
    if ReductionStep.NORM_FLAT in disable_steps:
        logger.warning(f"Normflat step is disabled. Skipping normflat correction.")
    elif flat is None:
        logger.warning(f"No master flat for channel {channel}, cannot perform normflat step.")
    else:
        norm, blaze, slitfunc, slitfunc_meta = NormflatWrapper.run(flat, fhead, traces,
                                                                   step_cfg=channel_cfg[ReductionStep.NORM_FLAT],
                                                                   **kwargs)
        logger.info("Normflat correction created successfully.")
        if output_dir is not None:
            NormflatWrapper.save(norm, blaze, slitfunc, slitfunc_meta, filename=f"{output_dir}/norm_{channel}.npz")
    res.update({'norm': norm, 'blaze': blaze, 'slitfunc': slitfunc, 'slitfunc_meta': slitfunc_meta})

    # wavecal
    wave_img, arc_lines = None, None
    if ReductionStep.WAVECAL in disable_steps:
        logger.warning(f"Wavecal step is disabled. Skipping wavelength calibration.")
    elif arc_files is None or len(arc_files) == 0:
        logger.warning(f"No arc files found for channel {channel}, check your input files. "
                       f"Skipping wavecal for this channel.")
    else:
        arc = combine_calibrate(files=list(arc_files), instrument=instrument, channel=channel, bias=bias,
                                bhead=bhead, norm=norm, traces=traces)
        wave_img, arc_lines = simple_wavesol(arc[0], arc[1], traces, trace_list=kwargs.get('trace_list'), lamp_lines=kwargs.get('lamp_lines'))
        if output_dir is not None:
            orders = [t.m for t in traces if not t.invalid]
            np.savez(f"{output_dir}/wavecal_{channel}.npz", wave_img=wave_img, orders=orders, arc_lines=arc_lines.as_array())
    res.update({'wave_img': wave_img, 'arc_lines': arc_lines})
    if output_dir is not None:
        # Wavelength calibration assigns the measured traces their physical order numbers.
        TraceWrapper.save(traces, f"{output_dir}/trace_{channel}.fits")

    return res


def _run_per_channel_reduction(instrument: ZSHOOTER, channel: str, channel_cfg: dict, science_files: Sequence[str],
                              bias_files: Sequence[str], arc_files: Sequence[str], flat_files: Sequence[str],
                              free_spectral_range: dict, disable_steps: list[ReductionStep],
                              output_dir: Optional[str], reuse_cals: bool = True, trace_files=None, **kwargs) -> dict:
    chanres: dict[str, Any] = dict()
    # load mask
    mask = None
    if ReductionStep.MASK not in disable_steps:
        mask_file = instrument.get_mask_filename(channel)
        mask = MaskWrapper.run(mask_file, instrument=instrument, channel=channel)
    chanres = {'mask': mask}

    # create master bias
    bias, bhead = BiasWrapper.run(bias_files, instrument=instrument, channel=channel)
    chanres['master_bias'] = (bias, bhead)

    if reuse_cals and output_dir is not None:
        try:
            traces = TraceWrapper.load(f"{output_dir}/trace_{channel}.fits")
            norm, blaze, slitfunc, slitfunc_meta = NormflatWrapper.load(f"{output_dir}/norm_{channel}.npz")
            with np.load(f"{output_dir}/wavecal_{channel}.npz") as data:
                wave_img = data['wave_img']
                if not np.array_equal(data['orders'], [t.m for t in traces if not t.invalid]):
                    raise ValueError("Saved wavelength rows and trace order numbers differ; rebuild calibrations.")
                arc_lines = Table(data['arc_lines'])
            chanres.update({'traces': traces, 'norm': norm, 'blaze': blaze, 'slitfunc': slitfunc,
                            'slitfunc_meta': slitfunc_meta, 'wave_img': wave_img, 'arc_lines': arc_lines})
        except Exception as e:
            logger.warning(f"Could not load traces for channel {channel} from {output_dir}. "
                           f"Will attempt to reduce calibration files. Error: {e}")
    if 'traces' not in chanres:
        # reduce calibration files
        calres = _reduce_cals(instrument, channel, channel_cfg, arc_files, flat_files, bias, bhead,
                             disable_steps=disable_steps, output_dir=output_dir, trace_files=trace_files, **kwargs)
        chanres.update(calres)

    # science extraction
    if ReductionStep.SCIENCE in disable_steps:
        logger.warning(f"Science step is disabled. Skipping science data extraction.")
        return chanres
    group_spectra = ScienceWrapper.run(list(science_files), chanres['traces'], instrument=instrument,
                                       channel=channel, bias=bias, bhead=bhead, norm=chanres['norm'], mask=None,
                                       step_cfg=channel_cfg[ReductionStep.SCIENCE], **kwargs)
    chanres.update({'spectra': group_spectra, 'level': 0})

    # blaze normalization
    if ReductionStep.CONTINUUM in disable_steps:
        logger.warning(f"Continuum step is disabled. Skipping blaze normalization.")
    elif chanres['blaze'] is None or chanres['wave_img'] is None:
        logger.warning(f"No blaze function or wavesol available for channel {channel}, "
                       f"cannot perform blaze normalization.")
    else:
        logger.info(f"Performing blaze normalization for channel {channel}.")
        group_spectra = BlazeNormalization.run(group_spectra, chanres['wave_img'], chanres['blaze'], free_spectral_range)
        chanres.update({'spectra': group_spectra, 'level': 1})

    return chanres


def run_reduction(files: dict[Channel, dict[str, Any]],
                  channels: Optional[list[Channel]] = None,
                  output_dir: Optional[str | Path] = None,
                  disable_steps: Optional[list[ReductionStep]] = None,
                  disable_all_plots: bool = False,
                  reuse_cals: bool = True,
                  instrument=None,
                  trace_list=None,
                  lamp_lines=None,
                  **kwargs):
    """
    Run the reduction pipeline with a configured instrument and optional ScopeSim trace list.
    :param files: Nested dict of files for each channel.
                  The optional 'trace' group supplies order-definition frames separately from the full-slit flat.
    :param channels: Instrument channel names to reduce; None selects all configured channels.
    :param output_dir: Directory to save the output files. If None, files will not be saved.
    :param disable_steps: List of steps to disable during the reduction. If None, all steps will be run. Options include: mask, scatter, trace, curvature, norm_flat, wavecal, science, continuum.
    :param disable_all_plots: If True, all diagnostic plotting will be disabled during the reduction.
    :param reuse_cals: If True, reuse existing reduced calibration files if they exist.
    :param instrument: PyReduce Instrument; defaults to the existing ZSHOOTER configuration.
    :param trace_list: Configured ScopeSim spectral trace list used by the observation.
    :param lamp_lines: Lamp table with vacuum wavelengths in Angstrom and relative amplitudes.
    :keyword require_variance: Require prepared SCI+VARIANCE inputs; missing variance fails instead of using legacy uncertainties.
    :keyword print_params: If True, print the parameters for each step during the reduction.

    :return: Dictionary containing the results of the reduction for each channel.
    """
    # load instrument
    zs = ZSHOOTER() if instrument is None else instrument

    # load step settings
    settings_cfg = load_instrument_settings(zs)

    # validate input files
    files = {str(chankey): filedict for chankey, filedict in files.items()}
    channels = zs.config.channels if channels is None else channels if isinstance(channels, list) else [channels]
    channels = [str(chan) for chan in channels]
    for channel in channels:
        if channel not in zs.config.channels:
            raise ValueError(f'{channel} is not a channel of {zs.name}')

    # validate output_dir
    if output_dir is not None and Path(output_dir).resolve().is_dir():
        output_dir = str(Path(output_dir).resolve())
    else:
        output_dir = None

    # validate disable_steps
    disable_steps = disable_steps if disable_steps is not None else []
    disable_steps = [_validate_step(step) for step in disable_steps]

    # load free spectral ranges for ZSHOOTER
    fsrs = dict()
    if isinstance(zs, ZSHOOTER):
        with np.load(os.path.join(zs._inst_dir, 'free_spectral_ranges.npz')) as f:
            for chan in channels:
                fsrs[chan] = dict(zip(f[f'{chan}_orders'], f[chan], strict=True))
    else:
        for channel in channels:
            arm_id = zs.config.channels.index(channel)
            fsrs[channel] = {int(st.trace_id.rsplit('_', 1)[1]): (st.wave_min * 1e4, st.wave_max * 1e4)
                             for st in trace_list.spectral_traces.values() if st.meta['image_plane_id'] == arm_id}

    # run reduction for each channel
    results = dict() # for per channel intermediate results and calibration products
    for channel in channels:
        print(f"Running reduction for channel {channel}...")
        if channel not in files:
            logger.warning(f"No files found for channel {channel}, skipping reduction for this channel.")
            continue
        chanfiles = files[channel]
        chancfg = settings_cfg[channel]

        if disable_all_plots:
            for key in chancfg.keys():
                if 'plot' in chancfg[key]:
                    chancfg[key]['plot'] = False

        chanres = _run_per_channel_reduction(zs, channel, chancfg, science_files=chanfiles.get('science', []),
                                            bias_files=chanfiles.get('bias', []),
                                            arc_files=chanfiles.get('wavecal_master', []),
                                            flat_files=chanfiles.get('flat', []),
                                            trace_files=chanfiles.get('trace'),
                                            free_spectral_range=fsrs[channel], disable_steps=disable_steps,
                                            output_dir=output_dir, reuse_cals=reuse_cals, trace_list=trace_list, lamp_lines=lamp_lines, **kwargs)
        chanres['steps_run'] = [step.value for step in ReductionStep if step not in disable_steps]
        results[channel] = chanres
    return results


def run_flux_calibration_and_stitch(results: dict,
                                    reference_wave: Optional[np.ndarray] = None,
                                    reference_flux: Optional[np.ndarray] = None,
                                    standard_star_name: str = "STANDARD",
                                    plot: bool = True,
                                    output_dir: Optional[str] = None):
    """
    Run flux calibration and stitch spectra across channels.
    :param results: Dictionary containing the results of the reduction for each channel.
    :param reference_wave: Optional reference wavelength array for flux normalization.
    :param reference_flux: Optional reference flux density in erg/s/cm2/Angstrom, evaluated at reference_wave in Angstrom.
    :param standard_star_name: Name of the standard star in files to use for flux calibration. Default is "STANDARD".
    :param plot: Whether to plot the flux calibration results. Default is True.
    :param output_dir: Directory to save the output files. If None, no files will be saved.
    """
    # create reference spectrum object
    if reference_wave is not None and reference_flux is not None:
        reference_spectrum = Spectrum(spec=reference_flux, wave=reference_wave, m=None, sig=None)
    else:
        reference_spectrum = None

    # validate output_dir
    if output_dir is not None and Path(output_dir).resolve().is_dir():
        output_dir = str(Path(output_dir).resolve())
    else:
        output_dir = None

    objects = dict()  # to collect all channel spectra per object
    for channel, chanres in results.items():
        # check if standard cal is present, is blaze normalized, and reference spectrum is present
        group_spectra = chanres.get("spectra", {})
        standard_spectra = group_spectra.get(standard_star_name.upper(), None)

        sens_func = None
        if standard_spectra is None or reference_spectrum is None:
            logger.warning(f"Standard star spectrum with object name {standard_star_name.upper()} not observed, "
                           f"skipping flux calibration.")
        elif chanres.get("level", 0) == 0:
            logger.warning(f"Spectra for channel {channel} are not blaze normalized, skipping flux calibration.")
        else:
            sens_func = SensitivityFunction.run(standard_spectra, reference_spectrum, plot=plot)[0]
            chanres["level"] = 2

        lvl = chanres.get("level", 0)
        steps_run = chanres.get("steps_run", [])
        for objname, spectra in group_spectra.items():
            newsp = []
            flux_calibrated = sens_func is not None and objname != standard_star_name.upper()
            exptime = float(spectra.header["EXPTIME"])
            for sp in spectra.data:
                if not flux_calibrated:
                    factor = 1.0
                else:
                    factor = 10 ** sens_func(sp.wave)
                sp.spec *= factor / exptime
                sp.sig *= factor / exptime
                if sp.covariance is not None:
                    scale = np.broadcast_to(factor / exptime, sp.spec.shape)
                    sp.covariance = sp.covariance.multiply(scale[:, None]).multiply(scale[None, :]).tocsr()
                    sp.sig = np.sqrt(sp.covariance.diagonal())
                newsp.append(sp)
            header = spectra.header.copy()
            if flux_calibrated:
                output_unit = u.erg / (u.s * u.cm**2 * u.AA)
            elif 'BUNIT' in header:
                output_unit = u.Unit(header['BUNIT']) / u.s
            else:
                output_unit = None  # Legacy frames do not identify their input count unit.
            if output_unit is not None:
                header['BUNIT'] = output_unit.to_string()
                header['COVUNIT'] = (output_unit**2).to_string()
            spectra.header = header
            new_spectra = Spectra(data=newsp, header=header)
            objects[objname] = objects.get(objname, []) + [new_spectra]

            if output_dir is not None:
                suffix = "_fluxcal" if flux_calibrated else "_raw" if lvl == 0 else "_blazecal"
                new_spectra.save(f"{output_dir}/spectra_{objname}_{channel}{suffix}.fits", steps=steps_run)
                save_spectra_to_ascii(new_spectra, f"{output_dir}/spectra_{objname}_{channel}{suffix}.txt")

    # stitch all objects across channels
    final_spectra = dict()
    for objname, speclist in objects.items():
        specl = [sp.data[0] for sp in speclist]
        specl = Spectra(data=specl, header=speclist[0].header)
        # Calibration response sets the flux scale; fitting additional overlap ratios would add another noisy estimator.
        stitched = splice(specl, simple=all(sp.covariance is not None for sp in specl.data))
        final_spectra[objname] = stitched
        if output_dir is not None:
            stitched.save(f"{output_dir}/spectra_{objname}_stitched.fits")
            save_spectra_to_ascii(stitched, f"{output_dir}/spectra_{objname}_stitched.txt")

    return final_spectra


if __name__ == '__main__':
    pass