"""The scan service's caches: a repeated question is answered from memory, and a
changed config is read again.

A warm /api/verify took 4.4 s on 14196, three quarters of it parsing the config
three times and scanning the same signatures again; with these caches it takes
0.15 s. What must never happen is a stale answer: a scan memo kept for a blob
that is gone, or alias tables kept for a config that changed.
"""

import os
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import validate_artifacts as V  # noqa: E402
import verify_plugin_gamedata as VPG  # noqa: E402


class ScanMemo(unittest.TestCase):
    def test_same_blob_same_answer_from_memory(self):
        blob = b"\x90" * 16 + b"\x55\x48\x89\xe5" + b"\xcc" * 8
        calls = []
        real = V._find_all
        V._find_all = lambda *a: calls.append(1) or real(*a)
        try:
            first = V.find_all(blob, [0x55, 0x48, None, 0xE5])
            second = V.find_all(blob, [0x55, 0x48, None, 0xE5])
        finally:
            V._find_all = real
        self.assertEqual(first, [16])
        self.assertEqual(second, [16])
        self.assertEqual(len(calls), 1)

    def test_an_equal_but_different_blob_is_scanned_itself(self):
        one = bytearray(b"\x00\x55\x48\x89\xe5")
        two = bytes(b"\x55\x48\x89\xe5\x00")
        self.assertEqual(V.find_all(bytes(one), [0x55, 0x48]), [1])
        self.assertEqual(V.find_all(two, [0x55, 0x48]), [0])

    def test_callers_get_their_own_list(self):
        blob = b"\x55\x48" * 3
        V.find_all(blob, [0x55, 0x48]).append(999)
        self.assertNotIn(999, V.find_all(blob, [0x55, 0x48]))


class ConfigDerived(unittest.TestCase):
    def test_a_changed_config_is_read_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.yaml")
            built = []

            def table(value):
                def build():
                    built.append(value)
                    return {"v": value}
                return build

            with open(path, "w") as handle:
                handle.write("a: 1\n")
            self.assertEqual(VPG._from_config("t", path, table(1)), {"v": 1})
            self.assertEqual(VPG._from_config("t", path, table(1)), {"v": 1})
            self.assertEqual(built, [1])
            time.sleep(0.01)
            with open(path, "w") as handle:
                handle.write("a: 22\n")
            self.assertEqual(VPG._from_config("t", path, table(2)), {"v": 2})
            self.assertEqual(built, [1, 2])

    def test_callers_get_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.yaml")
            with open(path, "w") as handle:
                handle.write("x\n")
            VPG._from_config("copy", path, lambda: {"a": 1})["b"] = 2
            self.assertEqual(VPG._from_config("copy", path, lambda: {"a": 1}), {"a": 1})


if __name__ == "__main__":
    unittest.main()
