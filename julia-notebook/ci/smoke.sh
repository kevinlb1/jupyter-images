#!/usr/bin/env bash
# Post-build smoke test for julia-notebook. Run as:
#   julia-notebook/ci/smoke.sh IMAGE_REF
# The checks shared by all notebook images (JupyterHub pin, nbgrader,
# extensions) are in ci/smoke-notebook.sh; only julia-notebook's own checks are here.
set -euo pipefail

"$(dirname "$0")/../../ci/smoke-notebook.sh" "${1:?usage: smoke.sh IMAGE_REF}" <<'CHECKS'
# The Julia kernel must still be registered and start.
jupyter kernelspec list 2>/dev/null | grep -q julia || fail "IJulia kernel not registered"
julia -e 'using IJulia' >/dev/null 2>&1 || fail "IJulia fails to load"
CHECKS
