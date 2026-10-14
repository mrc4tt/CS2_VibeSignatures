"""auto_repair plans a repair only with evidence that does not come from the repair itself."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_repair as R  # noqa: E402
import verify_plugin_gamedata as P  # noqa: E402


def cell(offset, state="verified", **extra):
    record = {"module": "engine", "struct": "CServerSideClient", "member": "m_x", "offset": offset,
              "size": 8, "symbol": "CServerSideClient_m_x"}
    return dict({"status": "match", "verification": state, "record": record}, **extra)


def report(linux, windows):
    return [{"results": [{"name": "CServerSideClient::m_x", "platforms": {"linux": linux, "windows": windows}}]}]


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_cross_platform_evidence_is_repaired_at_the_named_instruction(self):
        windows = cell(0x9f8, "contradicted", xplat="mismatch", expected=0xa0, evidence_at="0x1800c6358",
                       evidence_in="CServerSideClientBase_Connect")
        repairs, left = R.plan("1", report(cell(0xa0), windows), binaries=None)
        self.assertEqual([(r[1], hex(r[2]), r[3]) for r in repairs], [("windows", "0x1800c6358", 0xa0)])
        self.assertEqual(left, [])

    def test_in_signature_repair_needs_the_other_platform_to_agree(self):
        with mock.patch.object(R, "_in_signature", return_value=(0x53565B, 0x50)) as found:
            repairs, _ = R.plan("1", report(cell(0x4C, "contradicted", width="mismatch"), cell(0x50)), None)
        self.assertEqual(repairs[0][2:4], (0x53565B, 0x50))
        self.assertEqual(found.call_args.args[1], "linux")

    def test_no_independent_evidence_is_left_for_a_person(self):
        with mock.patch.object(R, "_in_signature", return_value=None):
            repairs, left = R.plan("1", report(cell(0x4C, "contradicted", width="mismatch"), cell(0x50)), None)
        self.assertEqual(repairs, [])
        self.assertIn("no instruction with independent evidence", left[0][2])

    def test_shared_offset_agreeing_with_the_other_platform_is_left_alone(self):
        with mock.patch.object(R, "_in_signature") as found:
            repairs, left = R.plan("1", report(cell(0x48, "contradicted", unique="mismatch",
                                                    shares_offset_with="m_nEntityIndex"), cell(0x48)), None)
        found.assert_not_called()
        self.assertEqual(repairs, [])
        self.assertIn("clears once they are repaired", left[0][2])

    def test_shared_offset_disagreeing_with_the_other_platform_is_repaired(self):
        with mock.patch.object(R, "_in_signature", return_value=(0x549C42, 0x4C)):
            repairs, _ = R.plan("1", report(cell(0x48, "contradicted", unique="mismatch"), cell(0x4C)), None)
        self.assertEqual(repairs[0][2:4], (0x549C42, 0x4C))

    def test_in_signature_refuses_an_unverified_other_platform(self):
        self.assertIsNone(R._in_signature(None, "linux", cell(0x4C), cell(0x50, "unverified"), {"offset_sig": "48"}))


class AnchorDisagreementTests(unittest.TestCase):
    def _row(self, windows_offset):
        linux = cell(0xa0, anchor="ok", anchored_in="Connect")
        windows = cell(windows_offset)
        windows["record"]["size"] = linux["record"]["size"] = 1
        return {"platforms": {"linux": linux, "windows": windows}}

    def test_other_platform_value_in_the_same_function_contradicts(self):
        row = self._row(0x9f8)

        class Bins:
            def get(self, module, platform):
                return b"x", {}, None

        with mock.patch.object(P, "_identified_functions", return_value=[(0x100, 0x200, "Connect")]), \
                mock.patch.object(P, "_field_accesses", return_value={0xa0: 0x150}):
            P.anchor_disagreement(row, Bins())
        windows = row["platforms"]["windows"]
        self.assertEqual((windows["xplat"], windows["expected"], windows["evidence_at"]), ("mismatch", 0xa0, "0x150"))

    def test_a_layout_that_uses_its_own_value_is_left_alone(self):
        row = self._row(0x9f8)

        class Bins:
            def get(self, module, platform):
                return b"x", {}, None

        with mock.patch.object(P, "_identified_functions", return_value=[(0x100, 0x200, "Connect")]), \
                mock.patch.object(P, "_field_accesses", return_value={0xa0: 0x150, 0x9f8: 0x160}):
            P.anchor_disagreement(row, Bins())
        self.assertNotIn("xplat", row["platforms"]["windows"])


if __name__ == "__main__":
    unittest.main()
