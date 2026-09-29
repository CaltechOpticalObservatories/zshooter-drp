from copy import deepcopy
import zsdrp.ZSHOOTER as zshooter_package
import yaml
from pathlib import Path
from astropy.io import fits
from astropy.table import Table
import matplotlib.pyplot as plt
import numpy as np

from pyreduce.configuration import load_config
from pyreduce.spectra import Spectra

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
        cfg = deepcopy(base_cfg)
        if chan_cfg is not None:
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

def save_spectra_to_ascii(spectra: Spectra, filename: str):
    """
    Save a Spectra object to an ASCII file.
    """
    outdir = Path(filename).parent
    outdir.mkdir(parents=True, exist_ok=True)
    data = dict()
    header = dict(spectra.header)
    for i, sp in enumerate(spectra.data):
        data['wavelength'] = np.concatenate((data.get('wave', np.array([])), sp.wave))
        data['flux'] = np.concatenate((data.get('spec', np.array([])), sp.spec))
        data['eflux'] = np.concatenate((data.get('sig', np.array([])), sp.sig))
        data['blaze'] = np.concatenate((data.get('cont', np.array([])), sp.cont))
        data['index'] = np.concatenate((data.get('index', np.array([])), [i] * len(sp.wave)))

    table = Table(data, meta=header)
    table.write(filename, format='ascii', overwrite=True, delimiter='\t', comment='# ')

def plot_spectra_object(obj, ax=None, title=None, xlabel=None, ylabel=None):
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    for i, sp in enumerate(obj.data):
        if sp.wave:
            x = sp.wave
        else:
            x = range(len(sp.spec))
        ax.plot(x, sp.spec / np.nanmax(sp.spec) + 0.3 * i, label=f'order {i}')
    ax.legend(fontsize=8, loc=(1.01, 0.0))
    return ax

def make_static_mask(det_shape: tuple, mask_corners: list[tuple], savepath:str=None) -> np.ndarray:
    """
    Create a static mask for a detector image based on the provided corners of the mask polygon.
    :param det_shape: tuple
        The shape of the detector image (height, width).
    :param mask_corners: list of tuples
        The corners of the polygon to be masked, specified as (x, y) coordinates.
    :param savepath: str, optional
        The path to save the mask as a .npz file. If None, the mask will not be saved.
    :return: np.ndarray
        A boolean mask where True indicates unmasked pixels and False indicates masked pixels.
    """
    # mask points inside corners
    from matplotlib.path import Path
    ny, nx = det_shape
    y, x = np.mgrid[0:ny, 0:nx]
    points = np.column_stack((x.ravel(), y.ravel()))
    polygon = Path(mask_corners)
    mask = ~polygon.contains_points(points).reshape(ny, nx)
    if savepath and '.npz' in savepath:
        np.savez(savepath, mask=mask)
    return mask


##################### Misc #########################
from contextlib import contextmanager
from tqdm.auto import tqdm as auto_tqdm
import pyreduce.extract as extract_module

@contextmanager
def patched_extract_tqdm(disable: bool):
    if not disable:
        yield
        return

    old_tqdm = getattr(extract_module, "tqdm", None)
    old_trange = getattr(extract_module, "trange", None)

    def _silent_tqdm(*args, **kwargs):
        kwargs.setdefault("disable", True)
        return auto_tqdm(*args, **kwargs)

    extract_module.tqdm = _silent_tqdm
    if old_trange is not None:
        extract_module.trange = lambda *a, **k: _silent_tqdm(range(*a), **k)
    try:
        yield
    finally:
        if old_tqdm is not None:
            extract_module.tqdm = old_tqdm
        if old_trange is not None:
            extract_module.trange = old_trange
