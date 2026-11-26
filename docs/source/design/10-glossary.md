# Glossary

## 21. Glossary

| Term | Meaning |
|---|---|
| Arm | Group of ZSpec channels that share one DAG: VIS (BLUE, GREEN, RED) or NIR (YJ, H, K) |
| Channel | One ZSpec detector (BLUE, GREEN, RED, YJ, H, K) or ZImager band |
| `DetImage` / `DetImage3D` | eregion's detector-image containers: named xarray planes, per-`Output` regions, named mask planes. The 3D form holds an up-the-ramp read cube |
| `Output` | One amplifier or readout region of a detector, with its own header and mask planes |
| Epoch | Interval of unchanged instrument configuration over which a calibration product is valid |
| FSR | Free spectral range of an echelle order |
| lev0 / lev1 / lev2 | Raw; reduced per exposure (2D, extracted); science-ready (flux-calibrated, stitched) |
| QL | Quicklook |
| RTI | WMKO Real-Time Ingestion |
| SA | WMKO Staff Astronomer |
| SSG | WMKO Scientific Software Group |
| Task / flow | Prefect units matching the Guidelines' task and flow layers |
