import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("../../src"))

project = "ZShooter DRP"
author = "Sharma et. al & Caltech Optical Observatories"
copyright = f"{datetime.now():%Y}, {author}"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "sphinx_design",
    "nbsphinx",
]
autosummary_generate = True
autodoc_typehints = "description"
intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}
nbsphinx_execute = "never"

# The canonical extraction notebook retains legacy Python 2 lexer metadata.
# Keep structural and reference warnings fatal while allowing nbsphinx to
# render those saved code cells with its fallback lexer.
suppress_warnings = ["misc.highlighting_failure"]


templates_path = ["_templates"]
html_static_path = ["_static"]
html_theme = "furo"

# MyST Markdown
myst_enable_extensions = ["colon_fence", "deflist", "linkify"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
