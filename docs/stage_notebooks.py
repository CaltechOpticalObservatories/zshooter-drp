#!/usr/bin/env python3
"""Stage canonical example notebooks inside the Sphinx source tree."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS_SRC = ROOT / "notebooks"
NOTEBOOKS_DST = ROOT / "docs" / "source" / "notebooks"

IGNORED_NAMES = (
    ".DS_Store",
    ".ipynb_checkpoints",
    "__pycache__",
    "*.pyc",
)


def stage_notebooks(source: Path = NOTEBOOKS_SRC, destination: Path = NOTEBOOKS_DST) -> int:
    """Replace *destination* with a clean copy of the canonical notebook tree."""
    if not source.is_dir():
        raise FileNotFoundError(f"Missing notebook source directory: {source}")

    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    notebook_count = sum(1 for _ in destination.rglob("*.ipynb"))
    if notebook_count == 0:
        raise RuntimeError(f"No notebooks were staged from {source}")
    return notebook_count


def main() -> None:
    count = stage_notebooks()
    print(f"Staged {count} DRP notebook(s) in {NOTEBOOKS_DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
