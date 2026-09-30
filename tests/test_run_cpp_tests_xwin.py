"""run_cpp_tests.py finds an xwin sysroot for MSVC targets.

Fork-owned. Without a sysroot 15 of 16 cpp_tests fail on `<Windows.h>` at any
hl2sdk commit, so the run says nothing about the headers; these pin the lookup
that makes the run meaningful on a Linux machine.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import run_cpp_tests

MSVC = "x86_64-pc-windows-msvc"


def _make_sysroot(root: Path) -> None:
    for sub in run_cpp_tests._XWIN_INCLUDE_SUBDIRS:
        (root / sub).mkdir(parents=True)


@unittest.skipIf(os.name == "nt", "the sysroot lookup is for non-Windows hosts")
class XwinSysrootTest(unittest.TestCase):
    def test_msvc_target_gets_the_sysroot(self):
        with TemporaryDirectory() as tmp:
            _make_sysroot(Path(tmp))
            with mock.patch.dict(os.environ, {run_cpp_tests.XWIN_ROOT_ENV: tmp}, clear=True):
                env = run_cpp_tests.compile_environment(MSVC)
        self.assertEqual(
            env["CPLUS_INCLUDE_PATH"].split(os.pathsep),
            [str(Path(tmp) / sub) for sub in run_cpp_tests._XWIN_INCLUDE_SUBDIRS],
        )

    def test_incomplete_sysroot_is_not_used(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "crt/include").mkdir(parents=True)
            with mock.patch.dict(os.environ, {run_cpp_tests.XWIN_ROOT_ENV: tmp}, clear=True):
                env = run_cpp_tests.compile_environment(MSVC)
        self.assertNotIn("CPLUS_INCLUDE_PATH", env)

    def test_other_target_and_explicit_path_are_left_alone(self):
        with TemporaryDirectory() as tmp:
            _make_sysroot(Path(tmp))
            with mock.patch.dict(os.environ, {run_cpp_tests.XWIN_ROOT_ENV: tmp}, clear=True):
                self.assertNotIn("CPLUS_INCLUDE_PATH", run_cpp_tests.compile_environment("x86_64-pc-linux-gnu"))
            explicit = {run_cpp_tests.XWIN_ROOT_ENV: tmp, "CPLUS_INCLUDE_PATH": "/mine"}
            with mock.patch.dict(os.environ, explicit, clear=True):
                self.assertEqual(run_cpp_tests.compile_environment(MSVC)["CPLUS_INCLUDE_PATH"], "/mine")


if __name__ == "__main__":
    unittest.main()
