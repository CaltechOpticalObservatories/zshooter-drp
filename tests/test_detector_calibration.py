import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from pyreduce.trace_model import Trace

from zsdrp import pipe
from zsdrp.ZSHOOTER import ZSHOOTER
from zsdrp.steps import TraceWrapper


def detector_header():
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ['LINEAR', 'LINEAR']
    wcs.wcs.cunit = ['mm', 'mm']
    wcs.wcs.cdelt = [.018, .018]
    wcs.wcs.crpix = [4.5, 3.5]
    header = wcs.to_header(key='D')
    header['DETMODE'] = 'SPEC_ALTDETECT'
    header['CALNX'], header['CALNY'] = 8, 6
    return header


@pytest.mark.parametrize('change,expected', [('mode', 'detector package'), ('shape', 'detector shape'), ('pitch', 'detector WCS'), ('position', 'detector WCS'), ('missing', 'DETMODE'), ('same', None)])
@pytest.mark.parametrize('suffix', ['.fits', '.fits.gz'])
def test_saved_calibration_must_match_detector(monkeypatch, tmp_path, change, expected, suffix):
    header = detector_header()
    traces = [Trace(m=42, pos=np.array([0., 2.]), column_range=(0, 8), height=3)]
    trace_path = tmp_path/f'trace_H{suffix}'
    TraceWrapper.save(traces, trace_path, header=header)
    saved = fits.getheader(trace_path)
    assert saved['DETMODE'] == 'SPEC_ALTDETECT'
    assert saved['CDELT1D'] == .018
    assert (saved['CALNX'], saved['CALNY']) == (8, 6)
    image = np.zeros((6, 8))
    if change == 'mode':
        header['DETMODE'] = 'SPEC'
    elif change == 'shape':
        image = np.zeros((7, 8))
    elif change == 'pitch':
        header['CDELT1D'] = .015
    elif change == 'position':
        header['CRVAL1D'] = .1
    elif change == 'missing':
        del header['DETMODE']
    science = tmp_path/'science.fits'
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(image, header)]).writeto(science)
    monkeypatch.setattr(pipe.BiasWrapper, 'run', lambda *a, **kw: (0., fits.Header()))
    monkeypatch.setattr(pipe.NormflatWrapper, 'load', lambda *a: (None, None, None, None))
    np.savez(tmp_path/'wavecal_H.npz', wave_img=np.zeros((1, 8)), orders=[42], arc_lines=np.array([(42,)], dtype=[('order', 'i4')]))
    arguments = dict(instrument=ZSHOOTER(), channel='H', channel_cfg={}, science_files=[science], bias_files=[], arc_files=[], flat_files=[], free_spectral_range={}, disable_steps=[pipe.ReductionStep.MASK, pipe.ReductionStep.SCIENCE], output_dir=tmp_path)
    if expected:
        with pytest.raises(KeyError if change == 'missing' else ValueError, match=expected):
            pipe._run_per_channel_reduction(**arguments)
    else:
        result = pipe._run_per_channel_reduction(**arguments)
        assert result['traces'][0].m == 42
