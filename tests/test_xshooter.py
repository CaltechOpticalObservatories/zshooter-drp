import numpy as np
import pytest
from astropy.io import fits

from zsdrp.XSHOOTER import XSHOOTER
from zsdrp.utils import detector_to_extraction, extraction_to_detector, load_instrument_settings


@pytest.mark.parametrize('channel,orientation', [('UVB', 1), ('VIS', 3), ('NIR', 0)])
def test_detector_coordinates_follow_the_loaded_image(channel, orientation, tmp_path):
    raw = np.arange(35.).reshape(5, 7)
    header = fits.Header({'INSTRUME': 'XSHOOTER', 'ARM': channel, 'GAIN': 1., 'RON': 2., 'DARK': .02,
                         'BUNIT': 'electron', 'EXPTIME': 300., 'DIT': 300., 'NDIT': 1, 'COMBINE': 'sum', 'OBJECT': 'STAR'})
    filename = tmp_path / 'raw.fits'
    fits.HDUList([fits.PrimaryHDU(header=header), fits.ImageHDU(raw)]).writeto(filename)
    image, loaded = XSHOOTER().load_fits(filename, channel)
    assert loaded['e_orient'] == orientation
    y, x = np.indices(raw.shape)
    xx, yy = detector_to_extraction(x, y, loaded)
    np.testing.assert_array_equal(image[yy, xx], raw)
    xr, yr = extraction_to_detector(xx, yy, loaded)
    np.testing.assert_array_equal(xr, x)
    np.testing.assert_array_equal(yr, y)


@pytest.mark.parametrize('channel,combine,ndit,gain', [('UVB', 'sum', 2, .63), ('VIS', 'sum', 2, .64), ('NIR', 'average', 6, 2.29)])
def test_native_counts_become_accumulated_electrons(channel, combine, ndit, gain, tmp_path):
    raw = np.full((5, 7), 30.)
    header = fits.Header({'INSTRUME': 'XSHOOTER', 'ARM': channel, 'GAIN': gain, 'RDNOISE': 4., 'DARK': .02,
                         'BUNIT': 'adu', 'EXPTIME': 300. * ndit, 'DIT': 300., 'NDIT': ndit, 'COMBINE': combine, 'OBJECT': 'STAR'})
    filename = tmp_path / 'raw.fits'
    fits.HDUList([fits.PrimaryHDU(header=header), fits.ImageHDU(raw)]).writeto(filename)
    image, loaded = XSHOOTER().load_fits(filename, channel)
    np.testing.assert_allclose(image, 30 * gain * (ndit if combine == 'average' else 1))
    assert loaded['EXPTIME'] == 300 * ndit
    assert loaded['e_gain'] == 1
    assert loaded['e_readn'] == 4 * np.sqrt(ndit)
    assert loaded['e_drk'] == .02
    assert loaded['BUNIT'] == 'electron' and loaded['COMBINE'] == 'sum'


def test_xshooter_settings_use_all_three_native_arms():
    instrument = XSHOOTER()
    settings = load_instrument_settings(instrument)
    assert list(settings) == ['UVB', 'VIS', 'NIR']
    assert instrument.config.orientation == [1, 3, 0]
    for cfg in settings.values():
        assert cfg['science']['extraction_method'] == 'optimal'
        assert cfg['science']['smooth_slitfunction'] == .1
        assert cfg['curvature']['dimensionality'] == '2D'
