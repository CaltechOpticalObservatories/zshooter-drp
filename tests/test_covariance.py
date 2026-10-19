import numpy as np
import pytest
from astropy.io import fits
from astropy import units as u
from scipy import sparse
from pyreduce.spectra import Spectrum, Spectra

from zsdrp.XSHOOTER import XSHOOTER
from zsdrp.steps import load_prepared_science, BlazeNormalization, ScienceWrapper, splice
from zsdrp.utils import load_instrument_settings
from zsdrp.pipe import run_flux_calibration_and_stitch


@pytest.mark.parametrize('channel,orientation', [('UVB', 1), ('VIS', 3), ('NIR', 0)])
def test_prepared_variance_follows_pixel_rotation_and_count_scale(channel, orientation, tmp_path):
    science = np.arange(35.).reshape(5, 7) - 12
    variance = np.arange(35.).reshape(5, 7) + 2
    header = fits.Header({'INSTRUME': 'XSHOOTER', 'ARM': channel, 'GAIN': 2., 'RDNOISE': 4., 'DARK': .02,
                         'BUNIT': 'adu', 'EXPTIME': 1200., 'DIT': 300., 'NDIT': 4, 'COMBINE': 'average' if channel == 'NIR' else 'sum',
                         'OBJECT': 'STAR', 'SUBTRACTED': True})
    path = tmp_path / 'combined.fits'
    fits.HDUList([fits.PrimaryHDU(header=header), fits.ImageHDU(science), fits.ImageHDU(variance, name='VARIANCE')]).writeto(path)
    image, var, head = load_prepared_science(path, XSHOOTER(), channel)
    factor = 8 if channel == 'NIR' else 2
    np.testing.assert_array_equal(image, np.rot90(science, -orientation) * factor)
    np.testing.assert_array_equal(var, np.rot90(variance, -orientation) * factor**2)
    assert image.min() < 0  # Negative sky-subtracted signal must not become a Poisson variance estimate.
    assert head['COVCOND'] == 'calibrations fixed'
    assert u.Unit(head['COVUNIT']) == u.electron**2
    extracted = Spectrum(m=1, spec=image.ravel(), sig=np.sqrt(var.ravel()), covariance=sparse.diags(var.ravel(), format='csr'))
    extracted_path = tmp_path / 'extracted_electrons.fits'
    Spectra(header=head, data=[extracted]).save(extracted_path)
    with fits.open(extracted_path) as saved:
        assert u.Unit(saved[0].header['COVUNIT']) == u.electron**2
        assert u.Unit(saved['COV0000'].columns['DATA'].unit) == u.electron**2


def test_blaze_division_propagates_off_diagonal_covariance():
    wave = np.arange(6.)
    blaze = np.arange(6.) + 1
    covariance = sparse.diags([np.full(5, .25), np.full(6, 4.), np.full(5, .25)], [-1, 0, 1], format='csr')
    original = Spectrum(m=42, spec=np.full(6, 10.), sig=np.full(6, 2.), covariance=covariance)
    result = BlazeNormalization.run({'STAR': Spectra(header=fits.Header(), data=[original])}, wave[None], blaze[None], {42: (.5, 4.5)})['STAR'].data[0]
    selected = np.arange(1, 5)
    expected = covariance.toarray()[np.ix_(selected, selected)] / np.outer(blaze[selected], blaze[selected])
    np.testing.assert_allclose(result.covariance.toarray(), expected)
    np.testing.assert_allclose(result.sig**2, np.diag(expected))


