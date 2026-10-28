#!/usr/bin/env python3
"""Offline tests for ci/check_base_updates.py (quay.io is faked).

Run from the repository root:  python3 ci/test_check_base_updates.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_base_updates as cbu  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
D = {n: "sha256:" + n * 64 for n in "abcdef"}


def dockerfile(base: str) -> str:
    return f"ARG BASE_CONTAINER={base}\nFROM $BASE_CONTAINER\n"


class CheckBaseUpdatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.tags: dict[str, dict[str, str]] = {}

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def image(self, name: str, base: str) -> None:
        (self.root / name).mkdir()
        (self.root / name / "Dockerfile").write_text(dockerfile(base))

    def fetch(self, ref: str, name_filter: str):
        return [(t, d) for t, d in self.tags[ref].items() if name_filter in t]

    def test_newer_patch_and_minor_in_same_major_is_applied(self) -> None:
        self.image("scipy-notebook", f"quay.io/jupyter/scipy-notebook:hub-6.1.1@{D['a']}")
        self.tags["quay.io/jupyter/scipy-notebook"] = {
            "hub-6.1.1": D["a"], "hub-6.1.2": D["b"], "hub-6.2.0": D["c"],
            "2026-10-23": D["c"], "latest": D["c"],
        }
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertEqual((u.new_tag, u.new_digest, u.not_applied), ("hub-6.2.0", D["c"], None))
        cbu.apply_update(u, self.root)
        self.assertEqual(
            (self.root / "scipy-notebook" / "Dockerfile").read_text(),
            dockerfile(f"quay.io/jupyter/scipy-notebook:hub-6.2.0@{D['c']}"),
        )

    def test_k8s_hub_patch_release_is_found(self) -> None:
        self.image("jupyterhub", f"quay.io/jupyterhub/k8s-hub:4.4.4@{D['a']}")
        self.tags["quay.io/jupyterhub/k8s-hub"] = {
            "4.4.4": D["a"], "4.4.5": D["b"], "4.4.5-0.dev.git.7.h1234": D["c"],
        }
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertEqual((u.new_tag, u.new_digest), ("4.4.5", D["b"]))

    def test_new_major_is_reported_not_applied(self) -> None:
        self.image("r-studio", f"rocker/tidyverse:4.6.1@{D['a']}")
        self.tags["rocker/tidyverse"] = {"4.6.1": D["a"], "5.0.0": D["b"]}
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertFalse(u.changed)
        self.assertEqual(u.not_applied, "5.0.0")
        self.assertIn("5.0.0", cbu.summary([u]))
        report = cbu.major_report([u])
        self.assertIn(f"ARG BASE_CONTAINER=rocker/tidyverse:5.0.0@{D['b']}", report)
        self.assertIn("CRAN_SNAPSHOT", report)

    def test_no_major_report_when_nothing_is_held(self) -> None:
        self.image("scipy-notebook", f"quay.io/jupyter/scipy-notebook:hub-6.1.1@{D['a']}")
        self.tags["quay.io/jupyter/scipy-notebook"] = {"hub-6.1.1": D["b"]}
        self.assertEqual(cbu.major_report(cbu.check_all(self.root, self.fetch)), "")

    def test_same_tag_new_digest_is_a_refresh(self) -> None:
        self.image("julia-notebook", f"quay.io/jupyter/julia-notebook:hub-6.1.1@{D['a']}")
        self.tags["quay.io/jupyter/julia-notebook"] = {"hub-6.1.1": D["d"]}
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertTrue(u.changed)
        self.assertEqual((u.new_tag, u.new_digest), ("hub-6.1.1", D["d"]))
        self.assertIn("digest refreshed", cbu.summary([u]))

    def test_up_to_date_is_unchanged(self) -> None:
        self.image("r-notebook", f"quay.io/jupyter/r-notebook:hub-6.1.1@{D['a']}")
        self.tags["quay.io/jupyter/r-notebook"] = {"hub-6.1.1": D["a"], "hub-6.1.0": D["e"]}
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertFalse(u.changed)

    def test_unwatched_bases_are_skipped(self) -> None:
        self.image("ai100-notebook", "quay.io/jupyter/scipy-notebook:hub-5.5.0")
        self.image("codingworkspace-notebook", f"quay.io/jupyter/base-notebook:hub-5.5.1@{D['a']}")
        self.assertEqual(cbu.check_all(self.root, self.fetch), [])

    def test_docker_hub_series_tag_refreshes_digest_and_reports_newer_minor(self) -> None:
        self.image("ngshare-notebook", f"python:3.12-slim-bookworm@{D['a']}")
        self.tags["python"] = {
            "3.12-slim-bookworm": D["b"], "3.12.15-slim-bookworm": D["b"],
            "3.13-slim-bookworm": D["c"], "3.14-rc-slim-bookworm": D["d"],
            "3.13-slim-trixie": D["e"],
        }
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertEqual((u.new_tag, u.new_digest), ("3.12-slim-bookworm", D["b"]))
        self.assertEqual(u.not_applied, "3.13-slim-bookworm")
        self.assertIn(f"python:3.13-slim-bookworm@{D['c']}", cbu.major_report([u]))
        cbu.apply_update(u, self.root)
        self.assertEqual(
            (self.root / "ngshare-notebook" / "Dockerfile").read_text(),
            dockerfile(f"python:3.12-slim-bookworm@{D['b']}"),
        )

    def test_docker_hub_version_tag(self) -> None:
        self.image("r-studio", f"rocker/tidyverse:4.6.1@{D['a']}")
        self.tags["rocker/tidyverse"] = {
            "4.6.1": D["a"], "4.6.2": D["b"], "4.6": D["b"], "latest": D["b"], "devel": D["c"],
        }
        [u] = cbu.check_all(self.root, self.fetch)
        self.assertEqual((u.new_tag, u.new_digest), ("4.6.2", D["b"]))

    def test_watched_images_in_this_repo(self) -> None:
        watched = sorted(u.image for u in cbu.check_all(REPO, lambda ref, _: _current_pins()[ref].items()))
        self.assertEqual(
            watched,
            ["geophysics-notebook", "julia-notebook", "ngshare-notebook", "r-notebook", "r-studio",
             "scipy-notebook", "tensorflow-notebook"],
        )


class ApplyOnRealDockerfilesTest(unittest.TestCase):
    """apply_update must work on every real Dockerfile (comments may repeat the pin)."""

    def test_apply_update_rewrites_each_real_pin(self) -> None:
        fake = "sha256:" + "0" * 64
        for image in cbu.watched_images(REPO):
            text = (REPO / image / "Dockerfile").read_text()
            m = cbu.PIN.search(text)
            if not m:
                continue
            with self.subTest(image=image), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / image).mkdir()
                (Path(tmp) / image / "Dockerfile").write_text(text)
                u = cbu.Update(image=image, ref=m["ref"], old_tag=m["tag"], old_digest=m["digest"],
                               new_tag=m["tag"], new_digest=fake)
                cbu.apply_update(u, Path(tmp))
                new = (Path(tmp) / image / "Dockerfile").read_text()
                self.assertEqual(cbu.PIN.search(new)["digest"], fake)
                self.assertEqual(new, text.replace(m[0], m[0].replace(m["digest"], fake)))


def _current_pins() -> dict[str, dict[str, str]]:
    pins: dict[str, dict[str, str]] = {}
    for dockerfile_path in REPO.glob("*/Dockerfile"):
        match = cbu.PIN.search(dockerfile_path.read_text())
        if match:
            pins.setdefault(match["ref"], {})[match["tag"]] = match["digest"]
    return pins


if __name__ == "__main__":
    unittest.main()
