# ICD Compliance Matrix

## 20. ICD Compliance Matrix

Status key:

- **D**: designed in this document.
- **P**: pending external approval or decision.
- **IT**: instrument-team or ICS responsibility; the DRP consumes the result.
- **N/A**: does not apply, with the reason given.

### 20.1 Raw Data and Volume

| ID | Summary | How satisfied | § | Status |
|---|---|---|---|---|
| KOA-ICS-001 | FITS standard | All products FITS; validated on write | 14.1 | D |
| KOA-ICS-002 | Primary header approval | DRP scientist co-signs; keyword map in `config.yaml` | 2.2 | IT/P |
| KOA-DATA-001 | `LASTFILE` keyword per detector | ICS keyword; `realtime_flow` can consume it via RTI | 3 | IT |
| KOA-DATA-002 | `PROGNAME` | Read and propagated | 2.2 | IT |
| KOA-DATA-003 | `IMTYPE` | Classification keyword | 2.2 | IT |
| KOA-DATA-004 | KOA instrument keywords | Required-keyword list in `config.yaml` | 2.2 | IT |
| KOA-VOL-001 | Product specification incl. extensions | Product table | 14.1 | D |
| KOA-VOL-002 | Threshold/baseline/optimal labels | Product table | 14.1 | D |
| KOA-VOL-003 | Raw volume per hour/night | Per-frame sizes; totals at PDR | 16.3 | P |
| KOA-VOL-004 | Reduced volume per hour/night | Per-frame sizes; totals at PDR | 16.3 | P |
| KOA-VOL-005 | Update at PDR/PSR/ORR | This document revised at each review | 14.1 | D |

### 20.2 Development

| ID | Summary | How satisfied | § | Status |
|---|---|---|---|---|
| DRP-DEV-001 | SSG-approved framework | Prefect; approval requested before PDR | 1, 16 | P (O-1) |
| DRP-DEV-002 | Python ≥ 3.12 | `requires-python >= 3.12` | 16.1 | D |
| DRP-DEV-003 | Non-Python code approval | PyReduce C/CFFI extraction; optional GPU (ZImager) | 7.1, 17 | P (O-2) |
| DRP-DEV-004 | GitHub | Repository on GitHub | 16.1 | D |
| DRP-DEV-005 | Transfer to WMKO organization | At delivery | 16.1 | D |
| DRP-DEV-006 | Open source after OHR | BSD 3-Clause (relicense from MIT) | 16.1, 20 | P |
| DRP-DEV-007 | PEP 8 | CI lint | 16.1 | D |
| DRP-DEV-008 | Automated tests, scientific validity | Per-mode end-to-end tests against simulation truth | 18 | D |
| DRP-DEV-009 | Public test dataset by ORR | Selected per mode and science case | 18 | D |
| DRP-DEV-010 | Documentation contents | Documentation plan | 19 | D |
| DRP-DEV-011 | Ubuntu 24.04 | CI target | 16.1 | D |
| DRP-DEV-012 | New servers delivered with spare | Only if ZImager compute requires it | 17 | P (O-5) |
| DRP-DEV-013 | Future versions comply | Compliance matrix maintained per release | 21 | D |

### 20.3 Installation and Build

| ID | Summary | How satisfied | § | Status |
|---|---|---|---|---|
| DRP-BLD-001 | Build system approved | setuptools + uv; submitted with O-1 | 16.1 | P |
| DRP-BLD-002 | Databases auto-created | Prefect SQLite created on first run | 16.1 | D |
| DRP-BLD-003 | Default output directories | Created on first invocation | 14.3 | D |
| DRP-BLD-004 | Runs after clone + fetch + build | Static-file fetch on install or first import | 16.1 | D |
| DRP-BLD-005 | No config edits needed | Installed defaults reduce ZShooter data | 11 | D |
| DRP-BLD-006 | No environment-variable pipeline configuration | Backend switch and all parameters via config/CLI | 7.1, 11 | D |
| DRP-BLD-007 | `.env` with examples | `.env.example` committed | 11 | D |
| DRP-BLD-008 | Static files auto-downloaded | Checksummed fetch | 16.1 | D |

