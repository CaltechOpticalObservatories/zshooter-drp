from __future__ import annotations
from pathlib import Path
from typing import Literal

from zsdrp.ZSHOOTER import ZSHOOTER
from zsdrp.steps import (
    CurvatureWrapper,
    MaskWrapper,
    NormflatWrapper,
    ScienceWrapper,
    TraceWrapper,
)
from zsdrp.utils import load_zshooter_settings, save_image_to_fits

from pyreduce.combine_frames import combine_bias, combine_calibrate

VALID_STEPS = ['mask', 'scatter', 'trace', 'curvature', 'norm_flat', 'wavecal', 'wavecal_init', 'wavecal_master',
               'science', 'continuum', 'finalize']
ACTIVE_STEPS = ['mask', 'trace', 'curvature', 'norm_flat', 'science']

def run_reduction(files, *,
                  bias_key: str = 'bias', arc_key: str = 'arcs', flat_key: str = 'flat', science_key: str = 'star',
                  zshooter_instrument: ZSHOOTER | None = None,
                  channels: list[str] | Literal['all'] | str = 'all',
                  disable_steps: list[str] | None = None,
                  outdir: str | None = None):
    # load instrument
    zs = zshooter_instrument if zshooter_instrument is not None else ZSHOOTER()
    # load step settings
    settings_cfg = load_zshooter_settings(zshooter_instrument=zs)
    # validate channels
    if isinstance(channels, str):
        channels = zs.config.channels if channels == 'all' else [channels]
    assert isinstance(channels, list) and (all(chan in zs.config.channels for chan in channels)), \
        f"Invalid channels: {channels}. Valid channels are: {zs.config.channels}"
    # validate disable_steps
    disable_steps = disable_steps if disable_steps is not None else []
    assert isinstance(disable_steps, list) and (all(step in VALID_STEPS for step in disable_steps)), \
        f"Invalid disable_steps: {disable_steps}. Valid steps are: {VALID_STEPS}"
    steps_run = list(set(ACTIVE_STEPS) - set(disable_steps))

    results = {}
    for channel in channels:
        chanfiles = files[channel]
        chancfg = settings_cfg[channel]
        # load mask
        mask = MaskWrapper.run(zs, channel) if 'mask' not in disable_steps else None
        # create master bias
        bias, bhead = combine_bias(files=chanfiles[bias_key], instrument=zs, channel=channel)
        # create master arc
        arc, ahead = combine_calibrate(chanfiles[arc_key], instrument=zs, channel=channel, bias=bias, bhead=bhead,
                                       mask=mask)
        # create master flat
        flat, fhead = combine_calibrate(files=chanfiles[flat_key], instrument=zs, channel=channel, bias=bias, bhead=bhead,
                                        mask=mask, **chancfg.get('flat'))
        results[channel] = {'master_bias': (bias, bhead), 'master_arc': (arc, ahead), 'master_flat': (flat, fhead)}

        # trace
        if 'trace' not in disable_steps:
            traces = TraceWrapper.run(flat, chancfg.get('trace', {}))
        else:
            continue

        # curvature
        traces = CurvatureWrapper.run(arc, traces, chancfg.get('curvature', {})) if 'curvature' not in disable_steps else traces
        results[channel]['traces'] = traces
        # normflat
        norm, blaze, slitfunc, slitfunc_meta = NormflatWrapper.run(flat, fhead, traces, chancfg.get('normflat', {})) \
            if 'norm_flat' not in disable_steps else (None, None, None, None)
        results[channel]['norm'] = norm
        results[channel]['blaze'] = blaze
        results[channel]['slitfunc'] = slitfunc
        results[channel]['slitfunc_meta'] = slitfunc_meta
        # science
        spec = ScienceWrapper.run(chanfiles[science_key], traces, instrument=zs, channel=channel, bias=bias, bhead=bhead,
                               norm=norm, step_cfg=chancfg.get('science', {})) if 'science' not in disable_steps else None
        results[channel]['spectra'] = spec

        if outdir is not None and Path(outdir).resolve().is_dir():
            save_image_to_fits(bias, bhead, f"{outdir}/master_bias_{channel}.fits")
            save_image_to_fits(arc, ahead, f"{outdir}/master_arc_{channel}.fits")
            save_image_to_fits(flat, fhead, f"{outdir}/master_flat_{channel}.fits")
            TraceWrapper.save(traces, f"{outdir}/trace_{channel}.fits")
            NormflatWrapper.save(norm, blaze, slitfunc, slitfunc_meta, f"{outdir}/norm_{channel}.fits") if norm is not None else None
            spec.save(f"{outdir}/spectra_{channel}.fits", steps=steps_run) if spec is not None else None

    return results

if __name__ == '__main__':
    pass