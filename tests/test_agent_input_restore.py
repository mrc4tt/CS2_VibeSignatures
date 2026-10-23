import os
import tempfile
import unittest

import ida_analyze_bin as M


class TestAgentInputRestore(unittest.TestCase):
    def test_a_rewritten_or_deleted_input_is_put_back(self):
        # 14192: the -decompiles agent rewrote PickupItem.windows without its func_sig
        with tempfile.TemporaryDirectory() as tmp:
            kept, edited, gone = (os.path.join(tmp, n) for n in ("a.yaml", "b.yaml", "c.yaml"))
            for path in (kept, edited, gone):
                with open(path, "w") as handle:
                    handle.write("func_sig: 48 8B\n")
            snapshot = M._snapshot_input_files([kept, edited, gone, os.path.join(tmp, "missing.yaml")])
            with open(edited, "w") as handle:
                handle.write("func_va: '0x1'\n")
            os.remove(gone)
            self.assertEqual(sorted([edited, gone]), sorted(M._restore_input_files(snapshot)))
            for path in (kept, edited, gone):
                with open(path) as handle:
                    self.assertEqual("func_sig: 48 8B\n", handle.read())


if __name__ == "__main__":
    unittest.main()
