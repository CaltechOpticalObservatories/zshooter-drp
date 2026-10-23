"""PyReduce configuration for native ScopeSim X-shooter frames."""

from pathlib import Path
import numpy as np
import yaml
from pyreduce.instruments.common import Instrument
from pyreduce.instruments.models import InstrumentConfig


class XSHOOTER(Instrument):
    def __init__(self):
        super().__init__()
        self._inst_dir = str(Path(__file__).parent)

    def load_info(self):
        with (Path(__file__).parent / 'config.yaml').open() as stream:
            info = yaml.safe_load(stream)
        return InstrumentConfig(**info), info

    def load_fits(self, fname, channel, **kwargs):
        result = super().load_fits(fname, channel, **kwargs)
        header_only = kwargs.get('header_only', False)
        header = result if header_only else result[1]
        header['e_drk'] = header['DARK']
        if header['BUNIT'].lower() not in ('adu', 'electron'):
            raise ValueError('X-shooter reduction requires ADU or accumulated electrons')
        if header['BUNIT'].lower() == 'adu':
            scale = header['GAIN'] * (header['NDIT'] if header['COMBINE'] == 'average' else 1)
            header['e_readn'] = header['RDNOISE'] * np.sqrt(header['NDIT'])
            header['RON'] = header['e_readn']
            header['GAIN'] = header['e_gain'] = 1.0
            header['BUNIT'] = 'electron'
            header['COMBINE'] = 'sum'
            if not header_only:
                result = (result[0] * scale, header)
        return result

    @staticmethod
    def get_mask_filename(channel, **kwargs):
        return None

    @staticmethod
    def detector_shape(channel):
        # Extraction orientation; CCD dispersion is rotated into columns.
        return {'UVB': (2048, 3000), 'VIS': (2048, 4000), 'NIR': (1100, 2048)}[channel]
