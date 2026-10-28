#!/usr/bin/env bash
# Post-build smoke test for geophysics-notebook. Run as:
#   geophysics-notebook/ci/smoke.sh IMAGE_REF
# The checks shared by all notebook images (JupyterHub pin, nbgrader,
# extensions) are in ci/smoke-notebook.sh; only geophysics-notebook's own checks are here.
set -euo pipefail

"$(dirname "$0")/../../ci/smoke-notebook.sh" "${1:?usage: smoke.sh IMAGE_REF}" <<'CHECKS'
# The core scientific stack and the image's own additions must import.
python -c 'import numpy, scipy, pandas, matplotlib, sklearn' 2>/dev/null \
  || fail "core scientific packages fail to import"
python -c 'import simpeg, discretize, empymod, pymatsolver, cvxopt, geoscilabs' 2>/dev/null \
  || fail "geophysics packages fail to import"
# A small mesh and solve, so a broken compiled extension fails here.
python -c '
import discretize, numpy as np, pymatsolver, scipy.sparse as sp
mesh = discretize.TensorMesh([8, 8])
A = mesh.cell_gradient.T @ mesh.cell_gradient + 1e-3 * sp.identity(mesh.n_cells)
x = pymatsolver.Solver(A) * np.ones(mesh.n_cells)
assert np.isfinite(x).all()
' 2>/dev/null || fail "discretize/pymatsolver solve fails"
# Pardiso (mkl + pydiso) is what SimPEG should pick by default.
python -c 'import pydiso, pymatsolver; from simpeg.utils import get_default_solver; assert get_default_solver() is pymatsolver.Pardiso' 2>/dev/null \
  || fail "pymatsolver isn't using Pardiso (mkl/pydiso)"
# deepdish is patched for numpy 2 at build time; round-trip arrays and strings.
python -c '
import deepdish as dd, numpy as np
d = {"a": np.arange(5), "s": "text", "u": np.array(["x", "y"]), "b": np.array([b"x"])}
dd.io.save("/tmp/dd.h5", d)
r = dd.io.load("/tmp/dd.h5")
assert (r["a"] == d["a"]).all() and r["s"] == "text" and list(r["u"]) == ["x", "y"]
' 2>/dev/null || fail "deepdish save/load fails"
CHECKS
