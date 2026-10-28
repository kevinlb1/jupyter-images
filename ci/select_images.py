#!/usr/bin/env python3
"""Select the ordinary (non-CodingWorkspace) image directories to build.

Emits the ordinary_images output only, the name the workflows already use.
codingworkspace-* directories are never considered here: the
CodingWorkspace images keep their own selector
(codingworkspace-notebook/ci/select_images.py), outputs and validation,
unchanged. Takes the same --before/--current/--scope arguments as that
selector so a workflow can pass both the same values.

A changed file selects an image when it is inside the image's directory or
when the image's Dockerfile COPY/ADDs it (or a directory containing it).
Editing install-common.sh therefore rebuilds the notebook images that
install it, not r-studio or ngshare-notebook, and a root-level file no
Dockerfile uses (a README, .gitignore) selects nothing.

The build context is the repository root, so COPY sources are repository
paths. COPY --from=... (another stage or a named build context) is not a
repository input and is ignored.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shlex
import subprocess
from pathlib import Path


NULL_SHA = "0" * 40
ROOT = Path(__file__).resolve().parents[1]


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()


def image_directories() -> list[str]:
    return sorted(
        path.parent.name
        for path in ROOT.glob("*/Dockerfile")
        if path.parent.parent == ROOT
        and not path.parent.name.startswith("codingworkspace-")
    )


def dockerfile_instructions(text: str) -> list[str]:
    """Join backslash continuations and drop comments and blank lines."""
    instructions: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if current and line.startswith("#"):
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        instructions.append(current + line)
        current = ""
    if current:
        instructions.append(current)
    return instructions


def copy_sources(dockerfile: Path) -> list[str]:
    """Repository paths an image's Dockerfile COPYs or ADDs."""
    sources: list[str] = []
    for instruction in dockerfile_instructions(dockerfile.read_text()):
        keyword, _, rest = instruction.partition(" ")
        if keyword.upper() not in ("COPY", "ADD"):
            continue
        rest = rest.strip()
        if rest.startswith("["):
            args = json.loads(rest)
        else:
            args = shlex.split(rest)
        flags = [arg for arg in args if arg.startswith("--")]
        if any(flag.startswith("--from=") for flag in flags):
            continue
        paths = [arg for arg in args if not arg.startswith("--")][:-1]
        for path in paths:
            if "://" in path or path.startswith("<<"):
                continue
            sources.append(path.removeprefix("./").rstrip("/") or ".")
    return sources


def uses_file(image: str, sources: list[str], changed: str) -> bool:
    if changed.startswith(f"{image}/"):
        return True
    for source in sources:
        if source == ".":
            return True
        if changed == source or changed.startswith(f"{source}/"):
            return True
        if any(char in source for char in "*?[") and fnmatch.fnmatch(changed, source):
            return True
    return False


def compact_json(value: list[str]) -> str:
    return json.dumps(value, separators=(",", ":"))


def commit_exists(value: str) -> bool:
    if not value or value == NULL_SHA:
        return False
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def changed_files(before: str, current: str) -> list[str]:
    if not commit_exists(current):
        raise SystemExit(f"current revision is not a commit: {current!r}")
    if not commit_exists(before):
        parent = git("rev-parse", "--verify", "--quiet", f"{current}^", check=False)
        before = parent if commit_exists(parent) else ""
    if before:
        output = git("diff", "--name-only", before, current)
    else:
        output = git("ls-tree", "-r", "--name-only", current)
    return [line for line in output.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="")
    parser.add_argument("--current", required=True)
    parser.add_argument(
        "--scope",
        # codingworkspace-notebook is the CodingWorkspace-only dispatch scope;
        # it selects no ordinary images.
        choices=("changed", "codingworkspace-notebook", "all"),
        default="changed",
    )
    parser.add_argument(
        "--format",
        choices=("images", "github-output"),
        default="images",
        help="emit the selected image JSON or the ordinary_images job output",
    )
    args = parser.parse_args()

    images = image_directories()
    files: list[str] = []
    if args.scope == "all":
        selected = images
    elif args.scope == "codingworkspace-notebook":
        selected = []
    else:
        files = changed_files(args.before, args.current)
        sources = {image: copy_sources(ROOT / image / "Dockerfile") for image in images}
        selected = sorted(
            image for image in images
            if any(uses_file(image, sources[image], item) for item in files)
        )

    if args.format == "github-output":
        print(f"ordinary_images={compact_json(selected)}")
    else:
        print(compact_json(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
