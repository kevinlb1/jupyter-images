import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('security_assets', Path(__file__).parents[1] / 'install_security_assets.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssetTests(unittest.TestCase):
    def archive(self, name='package/package.json', kind=tarfile.REGTYPE, package_name='npm'):
        data = json.dumps({'name': package_name, 'version': '11.21.0'}).encode()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            member.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
            archive.addfile(member, io.BytesIO(data) if member.size else None)
        raw = stream.getvalue()
        return raw, dict(name=package_name, version='11.21.0', sha256=hashlib.sha256(raw).hexdigest())

    def test_scoped_asset_uses_official_tarball_and_creates_scope_directory(self):
        name = '@isaacs/nonrecursive-glob-match'
        raw, entry = self.archive(package_name=name)
        entry['url'] = 'https://registry.npmjs.org/@isaacs/nonrecursive-glob-match/-/nonrecursive-glob-match-11.21.0.tgz'
        with tempfile.TemporaryDirectory() as temp, patch.object(module.urllib.request, 'urlopen', return_value=io.BytesIO(raw)) as download:
            target = Path(temp) / 'node_modules' / name
            module.install(entry, target)
            self.assertEqual(json.loads((target / 'package.json').read_text())['name'], name)
            download.assert_called_once_with(entry['url'], timeout=90)

    def test_scoped_asset_rejects_alternate_download_host(self):
        raw, entry = self.archive(package_name='@isaacs/nonrecursive-glob-match')
        entry['url'] = 'https://example.invalid/package.tgz'
        with tempfile.TemporaryDirectory() as temp, patch.object(module.urllib.request, 'urlopen') as download:
            with self.assertRaisesRegex(ValueError, 'unreviewed'):
                module.install(entry, Path(temp) / 'package')
            download.assert_not_called()

    def test_lock_metadata_includes_new_dependency_and_replaces_stale_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            npm = Path(temp)
            entries = []
            for name, dependencies in [('glob', {'minimatch': '^11.0.0'}),
                                       ('@isaacs/nonrecursive-glob-match', {})]:
                package = npm / 'node_modules' / name
                package.mkdir(parents=True)
                (package / 'package.json').write_text(json.dumps({'dependencies': dependencies}))
                entries.append(dict(name=name,version='fixture-version',url='fixture-url',integrity='fixture-integrity'))
            path = npm / 'npm-shrinkwrap.json'
            path.write_text(json.dumps({'packages': {'node_modules/glob': {'dependencies': {'minimatch': '^10.0.0'}}}}))
            module.update_npm_lockfiles(npm, entries)
            packages = json.loads(path.read_text())['packages']
            self.assertEqual(packages['node_modules/glob']['dependencies'], {'minimatch': '^11.0.0'})
            self.assertEqual(packages['node_modules/@isaacs/nonrecursive-glob-match']['version'], 'fixture-version')
            self.assertNotIn('dependencies', packages['node_modules/@isaacs/nonrecursive-glob-match'])

    def test_valid_identity(self):
        raw, entry = self.archive()
        with tempfile.TemporaryDirectory() as temp:
            module.unpack(raw, entry, Path(temp))
            self.assertTrue((Path(temp) / 'package.json').is_file())

    def test_tamper(self):
        raw, entry = self.archive()
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, 'digest'):
            module.unpack(raw + b'x', entry, Path(temp))

    def test_traversal_and_links(self):
        for name, kind in [('package/../../escape', tarfile.REGTYPE), ('/package/x', tarfile.REGTYPE), ('package/link', tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                raw, entry = self.archive(name, kind)
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    module.unpack(raw, entry, Path(temp))

    def test_wrong_identity(self):
        raw, entry = self.archive()
        entry['version'] = '12.0.0'
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, 'identity'):
            module.unpack(raw, entry, Path(temp))


if __name__ == '__main__':
    unittest.main()
