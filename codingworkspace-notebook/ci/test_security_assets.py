import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('security_assets', Path(__file__).parents[1] / 'install_security_assets.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssetTests(unittest.TestCase):
    def archive(self, name='package/package.json', kind=tarfile.REGTYPE):
        data = json.dumps({'name': 'npm', 'version': '11.21.0'}).encode()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            member.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
            archive.addfile(member, io.BytesIO(data) if member.size else None)
        raw = stream.getvalue()
        return raw, dict(name='npm', version='11.21.0', sha256=hashlib.sha256(raw).hexdigest())

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
