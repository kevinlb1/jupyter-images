#!/usr/bin/env python3
"""Keep one visible major-upgrade notice; unchanged runs perform no writes."""
import json
import os
import re
import subprocess

REPOSITORY = 'ubc/jupyter-images'
TITLE = 'OpenCode major upgrade available'
MARKER = '<!-- codingworkspace-opencode-major:'


def gh(*args, body=None):
    result = subprocess.run(['gh', *args, '-R', REPOSITORY], input=body,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Could not reconcile the OpenCode major-upgrade notice')
    return result.stdout


def reconcile(version, run_url, call=gh):
    if version and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid held major version')
    if not re.fullmatch(r'https://github.com/ubc/jupyter-images/actions/runs/[0-9]+', run_url):
        raise ValueError('Invalid workflow evidence URL')
    matches = [row for row in json.loads(call('issue', 'list', '--state', 'open',
        '--search', 'in:title "' + TITLE + '"', '--limit', '100', '--json', 'number,title,body'))
        if row['title'] == TITLE]
    if len(matches) > 1:
        raise ValueError('Duplicate major-upgrade notices need reconciliation')
    existing = matches[0] if matches else None
    if existing and MARKER not in existing['body']:
        raise ValueError('Refusing to replace an unrelated issue with the same title')
    if not version:
        if existing:
            call('issue', 'close', str(existing['number']))
        return
    marker = MARKER + version + ' -->'
    if existing and marker in existing['body']:
        return
    body = (f'{marker}\nOpenCode **{version}** is available but held outside the pinned major.\n\n'
            'Automatic updates continue within the supported major, subject to the 48-hour soak, '
            'artifact hashes and CLI contracts. A major migration needs a reviewed platform '
            'auth/CLI update and the normal image regression before changing the pin.\n\n'
            f'Detected by [the updater]({run_url}). This notice closes when no eligible newer major remains.\n')
    if existing:
        call('issue', 'edit', str(existing['number']), '--body-file', '-', body=body)
    else:
        call('issue', 'create', '--title', TITLE, '--body-file', '-', body=body)


if __name__ == '__main__':
    reconcile(os.environ['HELD_MAJOR_VERSION'], os.environ['RUN_URL'])
