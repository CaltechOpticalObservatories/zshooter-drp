"""Check publication paths without executing the extraction notebook."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("stage_notebooks", Path(__file__).parents[1] / "docs/stage_notebooks.py")
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


class StageNotebookTests(unittest.TestCase):
    def test_report_links_move_and_saved_science_stays_unchanged(self):
        notebook = {
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": ["[Repair](../docs/source/repair.md#checks)\n"]},
                {"cell_type": "code", "metadata": {}, "source": ["path = '../docs/source/example'"], "execution_count": 3, "outputs": [{"output_type": "stream", "name": "stdout", "text": ["saved\n"]}]},
            ],
            "metadata": {"example": "preserve"}, "nbformat": 4, "nbformat_minor": 5,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "notebooks"
            destination = Path(directory) / "docs/source/notebooks"
            source.mkdir()
            destination.mkdir(parents=True)
            (source / "example.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
            (destination / "stale.ipynb").write_text("stale", encoding="utf-8")
            self.assertEqual(staging.stage_notebooks(source, destination), 1)
            staged = json.loads((destination / "example.ipynb").read_text())
            self.assertEqual(staged["cells"][0]["source"], ["[Repair](../repair.md#checks)\n"])
            self.assertEqual(staged["cells"][1], notebook["cells"][1])
            self.assertEqual(staged["metadata"], notebook["metadata"])
            self.assertEqual(json.loads((source / "example.ipynb").read_text()), notebook)
            self.assertFalse((destination / "stale.ipynb").exists())


if __name__ == "__main__":
    unittest.main()
