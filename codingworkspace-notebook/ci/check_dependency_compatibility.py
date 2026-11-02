#!/usr/bin/env python3
"""Exercise real package operations in a disposable, network-disabled notebook."""
import base64
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading


def run(*args, cwd=None, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f'{args!r} failed ({result.returncode})\n{result.stdout}\n{result.stderr}')
    print(result.stdout.strip())
    return result.stdout


def main():
    assert os.getuid() != 0
    run('node', str(Path(__file__).with_name('check_npm_security.cjs')))
    run(sys.executable, '-m', 'pip', 'check')
    conda = json.loads(run('/opt/conda/bin/conda', 'list', '--json'))
    assert any(p['name'] == 'conda' for p in conda)
    with tempfile.TemporaryDirectory(prefix='cw-dependency-compat-') as temp:
        root = Path(temp)
        venv = root / 'venv'
        run(sys.executable, '-m', 'venv', '--copies', str(venv))
        python = str(venv / 'bin/python')
        assert '26.2.1+cw3' in run(python, '-m', 'pip', '--version')
        install = (python, '-m', 'pip', 'install', '--no-index', '--find-links',
                   '/opt/codingworkspace-dependency-wheelhouse')
        run(*install, 'pip==26.2.1', 'Flask==3.1.3', 'openai==2.46.0')
        run(python, '-m', 'pip', 'check')
        run(python, '-m', 'pip', 'uninstall', '--yes', 'certifi')
        run(*install, 'certifi')
        run(python, '-m', 'pip', 'check')
        run(python, '-c', 'import flask,openai,ssl,sqlite3; print("Fresh app imports passed")')
        baked = '/opt/codingworkspace-installed-dependencies/venv/bin/python'
        run(baked, '-m', 'pip', 'check')
        run(baked, '-c', 'import flask,gunicorn,openai; print("Baked app imports passed")')

        package = io.BytesIO()
        with tarfile.open(fileobj=package, mode='w:gz') as tar:
            for name, content in {
                'package/package.json': json.dumps({'name': 'cw-compat-probe', 'version': '1.0.0', 'main': 'index.js'}),
                'package/index.js': 'module.exports = "cw-npm-ok";\n',
            }.items():
                raw = content.encode()
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                member.mode = 0o644
                tar.addfile(member, io.BytesIO(raw))
        archive = package.getvalue()
        requests = []

        class Registry(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(self.path)
                if self.path == '/cw-compat-probe':
                    version = {'name': 'cw-compat-probe', 'version': '1.0.0', 'dist': {
                        'tarball': f'http://127.0.0.1:{self.server.server_port}/probe.tgz',
                        'integrity': 'sha512-' + base64.b64encode(hashlib.sha512(archive).digest()).decode()}}
                    body = json.dumps({'name': 'cw-compat-probe', 'dist-tags': {'latest': '1.0.0'},
                                       'versions': {'1.0.0': version}}).encode()
                elif self.path == '/probe.tgz':
                    body = archive
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Registry) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            project = root / 'npm-project'
            project.mkdir()
            (project / 'package.json').write_text('{"name":"cw-consumer","version":"1.0.0","private":true}')
            env = {**os.environ, 'npm_config_cache': str(root / 'npm-cache'), 'npm_config_userconfig': '/dev/null'}
            try:
                run('npm', 'install', 'cw-compat-probe@1.0.0', '--ignore-scripts', '--no-audit', '--no-fund',
                    '--registry', f'http://127.0.0.1:{server.server_port}', cwd=project, env=env)
                assert 'cw-npm-ok' in run('node', '-e', 'console.log(require("cw-compat-probe"))', cwd=project)
                run('npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund', cwd=project, env=env)
                assert 'cw-npm-ok' in run('node', '-e', 'console.log(require("cw-compat-probe"))', cwd=project)
            finally:
                server.shutdown()
                thread.join(timeout=5)
        assert '/cw-compat-probe' in requests and '/probe.tgz' in requests
        # Exercise glob-backed workspace discovery as well as registry installs.
        workspace = root / 'npm-workspaces'
        child = workspace / 'packages/example'
        child.mkdir(parents=True)
        (workspace / 'package.json').write_text(json.dumps({
            'name': 'cw-workspaces', 'version': '1.0.0', 'private': True,
            'workspaces': ['packages/*']}))
        (child / 'package.json').write_text(json.dumps({
            'name': 'cw-workspace-child', 'version': '1.0.0', 'main': 'index.js'}))
        (child / 'index.js').write_text('module.exports = "cw-workspace-ok";\n')
        for operation in ('install', 'ci'):
            run('npm', operation, '--offline', '--ignore-scripts', '--no-audit', '--no-fund',
                cwd=workspace, env=env)
            run('node', '-e', 'require("node:assert/strict").equal(require("cw-workspace-child"),"cw-workspace-ok")',
                cwd=workspace, env=env)
        packed = json.loads(run('npm', 'pack', '--workspaces', '--json', '--offline', '--ignore-scripts',
                                cwd=workspace, env=env))
        assert len(packed) == 1 and packed[0]['name'] == 'cw-workspace-child'
        assert (workspace / packed[0]['filename']).is_file()
    print('Dependency compatibility passed: base/baked/fresh pip, ensurepip, uninstall/reinstall, conda inventory, npm registry/cache and workspace install/ci/pack.')


if __name__ == '__main__':
    main()
