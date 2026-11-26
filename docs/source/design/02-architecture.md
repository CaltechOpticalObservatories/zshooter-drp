# Architecture, Data Model, and Primitives

## 5. Layer Architecture and Package Layout

### 5.1 Target Layout

```text
src/zsdrp/
  core/                    # pure scientific primitives (no prefect import)
    frames.py              # raw assembly, overscan, orientation, ramp -> slope
    calib.py               # bias/dark/flat combination, bad-pixel mask
    trace.py               # order tracing, slit curvature
    flat.py                # normalized flat, blaze, slit function
    wavecal.py             # arc extraction, line ID, 2D wavelength solution
    extract.py             # box and optimal extraction, sky subtraction
    fluxcal.py             # blaze normalization, sensitivity, telluric
    splice.py              # order and channel splicing
    quicklook.py           # GUI-facing helpers (Sec. 4.1)
    qa.py                  # summary statistics and QA figures
    types.py               # canonical frozen records (Sec. 6)
    adapters/
      pyreduce.py          # only module that imports pyreduce types
      scopesim.py          # simulation-truth helpers (Sec. 7.2)
      eregion.py           # for preproc and frame load
  tasks/                   # thin Prefect task wrappers (<~20 lines each)
  flows/                   # per-arm cal/quicklook/science (vis, nir), shared subflows, flux_and_stitch, night, realtime
  instrument/              # current ZSHOOTER/ package: config, settings, atlases, FSR
  io/                      # FITS readers/writers, header provenance, file naming
  file_io_hooks.py         # WMKO-owned KOA hook stub (Sec. 15)
  cli/                     # zsdrp-oneshot, zsdrp-realtime, zsdrp-reprocess
```

`tests/test_layering.py` walks the AST of every module under `core/` and fails if any of them imports `prefect`,
`zsdrp.tasks`, or `zsdrp.flows` (Guidelines §5.1, §9). Neither PyReduce nor eregion depends on Prefect, so both
adapters pass.

### 5.2 Mapping the Alpha `Step` Classes

Each `Step` subclass in `src/zsdrp/steps.py` mixes parameter renaming, the PyReduce call, and file I/O
(`save`/`load`). Each one splits three ways: the science into a core primitive, any library-specific parameter
mapping into an adapter, and the I/O and caching into a thin task. `BiasWrapper.run` becomes `calib.master_bias`
(through the eregion adapter) behind a `build_master_bias` task; `ScienceWrapper.run` becomes
`extract.optimal_extract` and `extract.box_extract` behind one `extract_science` task per object group, with the
grouping by `OBJECT` promoted to its own fan-out task so the number of groups appears in the DAG. The orchestration
in `pipe.run_reduction` and `_reduce_cals` is replaced by the flows of §9, and its
disable-a-step logic becomes DAG composition.

A few behaviours change as part of the split, each because the alpha's version is unsafe once steps are cached and
re-executed independently: `MaskWrapper`'s silent all-zero mask when the file is missing is replaced by recording
the absence explicitly; `CurvatureWrapper`'s in-place edit of `traces` becomes a new `TraceSet`; and
`WavecalWrapper`'s `step_cfg.pop` becomes read-only configuration use. The science code in `splice`, `flux_at`,
`slit_line_profile` and the extraction calls is unchanged; only its call sites move.

## 6. Canonical Data Model

Every value that crosses a task boundary is one of the types below (Guidelines §5.5). The records are frozen
dataclasses, and their arrays are read-only (`arr.flags.writeable = False` at construction). The eregion containers
are not frozen, so a primitive that changes a frame returns a new `DetImage` instead of modifying the one it was
given (Guidelines §5.4).

