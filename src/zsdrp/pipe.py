from __future__ import annotations
from pathlib import Path
from typing import Optional, Any, Sequence
import logging
import enum

from zsdrp.ZSHOOTER import ZSHOOTER
from zsdrp.steps import *
from zsdrp.utils import load_zshooter_settings, save_spectra_to_ascii
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

def _validate_channel(chankey: str | Channel) -> Channel:
    if isinstance(chankey, Channel):
        return chankey
    try:
        valkey = Channel(chankey)
        return valkey
    except ValueError as e:
        raise ValueError(f"Invalid channel: {chankey}. Valid options are: {[chan.value for chan in Channel]}") from e

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
                disable_steps: list[ReductionStep], output_dir: Optional[str], **kwargs) -> dict:

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
    traces = TraceWrapper.run(flat, step_cfg=channel_cfg[ReductionStep.TRACE], **kwargs)
    logger.info("Traced flat files successfully.")

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
    if output_dir is not None:
        TraceWrapper.save(traces, f"{output_dir}/trace_{channel}.fits")

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
    wave_img, wavesol, linelist, metrics = None, None, None, None
    if ReductionStep.WAVECAL in disable_steps:
        logger.warning(f"Wavecal step is disabled. Skipping wavelength calibration.")
    elif arc_files is None or len(arc_files) == 0:
        logger.warning(f"No arc files found for channel {channel}, check your input files. "
                       f"Skipping wavecal for this channel.")
    else:
        arc = combine_calibrate(files=list(arc_files), instrument=instrument, channel=channel, bias=bias,
                                bhead=bhead, norm=norm, traces=traces)
        step = ReductionStep.WAVECAL.value
        master_cfg = channel_cfg[f'{step}_master']
        init_cfg = channel_cfg[f'{step}_init']
        cfg = channel_cfg[step]
        wave_img, wavesol, linelist, metrics = WavecalWrapper.run(arc[0], arc[1], traces, instrument=instrument,
                                                                  channel=channel, master_step_cfg=master_cfg,
                                                                  init_step_cfg=init_cfg, step_cfg=cfg,
                                                                  **kwargs)
        if output_dir is not None:
            WavecalWrapper.save(wave_img, wavesol, filename=f"{output_dir}/wavecal_{channel}.npz")
    res.update({'wave_img': wave_img, 'wavesol': wavesol, 'linelist': linelist, 'metrics': metrics})

    return res


def _run_per_channel_reduction(instrument: ZSHOOTER, channel: str, channel_cfg: dict, science_files: Sequence[str],
                              bias_files: Sequence[str], arc_files: Sequence[str], flat_files: Sequence[str],
                              free_spectral_range: np.ndarray, disable_steps: list[ReductionStep],
                              output_dir: Optional[str], reuse_cals: bool = True, **kwargs) -> dict:
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
            wave_img, wavesol = WavecalWrapper.load(f"{output_dir}/wavecal_{channel}.npz")
            chanres.update({'traces': traces, 'norm': norm, 'blaze': blaze, 'slitfunc': slitfunc,
                            'slitfunc_meta': slitfunc_meta, 'wave_img': wave_img, 'wavesol': wavesol})
        except Exception as e:
            logger.warning(f"Could not load traces for channel {channel} from {output_dir}. "
                           f"Will attempt to reduce calibration files. Error: {e}")
    if 'traces' not in chanres:
        # reduce calibration files
        calres = _reduce_cals(instrument, channel, channel_cfg, arc_files, flat_files, bias, bhead,
                             disable_steps=disable_steps, output_dir=output_dir, **kwargs)
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
        free_spectral_range = free_spectral_range[1:] if channel=='RED' else free_spectral_range # TODO: Hack for now
        group_spectra = BlazeNormalization.run(group_spectra, chanres['wave_img'], chanres['blaze'], free_spectral_range)
        chanres.update({'spectra': group_spectra, 'level': 1})

    return chanres


