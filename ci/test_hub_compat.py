#!/usr/bin/env python3
"""Exercise the shell-to-container version boundary without a Docker daemon."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class HubCompatibilityEnvironmentTests(unittest.TestCase):
    def test_pinned_version_reaches_container_without_an_export(self):
        repo = Path(__file__).resolve().parents[1]
        for inherited in (None, 'unexpected-host-value'):
            with self.subTest(inherited=inherited), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'ci').mkdir()
                (root / 'fixture').mkdir()
                (root / 'bin').mkdir()
                shutil.copyfile(repo / 'ci/hub-compat.sh', root / 'ci/hub-compat.sh')
                (root / 'fixture/Dockerfile').write_text('FROM fixture\n')
                (root / 'JUPYTERHUB_PINS.env').write_text('K8S_HUB_IMAGE=fixture/hub\n')
                docker = root / 'bin/docker'
                docker.write_text('''#!/bin/bash
if [[ "$1" == run && "$2" == --rm ]]; then
    echo 5.5.2
elif [[ "$1" == run && "$2" == -d ]]; then
    printf '%s\\n' "$@" > "$FIXTURE_DOCKER_ARGS"
fi
''')
                docker.chmod(0o755)
                checker = root / 'bin/python3'
                checker.write_text('#!/bin/sh\nexit 0\n')
                checker.chmod(0o755)
                env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'],
                           FIXTURE_DOCKER_ARGS=str(root / 'args'))
                env.pop('DOCKERSPAWNER_VERSION', None)
                if inherited is not None:
                    env['DOCKERSPAWNER_VERSION'] = inherited
                result = subprocess.run(['bash', str(root / 'ci/hub-compat.sh'), 'fixture', 'fixture/image'],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = (root / 'args').read_text().splitlines()
                env_args = [args[i+1] for i, arg in enumerate(args[:-1]) if arg == '-e']
                self.assertIn('DOCKERSPAWNER_VERSION=14.0.0', env_args)
                self.assertNotIn('DOCKERSPAWNER_VERSION', env_args)


if __name__ == '__main__':
    unittest.main()
