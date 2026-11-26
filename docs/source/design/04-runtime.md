# Runtime: Caching, Configuration, Observability

## 10. Caching and Selective Re-execution

Each cacheable task sets a Prefect `cache_key_fn` built from:

- the content fingerprints of array inputs (shape, dtype, moments) and, for `FrameRef`, the file's size, `KOAID`, and
  header checksum. Paths and mtimes are not used.
- every non-array parameter after configuration merging, i.e. the parameters as executed.
- the `zsdrp` version and the selected primitive backend.

Consequences:

- Changing one setting, for example `curvature.peak_threshold` for RED, invalidates `fit_curvature` and its
  descendants for RED only. Re-running `night_flow` then serves bias, flat, and trace from the cache.
- An interrupted run (SIGINT/SIGTERM) resumes with the next invocation by serving completed tasks from the cache
  (`DRP-RUN-017`). Termination is handled by Prefect's cancellation; the CLI registers signal handlers that cancel
  the flow run and return.
- The cache storage path and Prefect profile are per-instance configuration, so two instances on the same server
  never share locks, ports, or cache directories (`DRP-RUN-013`).
- Full-content hashing is used only in differential tests (§18).

This replaces the alpha's `reuse_cals`, which reloads `trace_<CHANNEL>.fits` / `norm_<CHANNEL>.npz` /
`wavecal_<CHANNEL>.npz` by filename inside a broad `try/except`.

## 11. Configuration

- **Layering.** Configuration is applied in order: the PyReduce defaults, then `instrument/settings.yaml`, then
  `instrument/settings_<CHANNEL>.yaml` (the alpha's `load_zshooter_settings` merge), then an optional user YAML, then
  CLI overrides. The installed defaults reduce ZShooter data without modification (`DRP-BLD-005`).
- **Parameters as executed.** Each task logs its fully merged parameter dict at entry, and that dict feeds both the
  cache key and the header provenance. In-code defaults that currently hide configuration move into `settings.yaml`
  or become required:
  - `reject_threshold=6` in `NormflatWrapper`.
  - `wave_delta=20` in `WavecalWrapper`.
  - The `ExtractionParams(osample=10, lambda_sf=1.0, lambda_sp=0.0)` fallbacks in `ScienceWrapper`.
- **Read-only configuration.** Primitives never mutate the config they receive. The alpha's
  `init_step_cfg.pop('atlas')` would raise `KeyError` on a second call with the same dict.
- **Environment.** Environment variables carry only machine configuration: the Prefect API URL, cache root,
  credentials, and the KOA endpoint used by WMKO's hook. All appear with example values in a committed
  `.env.example` (`DRP-BLD-006`, `DRP-BLD-007`). Nothing that changes reduction behaviour is read from the
  environment.
- **Plotting.** Interactive `plot: True` settings apply to notebooks and user mode only. Flows run headless, and their
  QA figures are written as products (§12.2).

## 12. Observability, Logging, and QA

### 12.1 Logging and Monitoring

The Prefect UI shows the DAG with per-task state, parameters, timing, cache-hit status, and per-task logs, for live
runs and past ones (Guidelines §5.6).

Every task writes the entry, exit, and failure fields of Guidelines §6. In addition:

- **Logging configuration.** Logs go to Prefect and also to files under `<log_dir>/<run_id>/<flow>/<task>.log`. The
  log directory defaults to `<output_dir>/logs` and can be set with `--log-dir` (`DRP-RUN-008`). All logs share that
  one parent directory (`DRP-RUN-010`).
- **What is logged.** Every reduction step, decision point (calibration association, epoch fallback, group
  formation), file read, file write, warning, and error. Warnings and errors name the task and the input files
  involved (`DRP-RUN-009`).
- **No `print`.** The alpha's `print(f"... parameters: {params}")` calls are replaced by entry logging.

### 12.2 Exit Statistics and QA Products

This section covers Guidelines §11.4.

| Task | Exit summary statistics | QA product |
|---|---|---|
| `assemble_frame` | Overscan level and sigma per output, saturated fraction | — |
| `ramp_to_slope` (NIR) | Reads used, jump-flagged pixel count, saturated fraction | — |
| `build_master_bias` / `dark` | Median, robust sigma, hot-pixel count | — |
| `build_master_flat` | Median counts per order region, saturated fraction | — |
| `trace_orders` | Orders found vs. expected per channel, median order width, polynomial RMS | Trace overlay PNG |
| `fit_curvature` | Median tilt per order, number of lines used | — |
| `normalize_flat` | Blaze peak per order, fraction of `norm` outside [0.5, 1.5] | Blaze curves PNG |
| `wavelength_solution` | Lines matched, RMS in m/s and pixels, order-number base `obase` | Residuals vs. wavelength PNG |
| `extract_science` | Median S/N per order, masked-pixel fraction, CR count | 2D + 1D overview PNG |
| `blaze_normalize` | Wavelength coverage, gaps | — |
| `sensitivity_function` | Fit RMS, clipped fraction | Sensitivity PNG |
| `splice_channels` | Junction wavelengths, rescale factors | Full-range spectrum PNG |
| Quicklook | Median S/N per channel and per order, frames in the stack, trace source, coverage flags, saturation flag | QL summary PNG for the GUI |

Per-exposure metadata QA (configuration, slit/R, airmass, seeing, non-sidereal rates, from the CDR) is copied from
raw headers into a QA table extension of each lev1/lev2 product.

## 13. Failure Handling

- **Retries** (Guidelines §5.7):
  - I/O tasks (`load_frame`, `write_*`, hook invocation): 3 retries with exponential backoff.
  - Compute tasks: 0 retries.
  - Calibration flows: 3 retries
- **Corrupt or malformed input** (`DRP-RUN-022`). `load_frame` validates the FITS structure and the required header
  keywords. A failure marks that unit failed, records its path and the exception, and lets the rest of the batch
  continue. The frame drops out of its group, and the group reduces with the remaining frames if any are left.
- **Run state.** A run ends in one of three states: `COMPLETED`, `COMPLETED_WITH_FAILURES` (with a per-unit failure
  list in the run artifact), or `FAILED` (flow-level error only). The CLI exit code distinguishes the three.
- **Automatic-mode edge cases.** Bad calibrations, poor conditions, and contamination may legitimately fail a unit
  (ICD Appendix B). The failure is documented and the batch is not failed.
- **Re-running failures.** Re-running only the failed units is just a flow re-submission; successful units are
  served from the cache.
