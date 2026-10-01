"""Unit tests for the identity checks that guard relocation.

audit_xref_identity: a function must still hold its finder's anchor.
audit_identity_drift: a function must keep its strings across gamevers.
Both are also applied inside the run, to every fresh relocation.
"""

import unittest
from unittest import mock

import audit_identity_drift as drift
import audit_xref_identity as xref
import ida_analyze_bin


class FakeBinary:
    """Just enough of audit_xref_identity.Binary for compare()."""

    def __init__(self, present=()):
        self.present = set(present)

    def va_to_off(self, va):
        return None


class SigRegexTest(unittest.TestCase):
    def test_wildcards_and_literals(self):
        rx = xref.sig_regex("48 8B ?? E8 ?")
        self.assertIsNotNone(rx.fullmatch(b"\x48\x8b\x00\xe8\xff"))
        self.assertIsNone(rx.fullmatch(b"\x48\x8c\x00\xe8\xff"))

    def test_rejects_garbage(self):
        self.assertIsNone(xref.sig_regex("48 ZZ"))


class CompareTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(drift, "string_present", lambda binary, text: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_strings_carried_over_is_ok(self):
        verdict, _ = drift.compare(({b"aaaaaa", b"bbbbbb"}, 3, 0x100),
                                   ({b"aaaaaa", b"bbbbbb"}, 3, 0x100), FakeBinary())
        self.assertEqual(verdict, "OK")

    def test_strings_held_together_elsewhere_is_drift(self):
        # JoinTeam.linux 14182: the old strings, all of them, in the real function
        old = ({b"HandleCommand_JoinTeam( %d ) - invalid", b"Team for queue", b"spectate"}, 9, 0x600)
        new = (set(), 4, 0x80)
        with mock.patch.object(drift, "where_strings_went", return_value=(0x1580E50, 3, 1.0)):
            verdict, why = drift.compare(old, new, FakeBinary())
        self.assertEqual(verdict, "DRIFT")
        self.assertIn("0x1580e50", why)

    def test_outlined_body_is_ok(self):
        # CLoopModeGame_LoopInit 14182: slot 0 became a wrapper calling the body
        old = ({b"listenserver", b"dedicated", b"save file"}, 40, 0xE84)
        new = (set(), 2, 0x75)
        with mock.patch.object(drift, "where_strings_went", return_value=(0x177BF00, 3, 1.0)):
            verdict, why = drift.compare(old, new, FakeBinary(), {0x177BF00})
        self.assertEqual(verdict, "OK")
        self.assertIn("outlined", why)

    def test_scattered_strings_is_only_a_warning(self):
        # CreatePlayerPawnServices 14182: the m_p* literals survive only in the schema table
        old = ({b"m_pBulletServices", b"m_pHostageServices", b"m_pBuyServices"}, 7, 0x2FF)
        new = (set(), 7, 0x1C4)
        with mock.patch.object(drift, "where_strings_went", return_value=None):
            verdict, _ = drift.compare(old, new, FakeBinary())
        self.assertEqual(verdict, "WARN")

    def test_single_string_never_drifts(self):
        old = ({b"basic_string::assign"}, 2, 0x40)
        verdict, _ = drift.compare(old, (set(), 2, 0x40), FakeBinary())
        self.assertEqual(verdict, "WARN")

    def test_strings_gone_from_binary_say_nothing(self):
        with mock.patch.object(drift, "string_present", lambda binary, text: False):
            verdict, _ = drift.compare(({b"removed literal"}, 1, 0x40), (set(), 1, 0x40), FakeBinary())
        self.assertEqual(verdict, "SKIP")


class LoadSpecsTest(unittest.TestCase):
    def test_noinline_and_inlined_are_alternatives(self):
        specs, _ = xref.load_specs("CMsgSource2NetworkFlowQuality_PrintStats")
        linux = specs["CMsgSource2NetworkFlowQuality_PrintStats"]["linux"]
        self.assertFalse(linux[0]["inlined"])
        self.assertTrue(any(e["inlined"] for e in linux[1:]))
        # windows is produced only by -inlined: never judged by it alone
        self.assertNotIn("windows", specs["CMsgSource2NetworkFlowQuality_PrintStats"])

    def test_platform_specific_signatures(self):
        specs, _ = xref.load_specs("CCSPlayerPawn_CreatePlayerPawnServices")
        spec = specs["CCSPlayerPawn_CreatePlayerPawnServices"]
        self.assertEqual(spec["linux"][0]["signatures"], ["4C 89 A3 ?? ?? 00 00 48 89 DE 4C 89 E7 E8"])
        self.assertEqual(spec["windows"][0]["signatures"], ["48 8B ?? 48 89 ?? ?? ?? 00 00 48 8B C8 E8"])
        self.assertEqual(spec["linux"][0]["strings"], [])


class SkillSelectionTest(unittest.TestCase):
    def test_comma_separated_list(self):
        skills = [{"name": "find-a"}, {"name": "find-b"}, {"name": "find-c"}]
        selected = ida_analyze_bin._select_skills_by_name(skills, "find-a, find-c")
        self.assertEqual([s["name"] for s in selected], ["find-a", "find-c"])


if __name__ == "__main__":
    unittest.main()