| Type | Contents | Produced by |
|---|---|---|
| `eregion.datamodels.DetImage` | `data` plane, `std` (1-sigma), and for combined frames `count`, as named planes of an `xarray.Dataset` with dims `(y, x)`; named boolean mask planes and integer label planes; per-`Output` amplifier regions each carrying their FITS header; primary header in `meta` | Raw load, preprocessing, master calibrations, processed 2D frames |
| `eregion.datamodels.DetImage3D` | Up-the-ramp read cube, dims `(y, x, t)`, with the same `Output` regions and `meta`. Consumed by the ramp fit and not archived | Raw load, NIR |
| `ImageBundle` | Ordered `DetImage` collection with its `image_type` table, used wherever a step consumes a stack of frames | `discover_frames`, `group_calibrations` |
| `FrameRef` | Path, `KOAID`, `IMTYPE`, `CHANNEL`, `OBJECT`, `DATE-OBS`, `EXPTIME`, content fingerprint | `discover_frames` |
| `CalibrationSet` | Channel, epoch ID, and refs to master bias, dark, flat, `TraceSet`, `NormFlat`, `WaveSolution` | `cal_flow_vis` / `cal_flow_nir` |
| `TraceSet` | Per-order centre polynomials, column ranges, extraction heights, slit curvature coefficients, order numbers `m` | `trace_orders`, `fit_curvature` |
| `NormFlat` | `norm` (2D), `blaze` (n_order x n_col), `slitfunc` per order, extraction metadata | `normalize_flat` |
| `WaveSolution` | `wave` (n_order x n_col, Angstrom, air/vacuum flag), 2D polynomial coefficients, matched line table, RMS (m/s), line count | `wavelength_solution` |
| `ExtractedSpectra` | Per-order `spec`, `sig`, `wave` (optional), `cont`, `m`; header; extraction parameters | `extract_science` and later steps |
| `SensitivityCurve` | Chebyshev coefficients, wavelength domain, reference-star ID | `sensitivity_function` |

- Uncertainty is the `std` plane and is 1-sigma, matching §14.1. The `VARIANCE` extension of §14.1 is written as
  `std**2`, so the archived product specification is unchanged.
- The pixel planes carry no unit. Flux units are kept in `meta` and written to `BUNIT` (§14.1). 
- Masking is a set of named boolean planes OR-ed into a combined mask, not a single bit-flag DQ word. Each masking
  step contributes its own plane, so the product records why a pixel was masked (§14.1).
- `DetImage` is two-dimensional. The NIR ramp is a `DetImage3D`, which only the ramp-to-slope primitive consumes.
  Every step after it sees a `DetImage`, so the two arms share one container from the slope image onward.

`src/zsdrp/core/adapters/pyreduce.py` converts between these types and the PyReduce-native ones (`Trace`, `Spectra`,
`Spectrum`, `ExtractionParams`, the `Instrument` subclass, and header dicts). No PyReduce type appears in a task
signature. Where PyReduce mutates its inputs (`Trace.slit`, `Trace.wave`, `Trace.m`), the adapter deep-copies before
the call and builds a new record afterwards (Guidelines §5.4). PyReduce's primitives take a bare array and a header
dict, so the adapter passes `DetImage` planes straight through. `src/zsdrp/core/adapters/eregion.py` is the only
module that constructs eregion types.

Guidelines §5.5 forbids an external library's native type in a task signature, and `DetImage` does appear in them.
This is a deliberate deviation: eregion is adopted as the data model, in the role the Guidelines reserve for "a
standard container carrying data, uncertainty, mask, and header". The rule still
applies to algorithm-library types such as PyReduce's `Trace` and `Spectra`. The cost is that eregion becomes a
pinned dependency rather than an interchangeable primitive source, which is why it is recorded in §20.7 and in open
items O-9 and O-10.

## 7. Primitive Inventory

This section covers Guidelines §11.1. The first table lists ZSpec primitives.

