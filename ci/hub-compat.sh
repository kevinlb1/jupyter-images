#!/usr/bin/env bash
# Spawn a locally built user image on the JupyterHub version we deploy and
# check they work together:
#   ci/hub-compat.sh IMAGE_NAME IMAGE_REF
# e.g. ci/hub-compat.sh scipy-notebook local/scipy-notebook:candidate
#
# The hub version is read from K8S_HUB_IMAGE in JUPYTERHUB_PINS.env,
# so the test follows the deployed chart. The hub runs from the matching
# quay.io/jupyterhub/jupyterhub image with DockerSpawner, and the image under
# test is started as a user server through the Docker socket. Checks are in
# ci/hub-compat/check_server.py: JupyterLab for the docker-stacks notebook
# images (conda-pinned jupyterhub-singleuser), and the formgrader patch for
# images that install nbgrader_config.py.
set -euo pipefail

IMAGE_NAME="${1:?usage: hub-compat.sh IMAGE_NAME IMAGE_REF}"
IMAGE_REF="${2:?usage: hub-compat.sh IMAGE_NAME IMAGE_REF}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Pinned: the hub container below holds the runner's docker socket.
DOCKERSPAWNER_VERSION=14.0.0

. "$ROOT/JUPYTERHUB_PINS.env"
k8s_hub="${K8S_HUB_IMAGE:?missing in JUPYTERHUB_PINS.env}"
hub_version="$(docker run --rm --entrypoint jupyterhub "$k8s_hub" --version)"
echo "Deployed hub: $k8s_hub -> JupyterHub $hub_version"

args=()
dockerfile="$ROOT/$IMAGE_NAME/Dockerfile"
grep -q 'conda-meta/pinned' "$dockerfile" && args+=(--lab)
grep -qE '^COPY .*nbgrader_config\.py' "$dockerfile" && args+=(--formgrader)

run_id="hubcompat-$$"
network="$run_id"
hub="$run_id-hub"
export TESTER_TOKEN HUB_COMPAT_PORT=18000
TESTER_TOKEN="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"

cleanup() {
  docker ps -aq --filter "network=$network" | xargs -r docker rm -f >/dev/null 2>&1 || true
  docker rm -f "$hub" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$hub" --network "$network" \
  -p "127.0.0.1:$HUB_COMPAT_PORT:8000" \
  -e TESTER_TOKEN -e HUB_COMPAT_NETWORK="$network" -e HUB_COMPAT_HUB_NAME="$hub" \
  -e DOCKERSPAWNER_VERSION="$DOCKERSPAWNER_VERSION" \
  -e HUB_COMPAT_IMAGE="$IMAGE_REF" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$ROOT/ci/hub-compat/jupyterhub_config.py:/srv/jupyterhub/jupyterhub_config.py:ro" \
  "quay.io/jupyterhub/jupyterhub:$hub_version" \
  bash -c 'pip install -q "dockerspawner==$DOCKERSPAWNER_VERSION" && exec jupyterhub -f /srv/jupyterhub/jupyterhub_config.py' \
  >/dev/null

if ! python3 "$ROOT/ci/hub-compat/check_server.py" ${args[@]+"${args[@]}"}; then
  echo "--- hub log (tail) ---"
  docker logs "$hub" 2>&1 | tail -40
  exit 1
fi
echo "OK: $IMAGE_NAME works with JupyterHub $hub_version"