### 20.4 Runtime

| ID | Summary | How satisfied | § | Status |
|---|---|---|---|---|
| DRP-RUN-001 | QL < 10 min (goal < 1 min) | Per-arm quicklook flows, box extraction, reserved pool; measured under load | 9.2, 16.2 | D |
| DRP-RUN-002 | Real-time and morning-after processing on one machine do not interfere | Separate work pools and concurrency limits | 16.2 | D |
| DRP-RUN-003 | Input from any location | CLI and flow parameters | 4 | D |
| DRP-RUN-004 | Output to any location | CLI and flow parameters | 14.3 | D |
| DRP-RUN-005 | Multi-input filename `<first>_<type>` | Calibration and stitched naming | 8, 14.1 | D |
| DRP-RUN-006 | Metadata from headers only | `FrameRef` from headers; no filename parsing | 2.2, 8 | D |
| DRP-RUN-007 | File permissions | `0o644`, non-root | 14.3 | D |
| DRP-RUN-008 | Configurable log location | `--log-dir` | 12.1 | D |
| DRP-RUN-009 | Log steps, decisions, I/O, warnings/errors with cause and inputs | Task contract | 12.1 | D |
| DRP-RUN-010 | One log parent directory | `<log_dir>/<run_id>/...` | 12.1 | D |
| DRP-RUN-011 | Processing steps in header or extension | `DRPSTnn`/`DRPPnn`/`PROVENANCE` | 14.2 | D |
| DRP-RUN-012 | `DRPVERNO` SemVer | From package version | 14.2 | D |
| DRP-RUN-013 | Concurrent instances | Per-instance profile, port, and cache root | 10 | D |
| DRP-RUN-014 | One-shot script | `zsdrp-oneshot` | 4 | D |
| DRP-RUN-015 | Real-time script, 24 h | `zsdrp-realtime` (stateless loop) | 9.5 | D |
| DRP-RUN-016 | Reprocessing script | `zsdrp-reprocess` | 4 | D |
| DRP-RUN-017 | Safe termination and resume | Flow cancellation; cache-based resume | 10 | D |
| DRP-RUN-018 | No net memory growth | Recycled process workers; profiling | 16.2, 18 | D |
| DRP-RUN-019 | Steady-state real-time resources | Same | 16.2, 18 | D |
| DRP-RUN-020 | Propagate `PROGID`, `KOAID` | Header writer | 14.2 | D |
| DRP-RUN-021 | `DRPSTATU` | Header writer = `final` | 14.2, 15 | D |
| DRP-RUN-022 | Skip corrupt input gracefully | Unit-level failure isolation | 13 | D |

### 20.5 KOA Interface

| ID | Summary | How satisfied | § | Status |
|---|---|---|---|---|
| DRP-KOA-001 | Archived product list at PSR | Starting proposal in §14.1; quicklook products excluded (§9.2) | 15 | P |
| DRP-KOA-002 | `file_io_hooks.py` present | Shipped stub | 15 | D |
| DRP-KOA-003 | Hook signature | Exact signature | 15 | D |
| DRP-KOA-004 | `final` argument on user-facing writers | All `io.write_*` | 15 | D |
| DRP-KOA-005 | Hook invoked when `final`; ISO-8601 `start_time` | Write task | 15 | D |
| DRP-KOA-006 | `final` identifies complete files | `final` = `DRPSTATU` | 15 | D |

### 20.6 Bulk Reprocessing

| ID | Summary | Status |
|---|---|---|
| DRP-REPRO-001 | Declare intent by CDR | D: ZShooter declares no periodic bulk reprocessing |
| DRP-REPRO-002 | Frequency, storage, cost estimate | N/A: no bulk reprocessing |
| DRP-REPRO-003 | "Data Reprocessing Procedure" document | N/A: no bulk reprocessing |
| DRP-REPRO-004 | "Data Reprocessing Conditions" document | N/A: no bulk reprocessing |
| DRP-REPRO-005 | Review of the above per release | N/A: no bulk reprocessing |
| DRP-REPRO-006 | Public record of reprocessing events | N/A: no bulk reprocessing |

