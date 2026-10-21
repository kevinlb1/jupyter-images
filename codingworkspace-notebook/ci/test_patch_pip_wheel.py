import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('patchpip', Path(__file__).parents[1] / 'patch_pip_wheel.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def wheel(files):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return raw.getvalue()


class PatchedPipTests(unittest.TestCase):
    def test_rebuilds_records_sbom_and_modern_backend(self):
        components = [dict(name=n, version=v, purl=f'pkg:pypi/{n}@{v}', **{'bom-ref': f'pkg:pypi/{n}@{v}'})
                      for n, v in [('msgpack', '1.1.2'), ('urllib3', '2.7.0'), ('setuptools', '70.3.0'), ('certifi', '2026.6.17')]]
        original = wheel({
            'pip/__init__.py': '__version__ = "26.2.1"',
            'pip/_vendor/__init__.py': '',
            'pip/_vendor/msgpack/__init__.py': 'old',
            'pip/_vendor/certifi/__init__.py': 'old',
            'pip/_vendor/certifi/cacert.pem': 'revoked CA',
            'pip/_vendor/urllib3/__init__.py': 'old',
            'pip/_vendor/pkg_resources/__init__.py': 'legacy',
            'pip/_internal/metadata/pkg_resources.py': 'legacy',
            'pip/_internal/metadata/__init__.py': 'def _should_use_importlib_metadata() -> bool:\n    return False\n\ndef _emit_pkg_resources_deprecation_if_needed():\n    pass\n',
            'pip/_vendor/vendor.txt': 'msgpack==1.1.2\nurllib3==2.7.0\nsetuptools==70.3.0\ncertifi==2026.6.17\n',
            'pip/_vendor/bom.cdx.json': json.dumps({'components': components, 'dependencies': [{'ref': 'pip', 'dependsOn': [c['bom-ref'] for c in components]}]}),
            'pip-26.2.1.dist-info/METADATA': 'Name: pip\nVersion: 26.2.1\nRequires-Python: >=3.9\n',
            'pip-26.2.1.dist-info/RECORD': 'obsolete',
        })
        replacements = [(dict(name=n, version=v), wheel({n + '/__init__.py': 'fixed', n + '/extension.so': 'not-portable', n + '/cacert.pem': 'trusted CA', n + '-' + v + '.dist-info/licenses/LICENSE': 'license text'}))
                        for n, v in [('msgpack', '1.2.3'), ('urllib3', '2.8.0'), ('certifi', '2026.10.19')]]
        certifi_files = m.read_wheel(replacements[-1][1])
        certifi_files['certifi/__init__.py'] = b'from .core import contents'
        certifi_files['certifi/core.py'] = (b'from importlib.resources import files, path, read_text\n'
            b'def contents(): return files("certifi").joinpath("cacert.pem").read_text()\n'
            b'def where(): return files("certifi").joinpath("cacert.pem")\n'
            b'def legacy_path(): return path("certifi", "cacert.pem")\n'
            b'def legacy_text(): return read_text("certifi", "cacert.pem")\n')
        replacements[-1] = (replacements[-1][0], wheel(certifi_files))
        raw = m.patched_wheel(original, replacements)
        self.assertEqual(raw, m.patched_wheel(original, replacements))
        files = m.read_wheel(raw)
        self.assertFalse(any('pkg_resources' in name or name.endswith('.so') for name in files))
        bom = json.loads(files['pip/_vendor/bom.cdx.json'])
        self.assertEqual({c['name']: c['version'] for c in bom['components']}, {'msgpack': '1.2.3', 'urllib3': '2.8.0', 'certifi': '2026.10.19'})
        self.assertNotIn('setuptools', json.dumps(bom))
        self.assertEqual(files['pip/_vendor/certifi/cacert.pem'], b'trusted CA')
        self.assertEqual(files['pip/_vendor/certifi/licenses/LICENSE'], b'license text')
        self.assertIn(b'certifi==2026.10.19', files['pip/_vendor/vendor.txt'])
        self.assertNotIn('2026.6.17', json.dumps(bom))
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / m.WHEEL
            archive.write_bytes(raw)
            probe = subprocess.run([sys.executable, '-I', '-S', '-c',
                'import sys; sys.path.insert(0,sys.argv[1]); from pip._vendor import certifi; print(certifi.contents())',
                str(archive)], check=True, text=True, capture_output=True)
            self.assertEqual(probe.stdout.strip(), 'trusted CA')
        self.assertIn(b'Requires-Python: >=3.13', files['pip-26.2.1+cw3.dist-info/METADATA'])
        for name, digest, size in csv.reader(io.StringIO(files['pip-26.2.1+cw3.dist-info/RECORD'].decode())):
            if digest:
                self.assertEqual(digest, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).decode().rstrip('='))
                self.assertEqual(int(size), len(files[name]))

    def test_rejects_traversal(self):
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            m.read_wheel(wheel({'../escape': 'bad'}))


if __name__ == '__main__':
    unittest.main()
