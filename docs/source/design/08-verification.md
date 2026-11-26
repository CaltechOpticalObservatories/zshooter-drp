# Testing and Documentation

## 18. Testing and Verification

| Test | What it establishes | Requirement |
|---|---|---|
| `test_layering.py` | `core/` imports no task, flow, or Prefect module | Guidelines §5.1, §9 |
| Core unit tests | Physical relationships on small synthetic inputs (e.g. splice preserves flux where pieces agree; sensitivity curve recovers a known response) | `DRP-DEV-008` |
| Dual-layer differential tests | Canonical and compiled backends agree within documented tolerance (full-content comparison) | Guidelines §5.9 |
| Flow fixture tests | The calibration, quicklook, and science flows of both arms, plus `flux_and_stitch_flow`, run end to end on a small set simulated by ScopeSim (`zs-scopesim`), comparing wavelength and flux against the simulation truth. Covers at least one VIS and one NIR channel, and a NIR nod sequence | `DRP-DEV-008` (one test per mode) |
| Raw-format tests | eregion assembly and orientation on a raw multi-output frame with overscan (VIS), and a ramp cube to slope (NIR), not only pre-assembled simulations | Guidelines §9 |
| Adapter round-trip test | `DetImage` → PyReduce arrays → `DetImage` preserves data, mask planes, and header | Guidelines §5.5 |
| Corrupt-input test | A batch with one truncated FITS completes as `COMPLETED_WITH_FAILURES` | `DRP-RUN-022` |
| Memory / CPU profiling | No net growth over repeated one-shot runs and over a long `realtime_flow` soak | `DRP-RUN-018`, `DRP-RUN-019` |
| Concurrent-instance test | Two instances with different profiles and cache roots on disjoint inputs | `DRP-RUN-013` |
| QL latency test | Per-channel QL time under a saturated science pool | `DRP-RUN-001` |
| Header test | Every written product carries `DRPVERNO`, `DRPSTATU`, `PROGID`, `KOAID`, and provenance | `DRP-RUN-011/012/020/021` |
| Hook test | `file_write_hook` called once per `final=True` product with correctly formatted arguments | `DRP-KOA-003..006` |

Tests run in GitHub Actions CI. A public test dataset that covers every DRP mode and primary science case (kilonovae,
stellar, white dwarf, exomoons, comets, following the ZShooter science notebooks) will be selected and made available
through KOA no later than ORR (`DRP-DEV-009`). Before first light the fixture set is simulated; on-sky
commissioning data replaces it.

## 19. Documentation Plan

Documentation is built with Sphinx and MyST (`docs/source/`) and hosted on Read the Docs. Docstrings use numpydoc
format. The `DRP-DEV-010` items map to pages as follows:

| Item | Location |
|---|---|
| Requirements | This document §20 |
| Installation | `getting-started` |
| Algorithms and reduction flow | This document §7–§9; per-primitive API docs |
| Command-line interfaces | `cli` page (generated from argparse) |
| Customization | Configuration guide (§11 expanded) |
| Data products | This document §14 |
| Common errors and failure modes | Troubleshooting page, keyed on task names and their exit statistics |
| Cookbooks | Notebooks on the `DRP-DEV-009` dataset (extending `notebooks/extraction_demo.ipynb`) |
| Code comments and docstrings | In source |

A code of conduct (Astropy-style) is linked from the documentation index (ICD Appendix C).
