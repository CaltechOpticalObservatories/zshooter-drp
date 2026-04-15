# Read the Docs – Sphinx Template

A minimal template to spin up documentation quickly.

## Use this template

1. Click **Use this template** on GitHub.
2. Clone your new repo and rename placeholders:

   ```bash
   export PKG=your_project      # snake_case python package directory
   export DIST=your-project     # distribution/project name in pyproject
   rg -l "your_project|your-project|Your Project|Your Name" | \
     xargs sed -i '' \
       -e "s/your_project/${PKG}/g" \
       -e "s/your-project/${DIST}/g" \
       -e "s/Your Project/${DIST}/g" \
       -e "s/Your Name/Your Name Here/g"
   git mv src/your_project src/${PKG}

