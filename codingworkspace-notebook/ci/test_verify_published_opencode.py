"""Exercise release-gate selection and failure propagation without registry access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class PublishedRuntimeTests(unittest.TestCase):
    def run_gate(self, prior='1.18.32', candidate='opencode v2.2.2', failure=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            for name in ('tests/test_opencode_runtime.py', 'tests/test_opencode_v2.py',
                         'tests/test_project_tools.py', 'tests/test_durable_group_apps.py',
                         'tools/coding_quality_benchmark.py'):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            docker = root / 'docker'
            docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if '--version' in args[-1]:
    print(os.environ['CANDIDATE'] if 'candidate' in args else os.environ['PRIOR'])
elif args[0] == 'create':
    print('disposable-container')
elif args[0] == 'cp':
    pathlib.Path(args[-1]).write_text('fixture')
elif '-m' in args:
    sys.exit(int(os.environ['FAILURE']))
''')
            docker.chmod(0o755)
            calls = root / 'calls.jsonl'
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       CALLS=str(calls), CANDIDATE=candidate, PRIOR=prior, FAILURE=str(failure))
            result = subprocess.run(['bash', str(Path(__file__).with_name('verify-published-opencode.sh')),
                'candidate', 'prior', str(source)], env=env, capture_output=True, text=True)
            return result, [json.loads(line) for line in calls.read_text().splitlines()]

    def test_v1_upgrade_uses_actual_prior_binary_and_installed_package(self):
        result, calls = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[:1] == ['cp'] for call in calls))
        run = next(call for call in calls if '-m' in call)
        for required in ('CW_TEST_OPENCODE_ISOLATION_REQUIRED=1',
                         'CW_TEST_OPENCODE_STARTER_REQUIRED=1',
                         'CW_TEST_OPENCODE_V1_BINARY=/usr/local/bin/opencode-v1',
                         'tests.test_project_tools', 'tests.test_opencode_v2'):
            self.assertIn(required, run)
        mounts = [run[i+1] for i, arg in enumerate(run[:run.index('candidate')]) if arg == '-v']
        self.assertTrue(all(mount.endswith(':ro') for mount in mounts))
        self.assertFalse(any('/source:/cw' in mount or '/codingworkspace:' in mount for mount in mounts))
        self.assertNotIn('CW_TEST_OPENCODE_FILESYSTEM_ONLY=1', run)

    def test_v2_prior_does_not_mislabel_it_as_v1(self):
        result, calls = self.run_gate(prior='opencode v2.2.2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[:1] == ['cp'] for call in calls))
        self.assertTrue(any('-m' in call for call in calls))

    def test_unknown_candidate_or_prior_fails_closed(self):
        for kwargs in ({'candidate': 'opencode v2.3.0'}, {'prior': 'unknown'}):
            with self.subTest(kwargs=kwargs):
                result, calls = self.run_gate(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any('-m' in call for call in calls))

    def test_runtime_failure_is_not_swallowed_by_cleanup(self):
        result, calls = self.run_gate(failure=19)
        self.assertEqual(result.returncode, 19, result.stderr)

    def test_legacy_candidate_is_explicitly_not_applicable(self):
        result, calls = self.run_gate(candidate='1.18.32')
        self.assertEqual(result.returncode, 0)
        self.assertIn('not applicable', result.stdout)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
