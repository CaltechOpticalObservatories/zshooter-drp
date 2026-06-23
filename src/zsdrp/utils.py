import yaml
import importlib

from pyreduce.configuration import load_config
from pyreduce.instruments.common import Instrument

def yaml_loader(path):
    with open(path) as f:
        return yaml.safe_load(f)

def config_loader(path):
    """
    Adds support for yaml configs in addition to json for pyreduce.
    Calls pyreduce.configuration.load_config after loading yaml as dict if input is yaml, else calls it directly.
    """
    if isinstance(path, str):
        if path.endswith('.yaml') or path.endswith('.yml'):
            cfg = yaml_loader(path)
        elif path.endswith('.json'):
            cfg = path
        else:
            raise ValueError(f'unknown config type: {path}')
    else:
        cfg = path

    return load_config(cfg, 'ZSHOOTER')

def zshooter_instrument() -> Instrument:
    """
    Load python instrument module for zshooter.
    Similar to pyreduce.instruments.instrument_info.load_instrument() but without having to put zshooter within
    pyreduce package.
    """
    lib = importlib.import_module(name="ZSHOOTER", package='zsdrp')
    inst = getattr(lib, 'ZSHOOTER')
    return inst()
