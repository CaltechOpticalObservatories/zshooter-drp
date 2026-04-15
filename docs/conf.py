import os, sys
from datetime import datetime
sys.path.insert(0, os.path.abspath("../src"))

project = "Your Project"
author = "Your Name"
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
]
autosummary_generate = True
autodoc_typehints = "description"
intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}


templates_path = ["_templates"]
html_static_path = ["_static"]
html_theme = "furo"

# MyST Markdown
myst_enable_extensions = ["colon_fence", "deflist", "linkify"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}

# Clean API index if empty (avoids warnings in fresh clones)
if not os.path.exists("api"):
    os.makedirs("api", exist_ok=True)

