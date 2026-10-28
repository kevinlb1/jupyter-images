#!/usr/bin/env python3
"""Fail if a constraints file would downgrade a package its base image ships.

Run inside a notebook base image, with the repository mounted:
    docker run --rm --entrypoint python -v "$PWD:/repo:ro" <base> \\
        -I /repo/ci/check_constraints.py /repo/constraints.txt

pip installs against PIP_CONSTRAINT replace any already-installed package
the pins disagree with, so a pin older than the base's own (conda-installed)
version silently downgrades it in the built image. Upgrades are reported but
allowed. ALLOW_DOWNGRADE lists the deliberate exceptions; keep it in sync
with ALLOW_MOVE in ci/regen-constraints.sh.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys

try:
    from packaging.version import Version
except ImportError:  # pragma: no cover - pip always vendors packaging
    from pip._vendor.packaging.version import Version

# otter-grader 7 needs wrapt<2 while the docker-stacks bases ship wrapt 2.x.
ALLOW_DOWNGRADE = {"wrapt"}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/repo/constraints.txt"
    installed = {
        norm(d.metadata["Name"]): d.version for d in importlib.metadata.distributions()
    }
    downgrades, upgrades = [], []
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, pinned = (part.strip() for part in line.split("==", 1))
        have = installed.get(norm(name))
        if have is None or Version(have) == Version(pinned):
            continue
        entry = f"{name}: base {have} -> pinned {pinned}"
        if Version(pinned) < Version(have) and norm(name) not in ALLOW_DOWNGRADE:
            downgrades.append(entry)
        else:
            upgrades.append(entry)
    for entry in upgrades:
        print(f"ok   {entry}")
    for entry in downgrades:
        print(f"FAIL {entry}")
    if downgrades:
        print(
            f"{len(downgrades)} base package(s) would be downgraded; "
            "regenerate with ci/regen-constraints.sh notebooks",
            file=sys.stderr,
        )
        return 1
    print(f"no base package downgraded ({len(upgrades)} moved within the allowed rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
