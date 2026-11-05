"""A last-good copy of each warm .i64, put back when the database will not open.

Twice on 14196 server.dll.i64 came out of a stop unopenable ("internal error
1228") and the run failed until it was rebuilt by hand. Pinned here: the copy is
taken only from a database that passed the identity check, it is not re-copied
when unchanged, shards never take one, a failed open puts it back once (setting
the failed file aside), and the 1228 log line counts as "cannot open".
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import ida_analyze_bin as iab  # noqa: E402
import ida_shards  # noqa: E402


class LastGood(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.binary = self.dir / "server.dll"
        self.binary.write_bytes(b"MZ")
        self.i64 = self.dir / "server.dll.i64"
        self.i64.write_bytes(b"IDA2good")

    def tearDown(self):
        self.tmp.cleanup()

    def lastgood(self):
        return Path(iab._lastgood_path(self.binary))

    def test_save_copies_once(self):
        env = {k: v for k, v in os.environ.items() if k != ida_shards.SHARD_PLAN_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(iab._save_lastgood_idb(self.binary), os.fspath(self.lastgood()))
            self.assertEqual(self.lastgood().read_bytes(), b"IDA2good")
            with mock.patch.object(iab.shutil, "copy2", side_effect=AssertionError("re-copied")):
                iab._save_lastgood_idb(self.binary)

    def test_shards_and_headerless_databases_take_no_copy(self):
        with mock.patch.dict(os.environ, {ida_shards.SHARD_PLAN_ENV: "x"}):
            self.assertIsNone(iab._save_lastgood_idb(self.binary))
        self.i64.write_bytes(b"\0\0\0\0")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(iab._save_lastgood_idb(self.binary))
        self.assertFalse(self.lastgood().exists())

    def test_restore_sets_the_failed_one_aside(self):
        self.lastgood().write_bytes(b"IDA2good")
        old = time.time() - 3600
        os.utime(self.lastgood(), (old, old))
        self.i64.write_bytes(b"IDA2broken")
        (self.dir / "server.dll.id0").write_bytes(b"x")
        (self.dir / "server.dll.i64.unopenable-20000101-000000").write_bytes(b"older")
        self.assertTrue(iab._restore_lastgood_idb(self.binary))
        self.assertEqual(self.i64.read_bytes(), b"IDA2good")
        self.assertFalse((self.dir / "server.dll.id0").exists())
        aside = sorted(p.name for p in self.dir.glob("server.dll.i64.unopenable-*"))
        self.assertEqual(len(aside), 1, "only the newest failed copy is kept")
        self.assertEqual((self.dir / aside[0]).read_bytes(), b"IDA2broken")

    def test_restore_does_nothing_without_a_different_copy(self):
        self.assertFalse(iab._restore_lastgood_idb(self.binary))
        with mock.patch.dict(os.environ, {}, clear=True):
            iab._save_lastgood_idb(self.binary)
        self.assertFalse(iab._restore_lastgood_idb(self.binary), "the copy is what failed")

    def test_a_failed_warm_open_restores_and_retries_once(self):
        self.lastgood().write_bytes(b"IDA2good")
        old = time.time() - 3600
        os.utime(self.lastgood(), (old, old))
        self.i64.write_bytes(b"IDA2broken")
        dead = mock.Mock(pid=1)
        dead.poll.return_value = 1
        opened = []

        def wait_for_port(*_a, **_k):
            opened.append(self.i64.read_bytes())
            return self.i64.read_bytes() == b"IDA2good"

        with mock.patch.object(iab, "is_port_in_use", return_value=False), \
                mock.patch.object(iab.subprocess, "Popen", return_value=dead), \
                mock.patch.object(iab, "wait_for_port", side_effect=wait_for_port), \
                mock.patch.object(iab, "wait_for_port_release", return_value=True), \
                mock.patch.object(iab, "_terminate_process_group"), \
                mock.patch.object(iab.os, "killpg", create=True), \
                mock.patch.object(iab, "_idalib_mcp_log_tail",
                                  return_value="FATAL ERROR: Oops! internal error 1228 occurred."):
            process = iab.start_idalib_mcp(os.fspath(self.binary), port=1)
        self.assertIs(process, dead)
        self.assertEqual(opened[-1], b"IDA2good")
        self.assertEqual(opened.count(b"IDA2good"), 1)

    def test_internal_error_1228_counts_as_unopenable(self):
        self.assertTrue(any(m in "FATAL ERROR: Oops! internal error 1228 occurred."
                            for m in iab.UNOPENABLE_LOG_MARKERS))


if __name__ == "__main__":
    unittest.main()
