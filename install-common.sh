#!/bin/bash
# Shared build step for the notebook images. The Dockerfiles COPY this
# script together with the other root-level shared inputs into /tmp/common/
# and run it as NB_UID:
#   PIP_CONSTRAINT=/tmp/common/constraints.txt \
#       bash -x /tmp/common/install-common.sh [--with-nbgrader]
#
# --with-nbgrader also installs nbgrader + ngshare_exchange, the ngshare
# nbgrader_config.py and the formgrader patches. Images that don't pass it
# (e.g. ai100-notebook) are unaffected.
#
# Keep the package lists in the "pip install" + 4-space-continuation format:
# the constraints.txt regeneration recipe extracts them with sed.
set -euo pipefail

COMMON_DIR="$(cd "$(dirname "$0")" && pwd)"

WITH_NBGRADER=0
for arg in "$@"; do
    case "$arg" in
        --with-nbgrader) WITH_NBGRADER=1 ;;
        *) echo "install-common.sh: unknown option: $arg" >&2; exit 2 ;;
    esac
done

echo "Installing common Python packages..."
pip install --no-cache-dir nbgitpuller \
    jupyterlab-lsp \
    jupyterlab-code-formatter \
    jupyterlab-spreadsheet-editor \
    jupyterlab_templates \
    jupyter-resource-usage \
    otter-grader \
    jupytext

if [ "$WITH_NBGRADER" != 1 ]; then
    echo "Installation complete!"
    exit 0
fi

echo "Installing nbgrader + ngshare exchange..."
pip install --no-cache-dir nbgrader \
    ngshare_exchange

# ngshare exchange config; course_id comes from the NBGRADER_COURSE_ID env
# var set per-spawn by the Hub. /etc/jupyter is group-writable (users) in
# the docker-stacks images, so NB_UID can install it.
install -m 0644 "$COMMON_DIR/nbgrader_config.py" /etc/jupyter/nbgrader_config.py

# Hide Manage Students editing / reword Course List; fails the build if a
# patch target no longer matches the installed nbgrader.
python3 "$COMMON_DIR/patch_formgrader.py"

# JupyterLab ships the lockfile it uses to *build* its frontend. Those are
# not runtime dependencies: "JupyterLab is not using any of the Node.js
# packages at runtime" (jupyterlab/jupyterlab#16698, core maintainer, open).
# ECR/Inspector scans it anyway and reports CVEs in build tooling
# (handlebars, tar, minimatch, ...). Empty the lockfile rather than delete
# it: `jupyter lab build` copies it as a template and raises if it's
# missing (jupyterlab/commands.py, _populate_staging). Delete the test
# fixtures; keep staging/package.json, which JupyterLab reads at runtime.
# Only cost: `jupyter lab build` (rare; prebuilt extensions don't need it)
# resolves packages fresh instead of from the lock.
# Scanner hygiene, not a fix: the few lockfile libraries that do ship in the
# compiled bundle (dompurify, vega) stay flagged until a JupyterLab release.
# Here rather than above the nbgrader exit so ai100-notebook (own
# maintainer) is unaffected.
jl="$(python3 -c 'import jupyterlab, os; print(os.path.dirname(jupyterlab.__file__))')"
: > "$jl/staging/yarn.lock"
rm -rf "$jl/tests/mock_packages"

echo "Installation complete!"