def test_stitch_keeps_correlations_within_each_retained_piece():
    pieces=[]
    for first, signal in [(1, 10.), (4, 20.)]:
        covariance = sparse.diags([np.full(4, .5), np.ones(5), np.full(4, .5)], [-1, 0, 1], format='csr')
        pieces.append(Spectrum(m=first, wave=np.arange(first, first + 5.), spec=np.full(5, signal), sig=np.ones(5), cont=np.ones(5), covariance=covariance))
    stitched=splice(Spectra(header=fits.Header(), data=pieces), simple=True).data[0]
    expected=np.zeros(stitched.covariance.shape)
    for p in pieces:
        keep = stitched.spec == p.spec[0]
        src = np.searchsorted(p.wave, stitched.wave[keep])
        expected[np.ix_(keep, keep)] = p.covariance.toarray()[np.ix_(src, src)]
    np.testing.assert_array_equal(stitched.covariance.toarray(), expected)
    assert np.all(np.diff(stitched.wave) > 0)
    with pytest.raises(ValueError, match='simple=True'):
        splice(Spectra(header=fits.Header(), data=pieces), simple=False)


def test_response_and_exposure_scale_flux_and_covariance_together(tmp_path):
    wave=np.linspace(1., 2., 100)
    covariance=sparse.diags([np.full(99, 1.), np.full(100, 4.), np.full(99, 1.)], [-1, 0, 1], format='csr')
    std=Spectrum(m=None, wave=wave, spec=np.full(100, 200.), sig=np.full(100, 2.), cont=np.ones(100), covariance=covariance.copy())
    star=Spectrum(m=None, wave=wave, spec=np.full(100, 1500.), sig=np.full(100, 2.), cont=np.ones(100), covariance=covariance.copy())
    results={'UVB': {'level': 1, 'spectra': {'STANDARD': Spectra(header=fits.Header({'EXPTIME': 100., 'BUNIT': 'electron'}), data=[std]),
                                          'STAR': Spectra(header=fits.Header({'EXPTIME': 300., 'BUNIT': 'electron'}), data=[star])}}}
    products=run_flux_calibration_and_stitch(results, reference_wave=wave, reference_flux=np.full(100, 3.), plot=False, output_dir=tmp_path)
    output=products['STAR'].data[0]
    np.testing.assert_allclose(output.spec, 7.5, rtol=1e-10)
    np.testing.assert_allclose(output.covariance.toarray(), covariance.toarray() * (.005)**2, rtol=1e-10, atol=1e-20)
    np.testing.assert_allclose(output.sig**2, output.covariance.diagonal())
    flux_unit = u.erg / (u.s * u.cm**2 * u.AA)
    for obj, unit, suffix in [('STAR', flux_unit, 'fluxcal'), ('STANDARD', u.electron/u.s, 'blazecal')]:
        saved=Spectra.read(tmp_path / f'spectra_{obj}_UVB_{suffix}.fits', raw=True)
        assert u.Unit(saved.header['BUNIT']) == unit
        assert u.Unit(saved.header['COVUNIT']) == unit**2
        assert u.Unit(products[obj].header['BUNIT']) == unit
    assert not (tmp_path / 'spectra_STANDARD_UVB_fluxcal.fits').exists()
    np.testing.assert_allclose(products['STANDARD'].data[0].spec, 2.)
    assert u.Unit(results['UVB']['spectra']['STAR'].header['BUNIT']) == flux_unit


def test_required_variance_cannot_fall_back_to_residual_noise(tmp_path):
    header = fits.Header({'INSTRUME': 'XSHOOTER', 'ARM': 'NIR', 'GAIN': 1., 'RON': 4., 'DARK': .02,
                         'BUNIT': 'electron', 'EXPTIME': 300., 'DIT': 300., 'NDIT': 1, 'COMBINE': 'sum',
                         'OBJECT': 'STAR', 'HIERARCH SUBTRACTED': True})
    path=tmp_path/'missing_variance.fits'
    fits.HDUList([fits.PrimaryHDU(header=header), fits.ImageHDU(np.ones((5, 7)))]).writeto(path)
    instrument=XSHOOTER()
    cfg=load_instrument_settings(instrument)['NIR']['science']
    with pytest.raises(KeyError, match='VARIANCE'):
        ScienceWrapper.run([str(path)], [], instrument=instrument, channel='NIR', step_cfg=cfg, require_variance=True, print_params=False)
