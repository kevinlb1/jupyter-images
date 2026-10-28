#!/usr/bin/env bash
# Post-build smoke test for tensorflow-notebook. Run as:
#   tensorflow-notebook/ci/smoke.sh IMAGE_REF
# The checks shared by all notebook images (JupyterHub pin, nbgrader,
# extensions) are in ci/smoke-notebook.sh; only tensorflow-notebook's own checks are here.
set -euo pipefail

"$(dirname "$0")/../../ci/smoke-notebook.sh" "${1:?usage: smoke.sh IMAGE_REF}" <<'CHECKS'
# TensorFlow and the CPU-only PyTorch build must import.
python -c 'import tensorflow, torch, torchvision, torchaudio, cv2, plotly, skorch' 2>/dev/null \
  || fail "ML packages fail to import"
python -c 'import torch, sys; sys.exit(torch.version.cuda is not None)' \
  || fail "torch is a CUDA build, expected CPU-only"
CHECKS
