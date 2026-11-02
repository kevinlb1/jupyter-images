#!/usr/bin/env bash
# Read-only registry-image gate. Only disposable fixtures receive namespace access.
set -euo pipefail
image=${1:?published candidate image is required}
prior=${2:?actual prior image is required}
source=${3:?exact candidate source archive is required}
engine_version() {
  docker run --rm --network none --entrypoint /bin/sh "$1" -ceu '
    probe=$(mktemp -d)
    trap '\''rm -rf -- "$probe"'\'' EXIT
    HOME="$probe" XDG_DATA_HOME="$probe/data" XDG_CONFIG_HOME="$probe/config" \
      XDG_CACHE_HOME="$probe/cache" XDG_STATE_HOME="$probe/state" NO_COLOR=1 \
      OPENCODE_DISABLE_MODELS_FETCH=1 OPENCODE_DISABLE_AUTOUPDATE=1 /usr/local/bin/opencode --version
  '
}
version=$(engine_version "$image")
case "$version" in
  'opencode v2.2.2') ;;
  1.18.32) echo 'V1 candidate: V2 installed-runtime gate is not applicable'; exit 0 ;;
  *) echo 'Unsupported candidate OpenCode version' >&2; exit 1 ;;
esac
for path in tests/test_opencode_runtime.py tests/test_opencode_v2.py tests/test_project_tools.py \
            tests/test_durable_group_apps.py tools/coding_quality_benchmark.py; do
  test -f "$source/$path"
done
prior_version=$(engine_version "$prior")
fixture=$(mktemp -d)
container=''
cleanup() {
  if [ -n "$container" ]; then docker rm -f "$container" >/dev/null; fi
  rm -rf -- "$fixture"
}
trap cleanup EXIT
v1_args=()
case "$prior_version" in
  1.18.32)
    container=$(docker create --entrypoint /bin/true "$prior")
    docker cp "$container:/usr/local/bin/opencode" "$fixture/opencode-v1"
    docker rm "$container" >/dev/null
    container=''
    chmod 0755 "$fixture/opencode-v1"
    v1_args=(-v "$fixture/opencode-v1:/usr/local/bin/opencode-v1:ro"
             -e CW_TEST_OPENCODE_V1_BINARY=/usr/local/bin/opencode-v1)
    echo 'Testing retained V1 history migration and unchanged V1 rollback copy'
    ;;
  'opencode v2.2.2') echo 'Prior image already uses V2; V1 migration is not applicable' ;;
  *) echo 'Unsupported prior OpenCode version; review the migration fixture' >&2; exit 1 ;;
esac
# Import only the installed package, with exact-source tests/helpers mounted
# separately. Never mount the source package over the published installation.
# Full TCP and filesystem protection is mandatory; no local-kernel fallback.
docker run --rm --network none --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --entrypoint /opt/conda/bin/python \
  -v "$source/tests:/cw-tests/tests:ro" \
  -v "$source/scripts:/cw-tests/scripts:ro" \
  -v "$source/tools:/cw-tests/tools:ro" \
  -w /cw-tests -e PYTHONPATH=/cw-tests:/cw-tests/tests \
  -e CW_TEST_OPENCODE_BINARY=/usr/local/bin/opencode \
  -e CW_TEST_OPENCODE_ISOLATION_REQUIRED=1 \
  -e CW_TEST_OPENCODE_STARTER_REQUIRED=1 \
  "${v1_args[@]}" "$image" -m unittest tests.test_opencode_runtime tests.test_opencode_v2 \
  tests.test_project_tools tests.test_durable_group_apps -v
