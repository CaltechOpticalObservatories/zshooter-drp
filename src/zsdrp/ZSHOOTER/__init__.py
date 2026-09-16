"""
Defines instrument class for pyreduce to handle ZShooter specific info. Can be incorporated into pyreduce package later.
"""

import logging
import os
import pathlib
import yaml

from pyreduce.instruments.common import Instrument
from pyreduce.instruments.models import InstrumentConfig

logger = logging.getLogger(__name__)

class ZSHOOTER(Instrument):
    def load_info(self):
        """
        Load ZShooter instrument config from the yaml config in this package.
        """
        yaml_name = os.path.join(os.path.dirname(__file__), 'config.yaml')
        if os.path.exists(yaml_name):
            with open(yaml_name) as f:
                info = yaml.safe_load(f)
        else:
            raise FileNotFoundError

        config = InstrumentConfig(**info)
        return config, info

    @staticmethod
    def get_mask_filename(channel, **kwargs):
        mf = f"mask_{channel}*"
        cwd = pathlib.Path(os.path.dirname(__file__)).expanduser().resolve()
        files = cwd.glob(mf, case_sensitive=False)
        return next(files, None)

    @staticmethod
    def detector_shape(channel):
        """
        Return the detector shape for the given channel.
        """
        if channel in ['BLUE', 'GREEN', 'RED']:
            return (4096, 2048)
        elif channel in ['YJ', 'H', 'K']:
            return (2048, 2048)
        else:
            raise ValueError(f"Unknown channel {channel}.")


