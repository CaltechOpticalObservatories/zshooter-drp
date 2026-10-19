from pathlib import Path
import argparse
import copy
import tempfile
import time

import numpy as np
from astropy.io import fits
from zsdrp.XSHOOTER import XSHOOTER
from zsdrp.steps import TraceWrapper, ScienceWrapper
from zsdrp.utils import load_instrument_settings

parser = argparse.ArgumentParser(description='Independent noise realizations of X-shooter H order 16 using prepared AB source/blank variance and measured calibrations.')
parser.add_argument('data_root', type=Path, help='Faint-mode directory containing prepared/ and blanks/.')
parser.add_argument('calibration_dir', type=Path, help='Directory containing trace_NIR.fits and norm_NIR.npz.')
parser.add_argument('--trials', type=int, default=12)
args = parser.parse_args()
root, cal = args.data_root, args.calibration_dir

with fits.open(root / 'prepared/flat_ab_NIR.fits') as h:
    hdul = fits.HDUList([extension.copy() for extension in h])
    variance = h['VARIANCE'].data.copy()
with fits.open(root / 'blanks/flat_ab_NIR.fits') as h:
    source = variance - 2 * h['VARIANCE'].data
    read_variance = h[1].header['RON']**2
    background = h['VARIANCE'].data - read_variance
assert source.min() > -1e-7 and background.min() > -1e-7
# Subtraction of large variance terms leaves roundoff at zero source/background.
source = np.maximum(source, 0.)
background = np.maximum(background, 0.)
trace = next(t for t in TraceWrapper.load(cal / 'trace_NIR.fits') if t.m == 16)
trace.column_range = (500, 1500)
with np.load(cal / 'norm_NIR.npz', allow_pickle=True) as h:
    norm = h['norm']
settings = load_instrument_settings(XSHOOTER())['NIR']['science']

with tempfile.TemporaryDirectory(prefix='xshooter-noise-') as temporary:
    path = Path(temporary) / 'trial.fits'

    def extract_image(image):
        hdul[1].data = image
        hdul.writeto(path, overwrite=True)
        result = ScienceWrapper.run([path], [copy.deepcopy(trace)], instrument=XSHOOTER(), channel='NIR', norm=norm, step_cfg=settings, require_variance=True, print_params=False)
        return result['FLAT_AB'].data[0]

    truth = extract_image(source)
    # Measure central columns, away from the fitted swath boundaries.
    select = np.arange(650, 1350)
    true_sum = truth.spec[select].sum()
    print('Expected sum:', true_sum, 'read variance:', read_variance, flush=True)
    rng = np.random.default_rng(32189)
    ratios, uncertainties = [], []
    start = time.perf_counter()
    for i in range(args.trials):
        image = rng.poisson(source + background) - rng.poisson(background) + rng.normal(0, np.sqrt(2 * read_variance), source.shape)
        spectrum = extract_image(image)
        ratio = spectrum.spec[select].sum() / true_sum
        uncertainty = np.sqrt(spectrum.covariance[select][:, select].sum()) / true_sum
        ratios.append(ratio)
        uncertainties.append(uncertainty)
        print('Trial:', i, 'ratio:', ratio, 'uncertainty:', uncertainty, flush=True)
    scatter = np.std(ratios, ddof=1)
    print('Mean:', np.mean(ratios), 'scatter:', scatter, 'SEM:', scatter / np.sqrt(len(ratios)), 'reported RMS:', np.sqrt(np.mean(np.square(uncertainties))), 'seconds:', time.perf_counter() - start, flush=True)
