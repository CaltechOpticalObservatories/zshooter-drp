from pathlib import Path

import numpy as np
import pytest
import yaml
from astropy.io import fits
from pyreduce.spectra import Spectra, Spectrum
from pyreduce.trace_model import Trace

from zsdrp.ZSHOOTER import ZSHOOTER
from zsdrp.steps import BlazeNormalization, TraceWrapper


@pytest.mark.parametrize('orders', [(58, 59, 80), (80, 58, 59), (59, 80)])
def test_fsr_follows_physical_order_with_missing_or_reordered_traces(orders):
    fsrs = {58: (100., 110.), 59: (200., 210.), 80: (300., 310.)}
    wave = np.array([np.linspace(fsrs[m][0] - 2, fsrs[m][1] + 2, 29) for m in orders])
    blaze = np.full(wave.shape, 5.)
    spectra = Spectra(header=fits.Header(), data=[Spectrum(m=m, spec=np.full(29, 30.), sig=np.full(29, 10.)) for m in orders])
    reduced = BlazeNormalization.run({'flat': spectra}, wave, blaze, fsrs)['flat'].data[0]
    expected_wave = np.sort(np.concatenate([w[(w > fsrs[m][0]) & (w < fsrs[m][1])] for m, w in zip(orders, wave)]))
    np.testing.assert_array_equal(reduced.wave, expected_wave)
    np.testing.assert_allclose(reduced.spec, 6.)
    np.testing.assert_allclose(reduced.sig, 2.)


def test_all_twenty_red_orders_survive_normalization():
    with np.load(Path(ZSHOOTER()._inst_dir) / 'free_spectral_ranges.npz') as data:
        orders = data['RED_orders']
        fsrs = dict(zip(orders, data['RED'], strict=True))
    wave = np.array([np.linspace(*fsrs[m], 32) for m in orders])
    blaze = np.ones_like(wave)
    spectra = Spectra(header=fits.Header(), data=[Spectrum(m=m, spec=np.ones(32), sig=np.ones(32)) for m in orders])
    reduced = BlazeNormalization.run({'red': spectra}, wave, blaze, fsrs)['red'].data[0]
    np.testing.assert_array_equal(orders, np.arange(37, 57))
    for m in orders:
        assert np.any((reduced.wave > fsrs[m][0]) & (reduced.wave < fsrs[m][1]))


def test_missing_physical_order_has_no_positional_fallback():
    spectra = Spectra(header=fits.Header(), data=[Spectrum(m=80, spec=np.ones(16), sig=np.ones(16))])
    with pytest.raises(KeyError, match='80'):
        BlazeNormalization.run({'star': spectra}, np.arange(16.)[None], np.ones((1, 16)), {79: (0., 15.)})


def test_zero_flat_response_is_excluded_from_flux_and_variance():
    wave = np.arange(10.)[None]
    blaze = np.ones((1, 10))
    blaze[0, 4] = 0
    spectra = Spectra(header=fits.Header(), data=[Spectrum(m=42, spec=np.ones(10), sig=np.ones(10))])
    reduced = BlazeNormalization.run({'star': spectra}, wave, blaze, {42: (-1., 10.)})['star'].data[0]
    np.testing.assert_array_equal(reduced.wave, np.delete(wave[0], 4))
    assert np.isfinite(reduced.spec).all() and np.isfinite(reduced.sig).all()


@pytest.mark.parametrize('suffix', ['.fits', '.fits.gz'])
def test_trace_roundtrip_preserves_physical_orders_and_measured_support(tmp_path, suffix):
    traces = [Trace(m=80, pos=np.array([.01, 50.]), column_range=(1340, 1840)), Trace(m=58, pos=np.array([.02, 1900.]), column_range=(0, 2048))]
    filename = str(tmp_path / f'trace{suffix}')
    TraceWrapper.save(traces, filename)
    loaded = TraceWrapper.load(filename)
    assert [t.m for t in loaded] == [80, 58]
    for original, restored in zip(traces, loaded, strict=True):
        np.testing.assert_array_equal(original.column_range, restored.column_range)
        x = np.arange(*original.column_range)
        np.testing.assert_array_equal(original.y_at_x(x), restored.y_at_x(x))


def test_packaged_wavelength_ranges_match_current_order_sets():
    instrument = ZSHOOTER()
    config = yaml.safe_load((Path(instrument._inst_dir) / 'config.yaml').read_text())
    limits = {'BLUE': (85, 118), 'GREEN': (56, 85), 'RED': (37, 56), 'YJ': (58, 80), 'H': (42, 51), 'K': (31, 38)}
    with np.load(Path(instrument._inst_dir) / 'free_spectral_ranges.npz') as data:
        for channel, wave_ranges in zip(config['channels'], config['wavelength_range'], strict=True):
            first, last = limits[channel]
            np.testing.assert_array_equal(data[f'{channel}_orders'], np.arange(first, last + 1))
            assert data[channel].shape == np.shape(wave_ranges) == (last - first + 1, 2)
            assert np.all(data[channel][:, 1] > data[channel][:, 0])
            wave_ranges = np.array(wave_ranges)
            assert np.all(np.minimum(data[channel][:, 1], wave_ranges[:, 1]) > np.maximum(data[channel][:, 0], wave_ranges[:, 0]))
