#!/usr/bin/env python3
"""Build pip 26.2.1+cw2 with fixed pure-Python vendored components.

Retain upstream licenses and truthful component SBOMs. Rebuild the wheel RECORD
and wheelhouse checksums before the image's dependency identity is finalized.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import urllib.request
import zipfile

VERSION = '26.2.1+cw2'
WHEEL = f'pip-{VERSION}-py3-none-any.whl'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_wheel(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        if len(infos) != len({i.filename for i in infos}) or sum(i.file_size for i in infos) > 50_000_000:
            raise ValueError('invalid wheel bounds or duplicate files')
        if any(PurePosixPath(i.filename).is_absolute() or '..' in PurePosixPath(i.filename).parts
               or '\\' in i.filename or ((i.external_attr >> 16) & 0o170000) == 0o120000 for i in infos):
            raise ValueError('unsafe wheel member')
        return {i.filename: z.read(i) for i in infos if not i.is_dir()}


def patched_wheel(original, replacements):
    files = read_wheel(original)
    for entry, raw in replacements:
        name = entry['name']
        prefix = 'pip/_vendor/' + name + '/'
        old = [p for p in files if p.startswith(prefix)]
        if not old:
            raise ValueError('vendored package is absent: ' + name)
        for path in old:
            del files[path]
        content = read_wheel(raw)
        # pip deliberately uses msgpack's pure Python fallback; never copy ABI
        # extensions into this platform-independent wheel.
        selected = {p: b for p, b in content.items() if p.startswith(name + '/') and not p.endswith(('.so', '.pyd'))}
        if name + '/__init__.py' not in selected:
            raise ValueError('replacement package is absent')
        for path, data in selected.items():
            files['pip/_vendor/' + path] = data
        for path, data in content.items():
            if '.dist-info/licenses/' in path:
                files[prefix + 'licenses/' + path.split('.dist-info/licenses/', 1)[1]] = data
        vendor = files['pip/_vendor/vendor.txt'].decode()
        vendor, count = re.subn(r'(?m)^(\s*' + name + r'==)[^\n]+', lambda m: m[1] + entry['version'], vendor)
        if count != 1:
            raise ValueError('vendor version declaration missing')
        files['pip/_vendor/vendor.txt'] = vendor.encode()
        bom = json.loads(files['pip/_vendor/bom.cdx.json'])
        component = next(c for c in bom['components'] if c['name'] == name)
        old_ref = component['bom-ref']
        new_ref = f"pkg:pypi/{name}@{entry['version']}"
        component.update(version=entry['version'], purl=new_ref, **{'bom-ref': new_ref})
        files['pip/_vendor/bom.cdx.json'] = (json.dumps(bom, indent=2).replace(old_ref, new_ref) + '\n').encode()
    # This image uses Python 3.13's importlib.metadata backend exclusively.
    # Remove the unused legacy pkg_resources backend, rather than ship a stale
    # setuptools component declaration or suppress its scanner findings.
    files = {p: b for p, b in files.items()
             if not p.startswith('pip/_vendor/pkg_resources/')
             and p != 'pip/_internal/metadata/pkg_resources.py'}
    backend = 'pip/_internal/metadata/__init__.py'
    source = files[backend].decode()
    start = source.index('def _should_use_importlib_metadata() -> bool:')
    end = source.index('\ndef _emit_pkg_resources_deprecation_if_needed()', start)
    source = source[:start] + 'def _should_use_importlib_metadata() -> bool:\n    """The CW Python 3.13 image uses the modern metadata backend only."""\n    return True\n\n' + source[end:]
    files[backend] = source.encode()
    files['pip/_vendor/vendor.txt'] = re.sub(rb'(?m)^setuptools==[^\n]+\n', b'', files['pip/_vendor/vendor.txt'])
    bom = json.loads(files['pip/_vendor/bom.cdx.json'])
    legacy = {c['bom-ref'] for c in bom['components'] if c['name'] == 'setuptools'}
    bom['components'] = [c for c in bom['components'] if c['name'] != 'setuptools']
    bom['dependencies'] = [d for d in bom['dependencies'] if d['ref'] not in legacy]
    for dependency in bom['dependencies']:
        dependency['dependsOn'] = [r for r in dependency.get('dependsOn', []) if r not in legacy]
    files['pip/_vendor/bom.cdx.json'] = (json.dumps(bom, indent=2) + '\n').encode()
    files['pip/__init__.py'] = files['pip/__init__.py'].replace(b'26.2.1', VERSION.encode())
    old_info = 'pip-26.2.1.dist-info/'
    new_info = f'pip-{VERSION}.dist-info/'
    files = {p.replace(old_info, new_info): b for p, b in files.items() if not p.endswith('.dist-info/RECORD')}
    metadata = new_info + 'METADATA'
    files[metadata] = files[metadata].replace(b'Version: 26.2.1\n', ('Version: ' + VERSION + '\n').encode())
    files[metadata] = re.sub(rb'(?m)^Requires-Python: [^\n]+', b'Requires-Python: >=3.13', files[metadata])
    files[new_info + 'CW_SECURITY_PROVENANCE.json'] = (json.dumps({
        'upstreamPipSha256': sha(original), 'version': VERSION,
        'replacements': [entry for entry, _ in replacements],
        'setuptoolsNote': 'Unused pkg_resources backend removed; importlib.metadata is required.'
    }, indent=2) + '\n').encode()
    records = io.StringIO(newline='')
    writer = csv.writer(records, lineterminator='\n')
    for path, data in sorted(files.items()):
        writer.writerow((path, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('='), len(data)))
    writer.writerow((new_info + 'RECORD', '', ''))
    files[new_info + 'RECORD'] = records.getvalue().encode()
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return result.getvalue()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wheelhouse', required=True, type=Path)
    p.add_argument('--lock', type=Path)
    p.add_argument('--ensurepip', type=Path)
    args = p.parse_args()
    wheelhouse = args.wheelhouse
    if args.ensurepip:
        root = args.ensurepip
        for old in (root / '_bundled').glob('pip-*.whl'):
            old.unlink()
        (root / '_bundled' / WHEEL).write_bytes((wheelhouse / WHEEL).read_bytes())
        init = root / '__init__.py'
        source, count = re.subn(r'(?m)^_PIP_VERSION = "[^"]+"', '_PIP_VERSION = "' + VERSION + '"', init.read_text())
        if count != 1:
            raise ValueError('unknown ensurepip version declaration')
        init.write_text(source)
        return
    entries = json.loads(args.lock.read_text())
    if [(e['name'], e['version']) for e in entries] != [('pip', '26.2.1'), ('msgpack', '1.2.3'), ('urllib3', '2.8.0'), ('certifi', '2026.10.19')]:
        raise ValueError('unexpected replacement manifest')
    raw = (wheelhouse / 'pip-26.2.1-py3-none-any.whl').read_bytes()
    if sha(raw) != entries[0]['sha256']:
        raise ValueError('original pip checksum mismatch')
    replacements = []
    for entry in entries[1:]:
        if not entry['url'].startswith('https://files.pythonhosted.org/packages/'):
            raise ValueError('untrusted wheel origin')
        with urllib.request.urlopen(entry['url'], timeout=90) as response:
            data = response.read(20_000_001)
        if len(data) > 20_000_000 or sha(data) != entry['sha256']:
            raise ValueError('replacement wheel checksum mismatch')
        replacements.append((entry, data))
    fixed = patched_wheel(raw, replacements)
    target = wheelhouse / WHEEL
    target.write_bytes(fixed)
    target.chmod(0o444)
    manifest = json.loads((wheelhouse / 'manifest.json').read_text())
    row = next(r for r in manifest['wheels'] if r['filename'] == 'pip-26.2.1-py3-none-any.whl')
    row.update(filename=WHEEL, sha256=sha(fixed), size=len(fixed))
    (wheelhouse / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    (wheelhouse / 'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {r['filename']}\n" for r in manifest['wheels']))
    (wheelhouse / 'pip-26.2.1-py3-none-any.whl').unlink()
    print('Built verified', WHEEL, sha(fixed))


if __name__ == '__main__':
    main()
