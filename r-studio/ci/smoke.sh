#!/usr/bin/env bash
# Post-build smoke test for r-studio. Run as:
#   r-studio/ci/smoke.sh IMAGE_REF
# The expected jupyterhub version comes from JUPYTERHUB_PINS.env (repo root).
set -euo pipefail

IMAGE="${1:?usage: smoke.sh IMAGE_REF}"
. "$(dirname "$0")/../../JUPYTERHUB_PINS.env"

docker run --rm -i -e JUPYTERHUB_VERSION="$JUPYTERHUB_VERSION" --entrypoint bash "$IMAGE" -s <<'INNER'
set -euo pipefail

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# KubeSpawner launches jupyterhub-singleuser as uid 1000 (rstudio).
[ "$(id -u)" = 1000 ] || fail "image runs as uid $(id -u), expected 1000"
hub_version=$(jupyterhub --version 2>/dev/null) || fail "jupyterhub --version failed"
[ "$hub_version" = "$JUPYTERHUB_VERSION" ] \
  || fail "jupyterhub $hub_version, expected $JUPYTERHUB_VERSION (JUPYTERHUB_PINS.env)"
command -v jupyterhub-singleuser >/dev/null || fail "jupyterhub-singleuser not on PATH"

# The proxy that serves RStudio through the single-user server, and the
# server it starts.
python3 -c 'import jupyter_rsession_proxy' 2>/dev/null || fail "jupyter-rsession-proxy fails to import"
command -v rserver >/dev/null || [ -x /usr/lib/rstudio-server/bin/rserver ] || fail "rserver not found"
R -q -e 'library(tidyverse)' >/dev/null 2>&1 || fail "tidyverse fails to load"
# The course packages, from binaries built for this Ubuntu release.
R -q -e 'for (p in c("haven", "survey", "srvyr", "broom", "modelsummary", "marginaleffects",
  "performance", "see", "car", "lmtest", "sandwich", "estimatr", "fixest", "ggeffects",
  "gtsummary", "janitor", "skimr", "corrr")) library(p, character.only = TRUE)' >/dev/null 2>&1 \
  || fail "a course R package fails to load"

echo "OK (jupyterhub $hub_version)"
INNER
