"""Refresh the packaged wavelength guesses and FSRs from a current simulated arc.

Run in the simulator environment:
python scripts/refresh_wavelength_ranges.py /path/to/arcs_0_BLUE.fits /path/to/reduced
The arc header locates the instrument package. Wavelength guesses are the saved
arc solution at detector columns 0 and nx-1; primary FSRs use edge_wave().
"""
from pathlib import Path
import sys

import numpy as np
import yaml
from astropy.io import fits
from scopesim.effects import EchelleSpectralTraceList
from zsdrp.ZSHOOTER import ZSHOOTER

header = fits.getheader(sys.argv[1], 0)
instrument_dir = Path(header['SIM CONFIG SIM file local_packages_path']) / header['INSTRUME']
effect = next(e for e in yaml.safe_load((instrument_dir / 'ZShooter_SPEC.yaml').read_text())['effects'] if e['name'] == 'trace_list_analytical')
model = EchelleSpectralTraceList(**(effect['kwargs'] | {'filename': str(instrument_dir / effect['kwargs']['filename'])}))
instrument = ZSHOOTER()
config_path = Path(instrument._inst_dir) / 'config.yaml'
config = config_path.read_text().split('wavelength_range:', 1)[0]
rows = ['wavelength_range:']
fsrs = {}
for channel, prefix in zip(instrument.config.channels, model._spectrographs, strict=True):
    spectrograph = model._spectrographs[prefix]
    orders = spectrograph.orders
    fsrs[channel] = spectrograph.edge_wave(fsr=True).to_value('Angstrom')
    fsrs[f'{channel}_orders'] = orders
    rows.append(f'  # {channel}: physical orders {orders[0]}--{orders[-1]}, detector coverage in Angstrom.')
    with np.load(Path(sys.argv[2]) / f'wavecal_{channel}.npz') as calibration:
        wave = dict(zip(calibration['orders'], calibration['wave_img'], strict=True))
    for i, order in enumerate(orders):
        lower, upper = wave[order][[0, -1]]
        lead = '  - - ' if i == 0 else '    - '
        rows.append(f'{lead}[{lower:.5f}, {upper:.5f}]')
    rows.append('')
    print(f'{channel}: {len(orders)} orders, {orders[0]}--{orders[-1]}')
config_path.write_text(config + '\n'.join(rows))
np.savez(Path(instrument._inst_dir) / 'free_spectral_ranges.npz', **fsrs)
