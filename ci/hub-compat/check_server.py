#!/usr/bin/env python3
"""Spawn the image under test on the hub and check it works as a user server.

Run by ci/hub-compat.sh with the hub listening on 127.0.0.1:$HUB_COMPAT_PORT:
    check_server.py [--lab] [--formgrader]

Always: the server starts and registers with the hub, and a hub-issued token
is accepted through the proxy by the single-user server (the hub/singleuser
compatibility that matters). --lab also checks JupyterLab and the kernel
API; --formgrader checks that the patched formgrader refuses
PUT /api/student while an unpatched formgrader API route still answers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HUB = f"http://127.0.0.1:{os.environ.get('HUB_COMPAT_PORT', '8000')}"
TOKEN = os.environ["TESTER_TOKEN"]
USER, SERVER = "compat", "test"


def call(method: str, path: str, body: object = None) -> tuple[int, str]:
    req = urllib.request.Request(
        HUB + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"token {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", action="store_true")
    parser.add_argument("--formgrader", action="store_true")
    args = parser.parse_args()

    for _ in range(60):
        try:
            status, body = call("GET", "/hub/api/")
            if status == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        print("FAIL: hub API never came up")
        return 1
    print("hub:", body)

    call("POST", f"/hub/api/users/{USER}")
    status, body = call("POST", f"/hub/api/users/{USER}/servers/{SERVER}")
    if status not in (201, 202):
        print(f"FAIL: spawn request returned HTTP {status}: {body[:300]}")
        return 1
    for _ in range(150):
        _, body = call("GET", f"/hub/api/users/{USER}")
        server = json.loads(body).get("servers", {}).get(SERVER, {})
        if server.get("ready"):
            break
        time.sleep(2)
    else:
        print("FAIL: server never became ready")
        return 1

    prefix = f"/user/{USER}/{SERVER}"
    checks = [("singleuser API with a hub token", "GET", f"{prefix}/api/status", None, 200)]
    if args.lab:
        checks += [
            ("kernel specs", "GET", f"{prefix}/api/kernelspecs", None, 200),
            ("JupyterLab page", "GET", f"{prefix}/lab", None, 200),
        ]
    if args.formgrader:
        checks += [
            # Unpatched route: proves auth/XSRF let a token PUT through, so
            # the 403 below comes from the patch.
            ("formgrader PUT /api/grade reaches its handler", "PUT",
             f"{prefix}/formgrader/api/grade/no-such-grade", {"score": 1}, 404),
            ("formgrader PUT /api/student refused by the patch", "PUT",
             f"{prefix}/formgrader/api/student/compat-student", {"first_name": "x"}, 403),
        ]
    failed = False
    for label, method, path, body, expected in checks:
        status, _ = call(method, path, body)
        ok = status == expected
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: HTTP {status} (expected {expected})")
    call("DELETE", f"/hub/api/users/{USER}/servers/{SERVER}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
