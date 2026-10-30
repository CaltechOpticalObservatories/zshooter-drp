import numpy as np
import pytest
from scipy.optimize import curve_fit

from zsdrp.steps import slit_line_profile, _slit_line_jacobian


@pytest.mark.parametrize("width,sigma,amplitude", [(4.4, .6, 100.), (1.5, 2.5, 30000.), (12., .8, 7.)])
def test_slit_line_jacobian_matches_profile_derivatives(width, sigma, amplitude):
    x = np.linspace(-20, 20, 161)
    parameters = np.array([amplitude, .3, width, sigma, 2.])
    analytic = _slit_line_jacobian(x, *parameters)
    for i, value in enumerate(parameters):
        step = 1e-5*max(abs(value), 1.)
        above, below = parameters.copy(), parameters.copy()
        above[i] += step
        below[i] -= step
        numerical = (slit_line_profile(x, *above) - slit_line_profile(x, *below))/(2*step)
        np.testing.assert_allclose(analytic[:, i], numerical, rtol=1e-5, atol=1e-7*amplitude)


@pytest.mark.parametrize("amplitude", [10., 100000.])
def test_scaled_fit_recovers_centroid_across_arc_intensities(amplitude):
    x = np.arange(21.)
    expected = [amplitude, 10.3, 3., 1.2, 2.]
    y = slit_line_profile(x, *expected)
    fitted, _ = curve_fit(slit_line_profile, x, y, p0=[amplitude*.8, 10., 4., 1., 1.], bounds=([0, 8, 1, .1, -np.inf], [np.inf, 12, 6, 3, np.inf]), x_scale="jac", jac=_slit_line_jacobian)
    assert fitted[1] == pytest.approx(expected[1], abs=1e-6)
    np.testing.assert_allclose(slit_line_profile(x, *fitted), y, rtol=1e-6)
