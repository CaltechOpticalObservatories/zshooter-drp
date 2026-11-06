# ZShooter Data Reduction Pipeline

ZShooter's DRP provides the instrument-specific configuration and glue around
peer-reviewed reduction packages, beginning with PyReduce. It will connect raw
ZShooter data products to observatory metadata and the WMKO/KOA archive.

The project is in active development. Interfaces and reduction recipes are not
yet stable.

## Installation

```bash
pip install .
```

The install provides:

- the `zsdrp` pipeline package containing utilities and helpers around PyReduce;
- the `zsdrp.ZSHOOTER` instrument package containing the instrument class,
  configuration, and settings required by PyReduce.

```python
from zsdrp.ZSHOOTER import ZSHOOTER
from zsdrp import run_reduction
```

## Documentation

The example notebooks remain in [`notebooks/`](notebooks/). Documentation
builds copy them into an ignored staging directory so the same notebooks can
be rendered by this repository and by the ZShooter documentation nexus.

```bash
python docs/stage_notebooks.py
python -m sphinx -W --keep-going -b html docs/source docs/_build/html
```
