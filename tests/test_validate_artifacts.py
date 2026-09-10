"""Tests for validate_artifacts.py - the artifact-vs-binary invariant checks.

The checks encode defects that were found by hand on 14181, so each test names
the defect it guards against.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validate_artifacts as va


def _fake_info(base=0, text=(0, 0x1000, 0x1000), data=(0x2000, 0x3000, 0x1000)):
    """segs entries are (file_offset, vaddr, size, flags); flag bit 0 = executable."""
    return {"type": "elf", "base": base,
            "segs": [(text[0], text[1], text[2], 0x1),
                     (data[0], data[1], data[2], 0x0)]}


class ParseSigTests(unittest.TestCase):
    def test_wildcard_spellings_all_parse(self):
        for tok in ("?", "??", "2A", "*"):
            self.assertEqual(va.parse_sig(f"48 {tok} C0"), [0x48, None, 0xC0])

    def test_non_hex_is_rejected(self):
        self.assertIsNone(va.parse_sig("48 ZZ C0"))

    def test_longest_literal_run_is_the_search_anchor(self):
        pat = va.parse_sig("48 ?? AA BB CC DD ?? 90")
        self.assertEqual(va._longest_literal_run(pat), (2, 4))

    def test_all_wildcard_pattern_finds_nothing(self):
        # matching everything is never a useful signature, so refuse rather than
        # return every offset in the image
        self.assertEqual(va.find_all(b"\x00" * 64, [None, None, None]), [])


class FindAllTests(unittest.TestCase):
    def test_anchored_search_finds_every_wildcard_match(self):
        blob = b"\x11" + b"\x48\x01\xAA\xBB" + b"\x22" + b"\x48\x02\xAA\xBB" + b"\x33"
        pat = va.parse_sig("48 ?? AA BB")
        self.assertEqual(va.find_all(blob, pat), [1, 6])

    def test_match_must_fit_inside_the_image(self):
        self.assertFalse(va.matches_at(b"\xAA\xBB", 1, [0xBB, 0xCC]))


class LiteralBranchTests(unittest.TestCase):
    """Guards the "74 D4" defect: a rel8 target left literal in a signature."""

    def test_short_jcc_displacement_is_reported(self):
        pat = va.parse_sig("FF 90 90 00 00 00 84 C0 74 D4")
        self.assertIn(9, va.literal_branch_bytes(pat, b"", 0))

    def test_wildcarded_short_jcc_is_accepted(self):
        pat = va.parse_sig("FF 90 90 00 00 00 84 C0 74 ??")
        self.assertEqual(va.literal_branch_bytes(pat, b"", 0), [])

    def test_near_call_displacement_is_reported(self):
        pat = va.parse_sig("48 89 E5 E8 11 22 33 44 90")
        self.assertIn(4, va.literal_branch_bytes(pat, b"", 0))

    def test_two_byte_jcc_displacement_is_reported(self):
        pat = va.parse_sig("84 C0 0F 84 11 22 33 44 90")
        self.assertIn(4, va.literal_branch_bytes(pat, b"", 0))


class BoundaryTests(unittest.TestCase):
    def test_padding_before_marks_a_function_head(self):
        blob = bytearray(0x2000)
        blob[0x0F] = 0xCC
        info = _fake_info()
        self.assertTrue(va.is_boundary(bytes(blob), info, 0x1010))

    def test_unaligned_address_without_padding_is_not_a_head(self):
        blob = bytes(bytearray(0x2000))
        self.assertFalse(va.is_boundary(blob, _fake_info(), 0x1005))

    def test_end_on_padding_is_clean(self):
        blob = bytearray(0x2000)
        blob[0x105] = 0xCC
        self.assertTrue(va.ends_clean(bytes(blob), _fake_info(), 0x1100, 0x5))

    def test_end_on_a_packed_16_byte_boundary_is_clean(self):
        # GCC places the next function directly after a tail jmp with no padding
        blob = bytes(bytearray(b"\x55" * 0x2000))
        self.assertTrue(va.ends_clean(blob, _fake_info(), 0x1100, 0x10))

    def test_end_mid_instruction_without_padding_is_not_clean(self):
        blob = bytes(bytearray(b"\x55" * 0x2000))
        self.assertFalse(va.ends_clean(blob, _fake_info(), 0x1100, 0x5))


class CategoryTests(unittest.TestCase):
    def test_each_category_is_recognised_from_its_identity_field(self):
        cases = {
            "vtable": {"vtable_class": "C"},
            "gv": {"gv_name": "g"},
            "patch": {"patch_name": "p"},
            "structmember": {"struct_name": "S", "member_name": "m"},
            "vfunc": {"func_name": "f", "vtable_name": "C"},
            "func": {"func_name": "f"},
        }
        for expected, payload in cases.items():
            self.assertEqual(va.category_of(payload), expected, expected)

    def test_vtable_wins_over_a_bare_func_name(self):
        self.assertEqual(va.category_of({"vtable_class": "C", "func_name": "f"}), "vtable")

    def test_unrecognisable_payload_returns_none(self):
        self.assertIsNone(va.category_of({"unrelated": 1}))


class GvConsistencyTests(unittest.TestCase):
    """Guards the defect where gv_va held the match address, not the data address."""

    def _blob_with_disp(self, sig_off, disp):
        blob = bytearray(0x4000)
        blob[sig_off:sig_off + 3] = b"\x48\x89\x1D"
        struct.pack_into("<i", blob, sig_off + 3, disp)
        return bytes(blob)

    def test_gv_va_matching_the_rip_target_passes(self):
        info = _fake_info()
        sig_va, disp = 0x1100, 0x1F09        # 0x1100 + 7 + 0x1F09 = 0x3010, in data
        blob = self._blob_with_disp(va.va_to_off(info, sig_va), disp)
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "g",
               "category": "gv", "binary": "b", "va": sig_va}
        out = va.Report()
        va.check_gv(rec, {"gv_va": "0x3010", "gv_sig_va": hex(sig_va),
                          "gv_inst_offset": 0, "gv_inst_length": 7, "gv_inst_disp": 3},
                    blob, info, out)
        self.assertEqual(out.errors, [])

    def test_gv_va_holding_the_match_address_is_an_error(self):
        info = _fake_info()
        sig_va, disp = 0x1100, 0x1F09
        blob = self._blob_with_disp(va.va_to_off(info, sig_va), disp)
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "g",
               "category": "gv", "binary": "b", "va": sig_va}
        out = va.Report()
        va.check_gv(rec, {"gv_va": hex(sig_va), "gv_sig_va": hex(sig_va),
                          "gv_inst_offset": 0, "gv_inst_length": 7, "gv_inst_disp": 3},
                    blob, info, out)
        self.assertTrue(any("is not what the instruction" in r["message"] for r in out.errors))


class VfuncTests(unittest.TestCase):
    def test_offset_must_be_eight_times_the_index(self):
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "s",
               "category": "vfunc", "binary": "b", "va": None}
        out = va.Report()
        va.check_vfunc(rec, {"vfunc_index": 18, "vfunc_offset": "0x88"},
                       b"", _fake_info(), out)
        self.assertTrue(any("not 8 * vfunc_index" in r["message"] for r in out.errors))

    def test_matching_offset_and_index_is_accepted(self):
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "s",
               "category": "vfunc", "binary": "b", "va": None}
        out = va.Report()
        va.check_vfunc(rec, {"vfunc_index": 18, "vfunc_offset": "0x90"},
                       b"", _fake_info(), out)
        self.assertEqual(out.errors, [])


class CrossModuleSlotTests(unittest.TestCase):
    """A copied index that disagrees is an error; two analysed ones only warn."""

    def _rec(self, module):
        return {"path": "p", "module": module, "platform": "linux", "symbol": "S_m",
                "category": "vfunc", "binary": "b", "va": None}

    def test_copied_index_disagreeing_is_an_error(self):
        out = va.Report()
        va.cross_platform_vfunc_check([
            (self._rec("client"), {"vtable_name": "I", "vfunc_index": 4, "func_va": "0x1"}),
            (self._rec("server"), {"vtable_name": "I", "vfunc_index": 5}),
        ], out)
        self.assertEqual(len(out.errors), 1)
        self.assertIn("copied", out.errors[0]["message"])

    def test_two_independently_analysed_modules_only_warn(self):
        out = va.Report()
        va.cross_platform_vfunc_check([
            (self._rec("client"), {"vtable_name": "I", "vfunc_index": 26,
                                   "func_va": "0x1", "func_size": "0x9f4"}),
            (self._rec("server"), {"vtable_name": "I", "vfunc_index": 25,
                                   "func_va": "0x2", "func_size": "0x9b3"}),
        ], out)
        self.assertEqual(out.errors, [])
        self.assertEqual(len(out.warnings), 1)

    def test_agreement_reports_nothing(self):
        out = va.Report()
        va.cross_platform_vfunc_check([
            (self._rec("client"), {"vtable_name": "I", "vfunc_index": 7, "func_va": "0x1"}),
            (self._rec("server"), {"vtable_name": "I", "vfunc_index": 7, "func_va": "0x2"}),
        ], out)
        self.assertEqual(out.rows, [])


class VtableTests(unittest.TestCase):
    def test_size_must_be_eight_times_the_slot_count(self):
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "V",
               "category": "vtable", "binary": "b", "va": 0x3000}
        out = va.Report()
        va.check_vtable(rec, {"vtable_va": "0x3000", "vtable_numvfunc": 10,
                              "vtable_size": "0x40", "vtable_entries": {}},
                        bytes(bytearray(0x4000)), _fake_info(), out)
        self.assertTrue(any("not 8 * vtable_numvfunc" in r["message"] for r in out.errors))

    def test_slot_pointing_outside_code_is_an_error(self):
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "V",
               "category": "vtable", "binary": "b", "va": 0x3000}
        out = va.Report()
        va.check_vtable(rec, {"vtable_va": "0x3000", "vtable_numvfunc": 1,
                              "vtable_size": "0x8",
                              "vtable_entries": {0: "0x3100"}},   # data, not code
                        bytes(bytearray(0x4000)), _fake_info(), out)
        self.assertTrue(any("do not point at code" in r["message"] for r in out.errors))

    def test_zero_slots_are_tolerated_because_a_pie_relocates_them(self):
        rec = {"path": "p", "module": "m", "platform": "linux", "symbol": "V",
               "category": "vtable", "binary": "b", "va": 0x3000}
        out = va.Report()
        va.check_vtable(rec, {"vtable_va": "0x3000", "vtable_numvfunc": 2,
                              "vtable_size": "0x10",
                              "vtable_entries": {0: "0x0", 1: "0x1010"}},
                        bytes(bytearray(0x4000)), _fake_info(), out)
        self.assertEqual(out.errors, [])


if __name__ == "__main__":
    unittest.main()
