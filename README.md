# ZShooter's Data Reduction Pipeline

This is presently a minimal repository to template out tooling demos and documentation integration. 

ZShooter's DRP errors will integrate with KOA and build on existing literature echelle and imager reduction codes. 

## Installation

```bash
pip install .
```

The install provides
- `zsdrp` pipeline package containing utilities and helpers around PyReduce. 
- `ZSHOOTER` instrument package containing instrument class, config and settings that PyReduce requires.

```python
from ZSHOOTER import ZSHOOTER
from zsdrp import run_reduction
```
