# ZShooter Data Reduction Pipeline

ZShooter's data reduction pipeline provides the instrument-specific layer
between peer-reviewed reduction packages, ZShooter detector and header
conventions, and the WMKO/KOA archive.

The current implementation concentrates on configuring and orchestrating
[PyReduce](https://pyreduce-astro.readthedocs.io/en/latest/) for the six
ZShooter spectrograph channels. It is early-stage software: the interfaces,
calibration recipes, and final data products will evolve with the instrument.

```{toctree}
:maxdepth: 2
:caption: Contents

getting-started
Extraction demo <notebooks/extraction_demo>
```
