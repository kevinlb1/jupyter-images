#!/usr/bin/env python3
"""Tests for ci/select_images.py against a throwaway git copy of this repo.

Run from the repository root:  python3 ci/test_select_images.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOTEBOOKS = ["geophysics-notebook", "julia-notebook", "r-notebook", "scipy-notebook", "tensorflow-notebook"]


def run(*args: str, cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()


class SelectImagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "repo"
        shutil.copytree(
            REPO, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__")
        )
        run("git", "init", "-q", cwd=self.root)
        run("git", "add", "-A", cwd=self.root)
        self.commit("base")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def commit(self, message: str) -> None:
        run(
            "git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
            "commit", "-q", "--allow-empty", "-m", message, cwd=self.root,
        )

    def select(self, *changed: str) -> dict[str, object]:
        for path in changed:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a") as f:
                f.write("\n# test change\n")
        run("git", "add", "-A", cwd=self.root)
        self.commit("change")
        output = run(
            "python3", "ci/select_images.py", "--before", "HEAD^", "--current", "HEAD",
            "--format", "github-output", cwd=self.root,
        )
        result: dict[str, object] = {}
        for line in output.splitlines():
            key, _, value = line.partition("=")
            result[key] = json.loads(value)
        return result

    def test_install_common_selects_only_images_that_copy_it(self) -> None:
        # ai100-notebook also COPYs install-common.sh (without --with-nbgrader).
        self.assertEqual(
            self.select("install-common.sh")["ordinary_images"],
            sorted(["ai100-notebook", *NOTEBOOKS]),
        )

    def test_each_shared_nbgrader_input_selects_notebook_images(self) -> None:
        for path in ("constraints.txt", "nbgrader_config.py", "patch_formgrader.py"):
            with self.subTest(path=path):
                self.assertEqual(self.select(path)["ordinary_images"], NOTEBOOKS)

    def test_runtime_pins_selects_r_and_scipy(self) -> None:
        self.assertEqual(
            self.select("RUNTIME_PINS.env")["ordinary_images"], ["r-notebook", "scipy-notebook"]
        )

    def test_unused_root_file_selects_nothing(self) -> None:
        self.assertEqual(self.select("README.md")["ordinary_images"], [])

    def test_image_directory_change_selects_that_image(self) -> None:
        self.assertEqual(self.select("r-studio/Dockerfile")["ordinary_images"], ["r-studio"])
        self.assertEqual(
            self.select("ngshare-notebook/run.py")["ordinary_images"], ["ngshare-notebook"]
        )

    def test_selector_change_builds_nothing(self) -> None:
        self.assertEqual(self.select("ci/select_images.py")["ordinary_images"], [])

    def test_codingworkspace_directories_are_never_selected(self) -> None:
        # A stand-in codingworkspace-* image that COPYs a shared root file:
        # the CodingWorkspace images are left to their own selector even
        # then.
        cw = self.root / "codingworkspace-standin"
        cw.mkdir()
        (cw / "Dockerfile").write_text("FROM scratch\nCOPY constraints.txt /tmp/\n")
        run("git", "add", "-A", cwd=self.root)
        self.commit("add codingworkspace stand-in")
        self.assertEqual(self.select("constraints.txt")["ordinary_images"], NOTEBOOKS)
        self.assertEqual(
            self.select("codingworkspace-standin/Dockerfile")["ordinary_images"], []
        )


if __name__ == "__main__":
    unittest.main()
