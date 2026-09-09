# Getting started

## Install

Create an isolated Python environment and install the repository in editable
mode while the pipeline is under active development:

```console
python -m pip install -e .
```

The package exposes the ZShooter instrument definition and the pipeline entry
point:

```python
from zsdrp import run_reduction
from zsdrp.ZSHOOTER import ZSHOOTER

instrument = ZSHOOTER()
```

## Explore an extraction

The {doc}`notebooks/extraction_demo` notebook walks through the current
PyReduce-backed extraction steps. Documentation builds render its saved output
without executing it, because the example currently expects simulated FITS
files from a separate checkout.

The notebook remains in the repository's top-level `notebooks/` directory so
it can also serve as an executable development example and, later, as the
target for Binder or Google Colab.