| Primitive                    | Source                                                               | Types in → out                                                           | Dual-layer | Notes                                                                                                                                                                                                                         |
|------------------------------|----------------------------------------------------------------------|--------------------------------------------------------------------------|---|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Raw assembly and orientation | eregion                                                              | raw HDUList → `DetImage`/`DetImage3D`                                    | No | Per-`Output` assembly and pre/overscan subtraction from the eregion detector configuration; per-output gain and read noise from the header. Rotation into PyReduce orientation (`config.yaml: orientation`) stays in `zsdrp`. |
| NIR ramp → slope             | eregion (generalized HISPEC ramps-to-slopes)                         | `DetImage3D` → `DetImage` (`data` + `std`)                               | Candidate | Ramps are not archived (CDR). In development in eregion (O-9).                                                                                                                                                                |
| Master bias                  | eregion                                                              | `ImageBundle` → `DetImage`                                               | No | CCD channels. Produces `data`, `std`, and `count` planes.                                                                                                                                                                     |
| Master dark                  | eregion                                                              | `ImageBundle` → `DetImage`                                               | No | NIR channels, scaled by `EXPTIME`.                                                                                                                                                                                            |
| Bad-pixel, cosmic-ray mask   | Instrument static + eregion masking (astropy sigma-clip, L.A.Cosmic) | `DetImage` → named mask planes                                           | No | Static (vignette) plus hot/dead pixels from darks and flats, each contributed as its own named plane.                                                                                                                         |
| Master flat                  | eregion                                                              | `ImageBundle`, bias → `DetImage`                                         | No | Bias scaled by exposure time. The same combination builds the master arc.                                                                                                                                                     |
| Order tracing                | PyReduce `trace.trace`                                               | flat `DetImage` → `TraceSet`                                             | No | The optional `order_centers` seed comes from instrument data.                                                                                                                                                                 |
| Slit curvature               | PyReduce `slit_curve.Curvature`                                      | arc `DetImage`, `TraceSet` → `TraceSet`                                  | No |                                                                                                                                                                                                                               |
| Scattered light              | PyReduce `estimate_background_scatter`                               | `DetImage`, `TraceSet` → background model                                | No | PyReduce implementation untested.                                                                                                                                                                                             |
| Normalized flat, blaze       | PyReduce `extract_normalize`                                         | flat, `TraceSet` → `NormFlat`                                            | Yes (PyReduce `numpy` / `c` slit decomposition) | Gain, read noise, and dark come from the master-flat header.                                                                                                                                                                  |
| Wavelength solution          | PyReduce `WavelengthCalibrationInitialize` + `WavelengthCalibration` | arc, `TraceSet` → `WaveSolution`                                         | No | Finalize arclamps first.                                                                                                                                                                                                      |
| Science extraction           | PyReduce `extract` (optimal or box car)                              | `DetImage`, `TraceSet`, `NormFlat` → `ExtractedSpectra`                  | Yes (optimal) | Optimal extraction for Science, box extraction for Quicklook.                                                                                                                                                                 |
| Sky subtraction, nod         | Nod A-B difference (`SUBTRACTED` header)                             | `DetImage` pair → `DetImage`                                             | No | NIR arm, for OH suppression.                                                                                                                                                                                                  |
| Sky subtraction, empirical   | Kelson-style sky spectrum extraction (new)                           | `DetImage`, `TraceSet` → subtracted data                                 | No | VIS arm, and any non-nodded data.                                                                                                                                                                                             |
| Blaze normalization          | New (`BlazeNormalization`)                                           | `ExtractedSpectra`, `WaveSolution`, `NormFlat`, FSR → `ExtractedSpectra` | No | Trims each order to its free spectral range, removes blaze                                                                                                                                           |
| Sensitivity function         | New (`SensitivityFunction`)                                          | standard `ExtractedSpectra`, reference spectrum → `SensitivityCurve`     | No | log10 ratio, median filter, sigma-clipped Chebyshev degree 6.                                                                                                                                                                 |
| Telluric correction          | Model fitting (e.g. molecfit-class) or telluric-standard division    | `ExtractedSpectra` → `ExtractedSpectra`                                  | No | Not in the alpha.                                                                                                                                                                               |
| Order / channel splice       | New (`splice`)                                                       | `ExtractedSpectra` → `ExtractedSpectra`                                  | No | Junction placed where the kept inverse variance per unit wavelength is highest. Optional S/N-anchored rescale.                                                                                                                |
| QA metrics                   | New (`core.qa`)                                                      | any record → `dict` + figure                                             | No | §12.2.                                                                                                                                                                                                                        |

### 7.1 Dual-Layer Primitives

PyReduce puts its slit decomposition behind one call site in `pyreduce.extract`. `zsdrp` supports two of its
backends:

- `numpy`: a pure-Python port. `zsdrp` treats this as the canonical implementation.
- `c`: the vendored CFFI extension, PyReduce's default. `zsdrp` treats this as the compiled override
  (Guidelines §5.9).

Differential tests run both on the same fixture frames (§18). PyReduce's other backends are optional extras of
`pyreduce-astro`, and `zsdrp` does not offer them: they add no capability `numpy` and `c` lack, and each would add a
dependency.

PyReduce reads its backend from the `PYREDUCE_EXTRACTION` environment variable. `DRP-BLD-006` forbids configuring
pipeline operation through the environment, so in `zsdrp` the backend is a configuration and CLI option
(`extraction_backend`, `--backend numpy`), which accepts `numpy` or `c`. `core/adapters/pyreduce.py` applies it to the
PyReduce call in-process. Users never set the variable, and the chosen backend is part of every extraction task's
parameters and cache key. It takes the place of the environment override the Guidelines describe.

Use of compiled code needs SSG approval under `DRP-DEV-003` (§20.8, open item O-2).

### 7.2 Simulation-Only Primitives

`simple_wavesol` in `src/zsdrp/steps.py` builds the wavelength image from the ScopeSim analytical trace list that
generated the frame. It reads `SIM CONFIG SIM file local_packages_path` and the `D` WCS from the header, then applies
an arc-line correction. It is a ground-truth tool for DRP development and for checking the PyReduce solution against
the simulator. It moves to `core/adapters/scopesim.py` and is never used on sky data. The production wavelength path
is `WavecalWrapper` → `wavecal.solve`.
