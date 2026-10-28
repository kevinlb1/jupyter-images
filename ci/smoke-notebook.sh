#!/usr/bin/env bash
# Shared post-build smoke test for the notebook images (geophysics, julia, r,
# scipy, tensorflow). CI runs each image's own <image>/ci/smoke.sh, which calls
# this with the image ref and pipes in its image-specific checks:
#   ci/smoke-notebook.sh IMAGE_REF <<'CHECKS'
#   python -c 'import something' || fail "something fails to import"
#   CHECKS
# The image-specific checks run inside the container after the JupyterHub
# checks, with fail() available.
#
# The expected singleuser jupyterhub pin and series come from
# JUPYTERHUB_PINS.env (repo root); override with EXPECTED_HUB_PIN and
# EXPECTED_HUB_SERIES.
set -euo pipefail

IMAGE="${1:?usage: smoke-notebook.sh IMAGE_REF < image-checks}"
. "$(dirname "$0")/../JUPYTERHUB_PINS.env"
EXPECTED_HUB_PIN="${EXPECTED_HUB_PIN:-$JUPYTERHUB_VERSION}"
EXPECTED_HUB_SERIES="${EXPECTED_HUB_SERIES:-${EXPECTED_HUB_PIN%.*}}"
IMAGE_CHECKS="$(cat)"

{
cat <<'INNER'
set -euo pipefail

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# Singleuser jupyterhub must stay on the hub's major.minor series, or user
# servers may fail to authenticate with the hub.
hub_version=$(jupyterhub --version 2>/dev/null) || fail "jupyterhub --version failed"
case "$hub_version" in
  "$EXPECTED_HUB_SERIES".*) ;;
  *) fail "jupyterhub $hub_version, expected $EXPECTED_HUB_SERIES.x" ;;
esac
grep -qxF "jupyterhub-singleuser ${EXPECTED_HUB_PIN}" "${CONDA_DIR}/conda-meta/pinned" \
  || fail "jupyterhub-singleuser ${EXPECTED_HUB_PIN} pin missing from conda-meta/pinned"

INNER
printf '%s\n\n' "$IMAGE_CHECKS"
cat <<'INNER'
# nbgrader + ngshare exchange (install-common.sh --with-nbgrader).
# ngshare_exchange reads $USER at import time.
USER="${USER:-jovyan}" python -c 'import nbgrader, ngshare_exchange' 2>/dev/null \
  || fail "nbgrader/ngshare_exchange fail to import"
[ -f /etc/jupyter/nbgrader_config.py ] || fail "nbgrader_config.py missing from /etc/jupyter"
nbgrader_dir=$(python -c 'import importlib.util, os; print(os.path.dirname(importlib.util.find_spec("nbgrader").origin))')
grep -qF 'Use ngshare-course-management CLI instead.' \
  "$nbgrader_dir/server_extensions/formgrader/apihandlers.py" \
  || fail "formgrader PUT /api/student patch missing"

# jupyter-ai and jupyter-server-documents (its transitive extension) must
# never be present in this image.
pip show jupyter-server-documents >/dev/null 2>&1 && fail "jupyter-server-documents present"
pip show jupyter-ai >/dev/null 2>&1 && fail "jupyter-ai present"

# Scanner hygiene from install-common.sh and the Dockerfiles' apt step: an
# emptied JupyterLab build lockfile, no test fixtures, no pebble.
jl=$(python -c 'import jupyterlab, os; print(os.path.dirname(jupyterlab.__file__))')
[ -f "$jl/staging/yarn.lock" ] && [ ! -s "$jl/staging/yarn.lock" ] \
  || fail "JupyterLab staging/yarn.lock missing or not emptied"
[ ! -e "$jl/tests/mock_packages" ] || fail "JupyterLab test fixtures present"
[ ! -e /usr/bin/pebble ] || fail "/usr/bin/pebble present"

# jupyter labextension list marks a broken/incompatible extension with a
# red " X " marker. The color codes wrap the X in ANSI escapes, so strip
# them before matching or the marker never matches literally.
labext_output=$(jupyter labextension list 2>&1) || fail "jupyter labextension list crashed"
clean_labext=$(printf '%s\n' "$labext_output" | sed -E 's/\x1b\[[0-9;]*m//g')
printf '%s\n' "$clean_labext" | grep -qE " X( |$)" && fail "incompatible labextension detected"

server_ext_output=$(jupyter server extension list 2>&1) || fail "jupyter server extension list crashed"
printf '%s\n' "$server_ext_output" | grep -qi "validation failed" && fail "server extension validation failed"

echo "OK (jupyterhub $hub_version)"
INNER
} | docker run --rm -i -e EXPECTED_HUB_SERIES="$EXPECTED_HUB_SERIES" \
  -e EXPECTED_HUB_PIN="$EXPECTED_HUB_PIN" "$IMAGE" bash -s
