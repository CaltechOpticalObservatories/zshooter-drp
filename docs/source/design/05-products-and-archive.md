# Data Products and KOA Integration

## 14. Data Products and FITS Conventions

### 14.1 Product Specification

This table is the `KOA-VOL-001`/`002` specification. It will be revised at PDR, PSR, and ORR (`KOA-VOL-005`). All
products are FITS with standard-conforming headers and extensions (`KOA-ICS-001`).

| Product | Level | Filename | Extensions | Label |
|---|---|---|---|---|
| Raw frame (CCD) / slope image (NIR) | lev0 | Instrument (KOAID) | PRIMARY header; image(s) per amplifier or slope; NIR: slope variance | Threshold |
| Master calibrations (§8) | cal | `<first>_<type>.fits` | PRIMARY; `DATA`; `VARIANCE`; `MASK`; `COUNT`; type-specific table (e.g. `TRACES`, `LINES`) | Baseline |
| Quicklook 1D (co-added stack), saved on request | QL | `<first>_ql.fits` (`DRP-RUN-005`) | PRIMARY; `SPEC` (per-order table: m, pixel, flux, sigma, wave); `QA` | Threshold |
| Processed 2D frame | lev1 | `<KOAID>_2d.fits` | PRIMARY; `DATA`; `VARIANCE`; `MASK`; `WAVE` (2D wavelength map); `BIAS`; `FLAT`; `SCATTER`; `SKY`; `CRMASK`; WCS keywords | Baseline |
| Extracted spectra, per order | lev1 | `<KOAID>_1d.fits` | PRIMARY; `SPEC` (binary table per order: m, pixel, wave, flux, sigma, blaze); `QA` | Threshold |
| Blaze-normalized spliced spectrum, per channel | lev1 | `<KOAID>_<CHANNEL>_norm.fits` | PRIMARY; `SPEC` (wave, flux, sigma, cont) | Baseline |
| Flux-calibrated full-range spectrum | lev2 | `<first>_stitched.fits` | PRIMARY; `SPEC` (wave, flux, sigma); `TELLURIC`; `SENS`; `QA` | Baseline |
| Calibration solutions (wavelength, response, telluric) | cal | §8 | As above | Baseline |
| QA figures and tables | QA | `<KOAID>_<task>_qa.png`, `_qa.fits` | — | Optimal |

Wavelength units are Angstrom. The air/vacuum convention is recorded in `WAVEMED`. Flux units are recorded in `BUNIT`
for every image extension and in `TUNITn` for every table column. Uncertainties are 1-sigma, propagated from the raw
variance (read noise, gain, dark) through every step (ICD Appendix B, `DRP-DEV-008` "scientific validity"). The
`DetImage` `std` plane holds that 1-sigma value, and the writer squares it into the `VARIANCE` extension.

The `MASK` extension holds the combined boolean mask. Its header lists the names of the mask planes that went into
it, so the reason a pixel was rejected is preserved in the archive (§6).

### 14.2 Header Keywords

| Keyword | Content | Requirement |
|---|---|---|
| `DRPVERNO` | `zsdrp` version, SemVer (from package metadata) | `DRP-RUN-012` |
| `DRPSTATU` | `T` if the file is fully reduced for its level, `F` otherwise | `DRP-RUN-021` |
| `PROGID`, `KOAID` | Copied from the first raw input | `DRP-RUN-020` |
| `DRPRUNID` | Prefect flow-run ID | Guidelines §6.4 |
| `DRPSTnn` / `DRPPnn` | Applied step `nn` (ordered) and its key parameters as JSON | `DRP-RUN-011`, Guidelines §5.10 |
| `DRPINnn` | Input frames and calibration products consumed | Guidelines §5.10 |
| `DRPSTART` | ISO-8601 UTC start of reduction of this file | `DRP-KOA-005` |

When the parameter set is too large for header cards, it goes in a dedicated `PROVENANCE` binary-table extension
(one row per step), as `DRP-RUN-011` allows. The pipeline never reads these keywords to decide control flow.

### 14.3 Writing Rules

- **Permissions.** In automatic mode, files are written with mode `0o644` by a non-root service account. They are
  never world-writable or executable (`DRP-RUN-007`).
- **Intermediates.** Intermediate products stay in the result cache. They are serialized to FITS only on request
  (`zsdrp export <run_id> <task>`). The alpha's `.npz` side-effect writes are removed. eregion serializes a
  `DetImage` to netCDF, which is the cache representation of a 2D frame; every archived product is FITS written by
  `zsdrp.io` (`KOA-ICS-001`).
- **Output directories.** Default output and log directories are created on first invocation (`DRP-BLD-003`). Any
  output location can be given at runtime (`DRP-RUN-004`).

## 15. KOA / RTI Integration

`src/zsdrp/file_io_hooks.py` ships with exactly the following content. WMKO overwrites this file at Keck deployments
(`DRP-KOA-002`, `DRP-KOA-003`). Changing its signature or how it is invoked requires SSG approval.

```python
def file_write_hook(koaid: str, filepath: str, start_time: str, final: bool = False, data_level: str = 'lev1'):
    pass
```

- Every writer of a user-facing product (`io.write_ql`, `write_2d`, `write_extracted`, `write_normalized`,
  `write_stitched`, `write_calibration`) takes a `final: bool` argument (`DRP-KOA-004`). `final` equals the
  `DRPSTATU` value written to that file.
- When `final` is `True`, the writer calls `file_write_hook` after the file has been closed on disk, with `koaid`,
  the absolute path, the ISO-8601 UTC `start_time` of that file's reduction, and `data_level` ∈ {`ql`, `lev1`,
  `lev2`, `cal`} (`DRP-KOA-005`, `DRP-KOA-006`).
- The hook is called from the write task, so it runs under the I/O retry policy and its outcome is visible in the DAG.
- The list of archived products for quick-look and science-ready modes will be agreed with the Staff Astronomer and
  KOA scientist and presented at PSR (`DRP-KOA-001`). §14.1 is the starting proposal. Quicklook products are not in
  it: they are written only on observer request (§9.2), and `DRP-KOA-004` scopes the write hook to fully reduced
  science output. Archiving them would be an addition, not a requirement.
