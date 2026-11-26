# Deployment, Build, and Resources

## 16. Deployment, Build, and Resources

### 16.1 Development and Build

- Python ≥ 3.12 (`requires-python = ">=3.12"` already set), with no `__future__` imports (`DRP-DEV-002`).
- Developed on GitHub, then transferred to the `Keck-DataReductionPipelines` organization at delivery
  (`DRP-DEV-004`, `DRP-DEV-005`). Released as open source after OHR under BSD 3-Clause, which is preferred by WMKO
  (`DRP-DEV-006`). The current `pyproject.toml` declares MIT, so the license change is an open item (§20).
- PEP 8 compliance is checked by a linter in CI (`DRP-DEV-007`). No automatic reformatter is used.
- Targets Ubuntu 24.04 LTS, with macOS supported for users (`DRP-DEV-011`).
- Installation: `pip install zsdrp` (PyPI, from the CDR) or `uv sync` from the committed `uv.lock`. Top-level
  dependencies are pinned. The build system (setuptools, uv) is subject to SSG approval (`DRP-BLD-001`). eregion is
  a pinned top-level dependency; its PyPI release is scheduled before PDR, and until then it installs from the COO
  GitHub repository at a pinned revision (§20.8, open item O-10).
- Static files (line atlases, FSR tables, static masks, reference spectra) are fetched by a post-install step that
  checks checksums. WMKO can serve the files (`DRP-BLD-008`). The step runs automatically on first import if it has
  not been run before, so the DRP runs straight after clone and build (`DRP-BLD-004`).
- The Prefect database is SQLite in local mode and is created automatically on first run. No other database is
  needed (`DRP-BLD-002`).

### 16.2 Runtime Footprint on the WMKO DRP Server

The DRP server has 24 cores, about 400 GB RAM, a 32 TB HDD, and a 1 TB NVMe disk (VERIFY ALL). The deployment is one Prefect
server and two work pools:

| Pool | Purpose | Concurrency limit (initial) | Executor |
|---|---|---|---|
| `zs-quicklook` | `quicklook_flow_vis`, `quicklook_flow_nir` | 6 (one per channel) | Single process per run |
| `zs-science` | `cal_flow_vis`/`_nir`, `science_flow_vis`/`_nir`, `flux_and_stitch_flow` | 12 worker processes | Process pool |

The QL pool has reserved capacity and the science pool is capped, so neither mode blocks the other (`DRP-RUN-002`).
QL timing is measured with the science pool full, because `DRP-RUN-001` applies under concurrent load.

Worker processes are recycled after each flow run, and results are written to the cache rather than held in worker
memory. Together these give no net memory growth after one-shot or reprocessing runs (`DRP-RUN-018`) and flat
steady-state use in real-time mode (`DRP-RUN-019`). Profiling in CI checks both (§18). Reduction resources are
released before next-night checkout.

### 16.3 Data Volume

`KOA-VOL-003`/`004` are instrument-team deliverables due at PDR. The DRP contribution is the per-frame size of each
product:

| Frame | Pixels | Size |
|---|---|---|
| CCD raw (16-bit, assumed) | 4096 x 2048 | 16 MiB plus overscan |
| NIR slope (float32) | 2048 x 2048 | 16 MiB, or 32 MiB with variance |
| NIR ramp (`DetImage3D`, float32), held in memory during the fit only | 2048 x 2048 x n_reads | about 512 MiB at 32 reads |
| Processed 2D, CCD (float32 data + variance + wave, 8-bit mask, correction maps) | 4096 x 2048 | about 100–160 MiB depending on the correction maps kept |
| Extracted 1D per channel | n_order x 2048 x 6 columns | < 5 MiB |

Per-hour and per-night totals depend on the exposure and calibration cadence of the observing plan and are TBD at
PDR. Which correction-map extensions are archived (§14.1) is the main control on reduced volume, and is set under
`DRP-KOA-001`.
