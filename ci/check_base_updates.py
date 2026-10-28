#!/usr/bin/env python3
"""Find newer base images for the ordinary images.

Watches every ordinary image (the same set as ci/select_images.py: not
codingworkspace-*) whose Dockerfile pins its base by digest as
    ARG BASE_CONTAINER=<image>:<tag>@sha256:<digest>
on quay.io or Docker Hub. Images without a digest pin (e.g. ai100-notebook)
are not watched. Two tag styles are understood:

- version tags, "X.Y.Z" or "hub-X.Y.Z" (docker-stacks hub-6.1.1,
  rocker/tidyverse 4.6.1): moves to the newest tag with the
  same prefix and major version;
- series tags, "X.Y-<variant>" (python 3.12-slim-bookworm): the tag moves
  with patch releases, so it stays and only its digest is refreshed.

Either way a new digest behind the pinned tag counts as an update. A newer
major version, or a newer minor for a series tag (python 3.13), is listed
in the summary but never applied: those need a deliberate upgrade.

    ci/check_base_updates.py [--apply] [--image NAME ...] [--summary FILE]
                             [--major-report FILE] [--format text|github-output]

--apply rewrites the BASE_CONTAINER lines. --major-report writes the manual
upgrade steps for the held-back releases (empty file when there are none).
github-output prints images=<JSON list of updated images> and
held=<JSON list of images with a held-back release> for the workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Both registries list tags newest first; a new release is always within the
# first pages.
MAX_PAGES = 10

PIN = re.compile(
    r"^ARG BASE_CONTAINER=(?P<ref>[\w./-]+):(?P<tag>[\w.-]+)"
    r"@(?P<digest>sha256:[0-9a-f]{64})[ \t]*$",
    re.M,
)
VERSION_TAG = re.compile(r"^(?P<prefix>hub-)?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
SERIES_TAG = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)-(?P<variant>[a-z][\w.-]*)$")

# fetch(ref, name_filter) -> iterable of (tag, digest)
TagFetcher = Callable[[str, str], Iterable[tuple[str, str]]]


@dataclass
class Update:
    image: str
    ref: str
    old_tag: str
    old_digest: str
    new_tag: str
    new_digest: str
    not_applied: str | None = None
    not_applied_digest: str | None = None

    @property
    def changed(self) -> bool:
        return (self.old_tag, self.old_digest) != (self.new_tag, self.new_digest)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def fetch_tags(ref: str, name_filter: str) -> Iterable[tuple[str, str]]:
    """Yield (tag, digest) for quay.io/... or Docker Hub refs, newest first."""
    host, _, path = ref.partition("/")
    if host == "quay.io":
        for page in range(1, MAX_PAGES + 1):
            data = _get_json(
                f"https://quay.io/api/v1/repository/{path}/tag/"
                f"?onlyActiveTags=true&limit=100&page={page}"
            )
            for tag in data.get("tags", []):
                if tag.get("manifest_digest"):
                    yield tag["name"], tag["manifest_digest"]
            if not data.get("has_additional"):
                return
        return
    if "." in host:
        raise SystemExit(f"{ref}: only quay.io and Docker Hub bases can be watched")
    namespace, _, repo = ref.rpartition("/")
    url = (
        f"https://hub.docker.com/v2/namespaces/{namespace or 'library'}/repositories/{repo}/tags"
        f"?page_size=100&name={urllib.parse.quote(name_filter)}"
    )
    for _ in range(MAX_PAGES):
        data = _get_json(url)
        for tag in data.get("results", []):
            if tag.get("digest"):
                yield tag["name"], tag["digest"]
        url = data.get("next")
        if not url:
            return


def check_image(image: str, root: Path, fetch: TagFetcher) -> Update | None:
    match = PIN.search((root / image / "Dockerfile").read_text())
    if not match:
        return None
    ref, current_tag = match["ref"], match["tag"]

    version, series = VERSION_TAG.match(current_tag), SERIES_TAG.match(current_tag)
    if version:
        tags = dict(fetch(ref, ""))
        prefix = version["prefix"] or ""
        current = tuple(int(version[k]) for k in ("major", "minor", "patch"))
        best_tag, best, newer = current_tag, current, None
        for tag in tags:
            m = VERSION_TAG.match(tag)
            if not m or (m["prefix"] or "") != prefix:
                continue
            candidate = tuple(int(m[k]) for k in ("major", "minor", "patch"))
            if candidate[0] == current[0]:
                if candidate > best:
                    best_tag, best = tag, candidate
            elif candidate[0] > current[0] and (newer is None or candidate > newer[1]):
                newer = (tag, candidate)
        not_applied = newer[0] if newer else None
    elif series:
        tags = dict(fetch(ref, f"-{series['variant']}"))
        best_tag = current_tag
        current = (int(series["major"]), int(series["minor"]))
        newer = None
        for tag in tags:
            m = SERIES_TAG.match(tag)
            if not m or m["variant"] != series["variant"] or int(m["major"]) != current[0]:
                continue
            candidate = (int(m["major"]), int(m["minor"]))
            if candidate > current and (newer is None or candidate > newer[1]):
                newer = (tag, candidate)
        not_applied = newer[0] if newer else None
    else:
        return None

    if best_tag not in tags:
        raise SystemExit(f"{image}: tag {best_tag} not found for {ref}")
    return Update(
        image=image,
        ref=ref,
        old_tag=current_tag,
        old_digest=match["digest"],
        new_tag=best_tag,
        new_digest=tags[best_tag],
        not_applied=not_applied,
        not_applied_digest=tags[not_applied] if not_applied else None,
    )


def apply_update(update: Update, root: Path) -> None:
    """Rewrite the ARG BASE_CONTAINER line only; comments may repeat the pin."""
    dockerfile = root / update.image / "Dockerfile"
    line = f"ARG BASE_CONTAINER={update.ref}:{update.new_tag}@{update.new_digest}"
    text, n = PIN.subn(lambda _: line, dockerfile.read_text())
    if n != 1:
        raise SystemExit(f"{dockerfile}: expected exactly one ARG BASE_CONTAINER pin, found {n}")
    dockerfile.write_text(text)


def summary(updates: list[Update]) -> str:
    lines = [
        "| Image | Base | Current | Newest applied | |",
        "|---|---|---|---|---|",
    ]
    for u in updates:
        if not u.changed:
            state = "up to date"
        elif u.old_tag == u.new_tag:
            state = "**digest refreshed**"
        else:
            state = "**new version**"
        lines.append(
            f"| {u.image} | `{u.ref}` | `{u.old_tag}@{u.old_digest[:19]}…` "
            f"| `{u.new_tag}@{u.new_digest[:19]}…` | {state} |"
        )
    held = [u for u in updates if u.not_applied]
    if held:
        lines.append("")
        lines.append("Newer releases available, not applied (need a deliberate upgrade):")
        lines.extend(f"- {u.image}: `{u.ref}:{u.not_applied}`" for u in held)
    return "\n".join(lines) + "\n"


# What else a held-back upgrade of each image needs besides the new pin.
MAJOR_NOTES = {
    "ngshare-notebook": [
        "Run `ci/regen-constraints.sh ngshare`.",
        "Release notes: https://docs.python.org/3/whatsnew/",
    ],
    "r-studio": [
        "Run `ci/regen-constraints.sh r-studio`; bump `CRAN_SNAPSHOT` if packages fail to install.",
        "Release notes: https://github.com/rocker-org/rocker-versioned2/releases",
    ],
}
NOTEBOOK_NOTES = [
    "geophysics, julia, r, scipy and tensorflow share `constraints.txt`: upgrade all five together, "
    "then run `ci/regen-constraints.sh notebooks`.",
    "Release notes: https://github.com/jupyter/docker-stacks/blob/main/CHANGELOG.md",
]


def major_report(updates: list[Update]) -> str:
    """Markdown with the manual upgrade steps, or "" when nothing is held back."""
    held = [u for u in updates if u.not_applied]
    if not held:
        return ""
    lines = [
        "## Major upgrade available: not built, tested or published",
        "",
        "A newer major release (for ngshare: a newer Python minor) is out. These can",
        "break images, so the watcher does **not** apply, build, test or publish them.",
        "Other updates in this run were handled as usual.",
    ]
    for u in held:
        lines += [
            "",
            f"### {u.image}",
            "",
            f"- Now: `{u.ref}:{u.old_tag}`",
            f"- Available: `{u.ref}:{u.not_applied}`",
            f"- In `{u.image}/Dockerfile`, replace the `ARG BASE_CONTAINER=` line with:",
            "  ```",
            f"  ARG BASE_CONTAINER={u.ref}:{u.not_applied}@{u.not_applied_digest}",
            "  ```",
        ]
        notes = NOTEBOOK_NOTES if u.old_tag.startswith("hub-") else MAJOR_NOTES.get(u.image, [])
        lines += [f"- {note}" for note in notes]
    lines += [
        "",
        "### How to upgrade manually",
        "",
        "1. Read the release notes above for breaking changes.",
        "2. New branch from `main`; replace the `ARG BASE_CONTAINER=` line(s) above.",
        "3. Do the extra steps listed under each image.",
        "4. Build and test locally:",
        "   ```bash",
        "   docker buildx build --load -f <image>/Dockerfile -t local/<image>:test .",
        "   <image>/ci/smoke.sh local/<image>:test",
        "   ci/hub-compat.sh <image> local/<image>:test   # user images only",
        "   ```",
        "5. Push and open a PR to `main`: CI builds and tests every changed image (no push).",
        "6. Merge: `main` publishes new short-SHA tags. Deploy manually, stg first",
        "   (README, *Deploying*).",
        "",
        "The digest above is from this run; the watcher refreshes it daily. After the",
        "merge it follows the new major automatically.",
    ]
    return "\n".join(lines) + "\n"


def watched_images(root: Path) -> list[str]:
    # Same image set as ci/select_images.py: codingworkspace-* is not ours.
    return sorted(
        path.parent.name
        for path in root.glob("*/Dockerfile")
        if not path.parent.name.startswith("codingworkspace-")
    )


def check_all(root: Path, fetch: TagFetcher, only: list[str] | None = None) -> list[Update]:
    updates = []
    for image in watched_images(root):
        if only and image not in only:
            continue
        update = check_image(image, root, fetch)
        if update is not None:
            updates.append(update)
    return updates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="rewrite BASE_CONTAINER pins")
    parser.add_argument("--image", action="append", help="check only this image (repeatable)")
    parser.add_argument("--summary", type=Path, help="write a Markdown summary here")
    parser.add_argument("--major-report", type=Path, help="write manual upgrade steps here")
    parser.add_argument("--format", choices=("text", "github-output"), default="text")
    args = parser.parse_args()

    updates = check_all(ROOT, fetch_tags, args.image)
    changed = [u for u in updates if u.changed]
    if args.apply:
        for update in changed:
            apply_update(update, ROOT)
    if args.summary:
        args.summary.write_text(summary(updates))
    if args.major_report:
        args.major_report.write_text(major_report(updates))

    images = json.dumps(sorted(u.image for u in changed), separators=(",", ":"))
    held = json.dumps(sorted(u.image for u in updates if u.not_applied), separators=(",", ":"))
    if args.format == "github-output":
        print(f"images={images}")
        print(f"held={held}")
    else:
        print(summary(updates), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