def run_reduction(files: dict[Channel, dict[str, Any]],
                  channels: Optional[list[Channel]] = None,
                  output_dir: Optional[str | Path] = None,
                  disable_steps: Optional[list[ReductionStep]] = None,
                  disable_all_plots: bool = False,
                  reuse_cals: bool = True,
                  **kwargs):
    """
    Run the full reduction pipeline for ZSHOOTER data.
    :param files: Nested dict of files for each channel.
    :param channels: List of channels to reduce. If None, all channels will be reduced. Options are BLUE, GREEN, RED, YJ, H, K.
    :param output_dir: Directory to save the output files. If None, files will not be saved.
    :param disable_steps: List of steps to disable during the reduction. If None, all steps will be run. Options include: mask, scatter, trace, curvature, norm_flat, wavecal, science, continuum.
    :param disable_all_plots: If True, all diagnostic plotting will be disabled during the reduction.
    :param reuse_cals: If True, reuse existing reduced calibration files if they exist.
    :keyword print_params: If True, print the parameters for each step during the reduction.

    :return: Dictionary containing the results of the reduction for each channel.
    """
    # load instrument
    zs = ZSHOOTER()

    # load step settings
    settings_cfg = load_zshooter_settings(zshooter_instrument=zs)

    # validate input files
    files = {_validate_channel(chankey): filedict for chankey, filedict in files.items()}

    # validate channels
    channels = [chan for chan in Channel] if channels is None else channels if isinstance(channels, list) else [channels]
    channels = [_validate_channel(chan) for chan in channels]

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
    with np.load(os.path.join(zs._inst_dir, 'free_spectral_ranges.npz')) as f:
        for chan in channels:
            fsrs[chan] = f[chan.value]

    # run reduction for each channel
    results = dict() # for per channel intermediate results and calibration products
    for channel in channels:
        print(f"Running reduction for channel {channel}...")
        if channel not in files:
            logger.warning(f"No files found for channel {channel}, skipping reduction for this channel.")
            continue
        chanfiles = files[channel]
        chancfg = settings_cfg[channel.value]

        if disable_all_plots:
            for key in chancfg.keys():
                if 'plot' in chancfg[key]:
                    chancfg[key]['plot'] = False

        chanres = _run_per_channel_reduction(zs, channel.value, chancfg, science_files=chanfiles.get('science', []),
                                            bias_files=chanfiles.get('bias', []),
                                            arc_files=chanfiles.get('wavecal_master', []),
                                            flat_files=chanfiles.get('flat', []),
                                            free_spectral_range=fsrs[channel], disable_steps=disable_steps,
                                            output_dir=output_dir, reuse_cals=reuse_cals, **kwargs)
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
    :param reference_flux: Optional reference flux array for flux normalization.
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
            for sp in spectra.data:
                if sens_func is None or objname==standard_star_name.upper():
                    factor = 1.0
                else:
                    factor = 10 ** sens_func(sp.wave)
                sp.spec *= factor
                sp.sig *= factor
                newsp.append(sp)
            new_spectra = Spectra(data=newsp, header=spectra.header)
            objects[objname] = objects.get(objname, []) + [new_spectra]

            if output_dir is not None:
                suffix = "_raw" if lvl == 0 else "_blazecal" if lvl == 1 else "_fluxcal"
                new_spectra.save(f"{output_dir}/spectra_{objname}_{channel}{suffix}.fits", steps=steps_run)
                save_spectra_to_ascii(new_spectra, f"{output_dir}/spectra_{objname}_{channel}{suffix}.txt")

    # stitch all objects across channels
    final_spectra = dict()
    for objname, speclist in objects.items():
        specl = [sp.data[0] for sp in speclist]
        specl = Spectra(data=specl, header=speclist[0].header)
        stitched = splice(specl, simple=False)
        final_spectra[objname] = stitched
        if output_dir is not None:
            save_spectra_to_ascii(stitched, f"{output_dir}/spectra_{objname}_stitched.txt")

    return final_spectra


if __name__ == '__main__':
    pass