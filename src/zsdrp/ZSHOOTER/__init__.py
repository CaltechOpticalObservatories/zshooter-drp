"""
Defines instrument class for pyreduce to handle ZShooter specific info. Can be incorporated into pyreduce package later.
"""

import logging
import os
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


