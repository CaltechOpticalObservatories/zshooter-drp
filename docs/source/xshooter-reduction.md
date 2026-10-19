# Native X-shooter reduction and propagated pixel noise

`run_reduction` accepts the local `zsdrp.XSHOOTER.XSHOOTER` instrument and the configured ScopeSim trace list. Existing calls retain the ZShooter instrument default. The X-shooter path uses measured flat traces, fitted arc curvature, model-assisted vacuum wavelength calibration, native PyReduce optimal extraction, a measured standard response and order/arm stitching.

```python
from zsdrp.XSHOOTER import XSHOOTER

results = run_reduction(files, instrument=XSHOOTER(), trace_list=train['spectral_traces'],
                        lamp_lines=lamp_lines, output_dir=reduced_dir, require_variance=True)
```

`lamp_lines` contains the vacuum `wave` values in Angstrom and the same relative `amplitude` values used to generate the simulated lamp. The configured tabulated X-shooter traces supply detector coverage and physical order identity: UVB 13–24, VIS 16–30 and NIR 11–26. They do not use ZShooter's primary-FSR cuts.

The local instrument reads ScopeSim science data from HDU1. It rotates UVB clockwise and VIS counterclockwise so wavelength increases with extraction column; NIR remains in its native orientation. Wavelength evaluation reverses these rotations before using the original detector WCS. Native ADU are converted to accumulated electrons with the configured gain; averaged NIR outputs additionally multiply by NDIT. Prepared electron frames are already summed and retain their count scale. The dark-current header remains a rate in electrons/second; prepared `RON` describes the combined read-noise standard deviation.

## Variance-aware science inputs

Supply one prepared file per object and arm, with the summed, sky-subtracted signal in HDU1 and its pixel variance in an extension named `VARIANCE`. `BUNIT=electron`, `GAIN=1`, `COMBINE=sum`, `EXPTIME` is the on-source integration, and `SUBTRACTED=True`. Variance is in electron squared and includes source, sky, dark and read terms. A native ADU input is also supported: its variance undergoes exactly the square of the data's conversion and the same pixel rotation.

Combine exposures before extraction using their actual coefficients. Independent sky frames and a reused sky exposure are different measurements: `A1+A2-2B` has variance `VA1+VA2+4VB`. The DRP does not infer those associations from previously subtracted images. `require_variance=True` makes a missing variance extension fail. The original no-variance extraction remains available for existing notebooks, but it uses PyReduce's legacy residual-based uncertainties.

The prepared variance is divided by the square of the normalized flat and passed to the revised PyReduce optimal extraction. Its spectral covariance includes the fitted spatial profile and overlapping swaths. The DRP carries covariance through blaze division, retained order ranges, response/exposure scaling and stitching. FITS outputs retain the sparse covariance; ASCII exports contain its diagonal standard deviation only. The standard reference is supplied in erg/s/cm2/Angstrom. Response-calibrated science products carry this flux-density `BUNIT` and the corresponding squared `COVUNIT`. The standard itself remains an electron/second rate diagnostic and is saved with the `_blazecal` suffix; it is not mislabeled as calibrated flux.

The reported science covariance is conditional on the measured traces, wavelength solution and high-S/N calibration products. Their sampling uncertainty is a separate calibration-realization experiment. Variance-aware stitching cuts between overlapping pieces using the measured response without fitting additional noisy multiplicative offsets. This preserves correlations within each retained piece; source samples from different detector orders are independent under the fixed-calibration calculation.

## Verification

The focused tests cover native detector rotations, summed versus averaged count units, covariance through blaze and response scaling, and retained correlations after order selection. The existing physical-order/FSR tests remain in the suite. An actual 1.5-day BLUE order-100 extraction from the preserved kilonova frames completed with 1,538 valid spectral samples and a non-diagonal propagated covariance. The inherited 30-iteration budget failed to converge for one swath; a 100-iteration budget completed in 1.27 seconds with the original stopping criterion. Both instrument configurations now explicitly allow 100 iterations.

The X-shooter tracing and arc-fitting settings require verification against the companion notebook's full calibration exposures. Passing the instrument/variance tests alone is not evidence that all 43 orders have been extracted successfully.
