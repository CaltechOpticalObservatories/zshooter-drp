# ZImager

## 17. ZImager (Outline)

ZImager is a three-channel astrophysical camera. Its reduction is simpler than ZSpec's, but its data rate is much
higher. Run continuously, it could deliver about 135 TiB per night (CDR).

- **Flows.** The same three flows, with `channel` as the parameter. `cal_flow`: master bias/dark, flat, and non-linearity
  calibration. `quicklook_flow`: bias, flat, and a sampled-frame preview. `science_flow`: bias/dark, non-linearity,
  flat, CR rejection, astrometric WCS, and stacking/photometry products.
- **Non-linearity.** A low-light non-linear response correction, of the kind identified for the Lightspeed
  pathfinder, is planned if issues remain in the delivered Hamamatsu sensors. It is an eregion primitive, simple per
  pixel but compute-heavy at ZImager rates. It is a dual-layer primitive: readable NumPy as the canonical version,
  with a GPU backend as the override.
- **I/O.** Streaming blosc2 compression and possibly HDF5 containers for high-rate cubes. The canonical data model
  gains a chunked cube type whose chunks are the fan-out units; because `DetImage` is already backed by named xarray
  planes, that is a chunked form of the same container rather than a second data model. Archived products remain FITS (`KOA-ICS-001`). Any non-FITS intermediate
  stays in the cache.
- **Resources.** 135 TiB/night is far beyond the WMKO DRP server's 32 TB HDD and 1 TB NVMe. Expected operational
  duty cycle, on-the-fly reduction or decimation, and whether ZImager-specific compute or storage must be procured
  with a spare (`DRP-DEV-012`) are to be raised with SSG and settled at PDR (§20.8, open item O-5).
