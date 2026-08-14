from copy import deepcopy
import zsdrp.ZSHOOTER as zshooter_package
import yaml
from pathlib import Path
from astropy.io import fits
import matplotlib.pyplot as plt
import numpy as np

from pyreduce.configuration import load_config

def yaml_loader(path: str | Path) -> dict:
    path = Path(path).expanduser().resolve()
    with open(path) as f:
        return yaml.safe_load(f)

def load_settings(path: str | Path, instrument: str) -> dict:
    """
    Adds support for yaml settings files in addition to json.
    Calls pyreduce.configuration.load_config after loading yaml as dict if input is yaml, else calls it directly.
    """
    path = str(path)
    if path.endswith('.yaml') or path.endswith('.yml'):
        cfg = yaml_loader(path)
    elif path.endswith('.json'):
        cfg = path
    else:
        raise ValueError(f'unknown settings file type: {path}')
    return load_config(cfg, instrument=instrument)

def load_zshooter_settings(zshooter_instrument: zshooter_package.ZSHOOTER | None = None) -> dict:
    """
    Adds support for yaml settings files in addition to json.
    Calls pyreduce.configuration.load_config after loading yaml as dict if input is yaml, else calls it directly.
    """
    zs = zshooter_instrument if zshooter_instrument is not None else zshooter_package.ZSHOOTER()

    base = Path(zshooter_package.__file__).resolve().parent / 'settings.yaml'
    if not base.exists():
        raise ValueError(f'settings file does not exist: {base}')
    base_cfg = load_settings(base, instrument='ZSHOOTER')

    cfgs = {}
    for channel in zs.config.channels:
        chan = Path(base).parent / f'settings_{channel}.yaml'
        if not chan.exists():
            raise ValueError(f'requested channel settings file does not exist: {chan}')
        chan_cfg = yaml_loader(chan)
        print(f'Loading settings for channel: {channel}')
        cfg = deepcopy(base_cfg)
        for k, v in chan_cfg.items():
            cfg[k].update(v)
        cfgs[channel] = cfg
    return cfgs

def save_image_to_fits(image, header, filename: str):
    """
    Save an image to a FITS file with the given header.
    """
    outdir = Path(filename).parent
    if not outdir.exists():
        outdir.mkdir(parents=True, exist_ok=True)
    hdul = fits.HDUList([fits.PrimaryHDU(header=header), fits.ImageHDU(data=image, header=header)])
    hdul.writeto(filename, overwrite=True)

def plot_spectra_object(obj, ax=None, title=None, xlabel=None, ylabel=None):
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    orders = [sp.m for sp in obj.data]
    sorted_orders = np.argsort(orders)
    for i in sorted_orders:
        sp = obj.data[i]
        ax.plot(sp.spec / np.nanmax(sp.spec) + 0.3 * i, label=f'order {sp.m}')
    ax.legend(fontsize=8, loc=(1.01, 0.0))
    return ax