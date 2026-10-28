#!/usr/bin/env bash
# Post-build smoke test for r-notebook. Run as:
#   r-notebook/ci/smoke.sh IMAGE_REF
# The checks shared by all notebook images (JupyterHub pin, nbgrader,
# extensions) are in ci/smoke-notebook.sh; only r-notebook's own checks are here.
set -euo pipefail

"$(dirname "$0")/../../ci/smoke-notebook.sh" "${1:?usage: smoke.sh IMAGE_REF}" <<'CHECKS'
# The R kernel must still be registered and start.
jupyter kernelspec list 2>/dev/null | grep -qw ir || fail "IRkernel not registered"
R -q -e 'library(IRkernel)' >/dev/null 2>&1 || fail "IRkernel fails to load"
# npm must be the pinned one, not the older npm bundled with conda nodejs.
( . /etc/runtime-pins.env && [ "$(npm --version)" = "$NPM_VERSION" ] ) \
  || fail "npm is not NPM_VERSION from RUNTIME_PINS.env"
CHECKS
