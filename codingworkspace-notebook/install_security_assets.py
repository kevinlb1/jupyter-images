#!/usr/bin/env python3
"""Install reviewed npm assets by digest, without running package lifecycle hooks."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import urllib.request


def unpack(raw, entry, output):
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('asset digest mismatch: ' + entry['name'])
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        members = archive.getmembers()
        if len(members) > 40000 or sum(m.size for m in members) > 200_000_000:
            raise ValueError('asset exceeds extraction limit')
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or not path.parts or path.parts[0] != 'package'
                    or not (member.isfile() or member.isdir()) or member.name in seen):
                raise ValueError('unsafe asset member: ' + member.name)
            seen.add(member.name)
            target = output.joinpath(*path.parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source:
                    target.write_bytes(source.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    metadata = json.loads((output / 'package.json').read_text())
    if (metadata['name'], metadata['version']) != (entry['name'], entry['version']):
        raise ValueError('asset identity mismatch')


def install(entry, target):
    url = entry['url']
    basename = entry['name'].rsplit('/', 1)[-1]
    expected = f"https://registry.npmjs.org/{entry['name']}/-/{basename}-{entry['version']}.tgz"
    if url != expected or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
        raise ValueError('unreviewed download location or digest')
    with urllib.request.urlopen(url, timeout=90) as response:
        raw = response.read(30_000_001)
    if len(raw) > 30_000_000:
        raise ValueError('asset download exceeds limit')
    # Scoped packages need their image-owned scope directory before staging.
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cw-security-', dir=target.parent) as temp:
        staging = Path(temp) / 'package'
        staging.mkdir()
        unpack(raw, entry, staging)
        if target.is_symlink():
            raise ValueError('asset target is a symlink')
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    print(f"Verified security asset {entry['name']}@{entry['version']} sha256:{entry['sha256']}")


def update_npm_lockfiles(npm, entries):
    """Keep dependency records aligned with the verified replacement packages."""
    for path in (npm / 'npm-shrinkwrap.json', npm / 'package-lock.json'):
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for entry in entries:
            if entry['name'] in ('npm', 'moment'):
                continue
            key = 'node_modules/' + entry['name']
            package = json.loads((npm / key / 'package.json').read_text())
            record = data.setdefault('packages', {}).setdefault(key, {'inBundle': True})
            record.update(version=entry['version'], resolved=entry['url'], integrity=entry['integrity'])
            record.pop('dependencies', None)
            if package.get('dependencies'):
                record['dependencies'] = package['dependencies']
        path.write_text(json.dumps(data, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--npm-only', action='store_true')
    modes.add_argument('--jupyterhub-only', action='store_true')
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    if lock['schemaVersion'] != 1:
        raise ValueError('unsupported asset manifest')
    npm = Path('/usr/local/lib/node_modules/npm')
    allowed = {'npm': npm, 'moment': Path('/opt/conda/share/jupyterhub/static/components/moment')}
    for name in ('brace-expansion', 'ip-address', 'postcss-selector-parser', 'undici',
                 'glob', 'minimatch', 'path-scurry', '@isaacs/nonrecursive-glob-match'):
        allowed[name] = npm / 'node_modules' / name
    entries = lock['packages']
    if len(entries) != len(allowed) or {e['name'] for e in entries} != set(allowed):
        raise ValueError('unexpected asset manifest package set')
    for entry in entries:
        if (entry['name'] == 'moment') == args.jupyterhub_only:
            install(entry, allowed[entry['name']])
    if args.npm_only:
        update_npm_lockfiles(npm, entries)


if __name__ == '__main__':
    main()