If a later science case requires uniform reprocessing, `DRP-REPRO-002`..`006` apply from that point. The
content-keyed cache and `zsdrp-reprocess` already provide the means.

### 20.7 Appendix C Recommendations

| Recommendation | Response |
|---|---|
| 1. Code of conduct | Adopted (§19) |
| 2. Documentation (Astropy style, numpydoc, Read the Docs) | Adopted (§19) |
| 3. Continuous integration | GitHub Actions (§18) |
| 4. Minimize dependencies | Core stack is numpy, scipy, astropy, matplotlib, numba. **We deviate:** `pyreduce-astro`, `eregion`, `prefect`, `pyyaml`, `tqdm`, and what eregion itself pulls in (`xarray`, `pydantic`, `pandas`, `h5netcdf`, `lacosmic`, `pint`, `joblib`, `uncertainties`). To be reported to the Data Services Lead Scientist (O-3) |
| 5. Re-use existing code | PyReduce, eregion (which holds the generalized HISPEC ramps-to-slopes algorithms), HISPEC extraction work, and PypeIt as primitive sources; contributions back to Astropy/specreduce (CDR) |
| 6. Develop for re-use | Core primitives take arrays and canonical types, and assume no particular FITS layout |
| 7. Clear error messages | Per-task failure fields name the task and its inputs (§12, §13) |
| 8. No hard-coded values | Header keywords, then configuration files, then named constants (§11, §20) |

### 20.8 Open Items and Risks

| ID | Item | Owner | Due |
|---|---|---|---|
| O-1 | SSG approval of Prefect as the reduction framework (`DRP-DEV-001`, `DRP-BLD-001`). Tier 1 status depends on it. If refused, the core and task layers stay as they are and only `flows/` is ported to the Keck DRP Framework | DRP lead + SSG | Before PDR |
| O-2 | SSG approval of PyReduce's C/CFFI extension and any GPU backend (`DRP-DEV-003`). The pure-Python `numpy` backend is the fallback if approval is refused | DRP lead + SSG | PDR |
| O-3 | Dependency deviations (Appendix C #4) | DRP lead | PDR |
| O-4 | Primary header content and the `IMTYPE` / KOA keyword set (`KOA-ICS-002`) | ICS + SA + KOA + DRP | Before ICS delivery |
| O-5 | ZImager data rate vs. WMKO DRP server capacity; any extra hardware and spare (`DRP-DEV-012`) | Instrument team + SSG | PDR |
| O-6 | Per-hour and per-night data volumes (`KOA-VOL-003`/`004`) | Instrument team | PDR |
| O-7 | Measured QL latency per channel against the 10 s budget of `REQ-2-ZS-515`, which is tighter than `DRP-RUN-001` and is the figure this design is built to. The requirement text is not yet in this repository | DRP lead | PSR |
| O-11 | Whether quicklook removes scattered light by default, and whether that is a GUI toggle at all. Decide from the measured round-trip time with and without it, and from whether it changes the observer's decision | DRP lead + science team | PSR |
| O-12 | Whether `line_width` is wanted by the science team. Elemental line annotation has already been dropped | DRP lead + science team | PDR |
| O-8 | Sky-subtraction observing modes per arm (A-B nod, nod-and-shuffle for OH suppression, or neither), which settle the last VIS/NIR DAG difference (§9.0) | Instrument + science teams | PDR |
| O-9 | eregion NIR readiness: the `DetImage3D` container and the generalized HISPEC ramp-to-slope, jump-detection, non-linearity, and reference-pixel algorithms (§6, §7) | DRP lead + COO | PDR |
| O-10 | eregion PyPI release and version pin, which `DRP-BLD-004` and the §16.1 install path both need | DRP lead + COO | Before PDR |
