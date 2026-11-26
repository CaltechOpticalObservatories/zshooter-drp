# ZShooter DRP Design

This is the design for the ZShooter Data Reduction Pipeline (`zsdrp`). It covers the ZSpec echelle spectrograph in
full and the ZImager camera in outline.

The document is split across the pages below. Section numbering is continuous across pages, so a reference such as
"§9.2" in the text always means the same section wherever it appears; the table underneath says which page holds it.

```{toctree}
:maxdepth: 2

01-overview
02-architecture
03-calibration-and-flows
04-runtime
05-products-and-archive
06-deployment
07-zimager
08-verification
09-compliance
10-glossary
```

## Where each section lives

| Sections | Page |
|---|---|
| §1 Purpose, Scope, and References<br>§2 Instrument Summary for the DRP<br>§3 System Context<br>§4 Operating Modes and Entry Points | [Purpose, Instrument, and Operating Modes](01-overview.md) |
| §5 Layer Architecture and Package Layout<br>§6 Canonical Data Model<br>§7 Primitive Inventory | [Architecture, Data Model, and Primitives](02-architecture.md) |
| §8 Calibration Structure<br>§9 Flow Catalog | [Calibration Structure and Flow Catalog](03-calibration-and-flows.md) |
| §10 Caching and Selective Re-execution<br>§11 Configuration<br>§12 Observability, Logging, and QA<br>§13 Failure Handling | [Runtime: Caching, Configuration, Observability](04-runtime.md) |
| §14 Data Products and FITS Conventions<br>§15 KOA / RTI Integration | [Data Products and KOA Integration](05-products-and-archive.md) |
| §16 Deployment, Build, and Resources | [Deployment, Build, and Resources](06-deployment.md) |
| §17 ZImager (Outline) | [ZImager](07-zimager.md) |
| §18 Testing and Verification<br>§19 Documentation Plan | [Testing and Documentation](08-verification.md) |
| §20 ICD Compliance Matrix (including §20.7 Appendix C responses and §20.8 open items) | [ICD Compliance Matrix](09-compliance.md) |
| §21 Glossary | [Glossary](10-glossary.md) |

References written as "Guidelines §N.M" point at the
[DRP Design Guidelines](https://caltechopticalobservatories.github.io/coo-software-architecture/drp_design_guidelines.html),
not at this document.
