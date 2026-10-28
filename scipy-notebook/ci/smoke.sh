#!/usr/bin/env bash
# Post-build smoke test for scipy-notebook. Run as:
#   scipy-notebook/ci/smoke.sh IMAGE_REF
# The checks shared by all notebook images (JupyterHub pin, nbgrader,
# extensions) are in ci/smoke-notebook.sh; only scipy-notebook's own checks are here.
set -euo pipefail

"$(dirname "$0")/../../ci/smoke-notebook.sh" "${1:?usage: smoke.sh IMAGE_REF}" <<'CHECKS'
# The core scientific stack and the image's own additions must import.
python -c 'import numpy, scipy, pandas, matplotlib, sklearn' 2>/dev/null \
  || fail "core scientific packages fail to import"
python -c 'import osgeo.gdal, geopandas, altair, weasyprint, pypdf, uncertainties, vl_convert' 2>/dev/null \
  || fail "image packages fail to import"
# Render a PDF, not just import: WeasyPrint needs the Pango system libraries.
python -c '
import io, pypdf, weasyprint
pdf = weasyprint.HTML(string="<h1>smoke</h1><p>test</p>").write_pdf()
assert len(pypdf.PdfReader(io.BytesIO(pdf)).pages) == 1
' 2>/dev/null || fail "WeasyPrint/pypdf can't make and read a PDF"
# npm must be the pinned one, not the older npm bundled with conda nodejs.
( . /etc/runtime-pins.env && [ "$(npm --version)" = "$NPM_VERSION" ] ) \
  || fail "npm is not NPM_VERSION from RUNTIME_PINS.env"
CHECKS
