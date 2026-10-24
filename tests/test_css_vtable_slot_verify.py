"""The vtable slot of a CounterStrikeSharp entry is judged the way CounterStrikeSharp reads it.

CSS's FindVirtualTable searches the literal "<len><name>" / ".?AV<name>@@" string and reads the
primary vtable; ApplyVtableFallback compares the raw slot pointer with the address the signature
scanned to. The verifier must agree with that, the generator must not ship a slot it cannot
prove, and the drift check must see a slot the install still holds after the generator dropped it.
"""
import argparse
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import check_deploy_drift as DRIFT  # noqa: E402
import verify_plugin_gamedata as VPG  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "css_gen_verify", os.path.join(REPO, "gamedata-generators", "CounterStrikeSharp", "gamedata.py"))
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


class FakeBinaries:
    def get(self, module, platform):
        return b"blob", {}, ({} if platform == "linux" else None)


BLOCK = {"class": "CBaseTrigger", "linux_index": 2}


class CheckVtableSlotTests(unittest.TestCase):
    def _verdict(self, tables, expected, block=BLOCK):
        with mock.patch.object(VPG, "primary_vtables", return_value=tables):
            return VPG.check_vtable_slot(FakeBinaries(), "server", "linux", block, expected)

    def test_slot_holding_the_function_is_ok(self):
        self.assertEqual(self._verdict([(0x1000, [0x10, 0x20, 0x30])], 0x30), "ok")

    def test_slot_holding_a_thunk_is_a_mismatch(self):
        # CSS compares raw pointers, so a thunk that jumps to the function is not it.
        with mock.patch.object(VPG.V, "_thunk_target", return_value=0x30):
            self.assertEqual(self._verdict([(0x1000, [0x10, 0x20, 0x40])], 0x30), "mismatch")

    def test_two_primary_tables_are_ambiguous(self):
        self.assertEqual(self._verdict([(0x1000, [1, 2, 3]), (0x2000, [1, 2, 3])], 3), "ambiguous")

    def test_index_past_the_table_is_out_of_range(self):
        self.assertEqual(self._verdict([(0x1000, [1, 2])], 2), "out-of-range")

    def test_class_the_runtime_cannot_find_is_unresolved(self):
        self.assertEqual(self._verdict([], 3), "unresolved")


class LiteralNameTests(unittest.TestCase):
    def test_elf_match_must_start_its_own_string(self):
        blob = b"\x00P12CCSGameRules\x00\x0012CCSGameRules\x00"
        self.assertEqual(VPG.V._literal_name_offsets(blob, b"12CCSGameRules\x00", True), [18])

    def test_template_name_is_not_resolved_by_tokens(self):
        # The binary spells the template with its arguments; CSS searches the literal
        # "<...>" name and finds nothing, so the verifier must not find a table either.
        blob = b"\x00N30CGameSystemReallocatingFactoryI20CSource2EntitySystemS0_EE\x00"
        name = "CGameSystemReallocatingFactory<CSource2EntitySystem>"
        VPG._PRIMARY_CACHE.clear()
        self.assertEqual(VPG.primary_vtables(blob, {}, {}, name), [])
        self.assertEqual(VPG.primary_vtables(blob, {}, None, name), [])


class ReportGateTests(unittest.TestCase):
    def test_vtable_mismatch_is_unhealthy(self):
        results = [{"name": "K", "kind": "signature", "module": "server",
                    "platforms": {"linux": {"status": "ok", "vtable": "mismatch"}}}]
        args = argparse.Namespace(json=True, quiet=False, gamever="0", gamedata="f.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(VPG._report(results, args, "f.json"), 1)

    def test_vtable_ok_is_healthy(self):
        results = [{"name": "K", "kind": "signature", "module": "server",
                    "platforms": {"linux": {"status": "ok", "vtable": "ok"}}}]
        args = argparse.Namespace(json=True, quiet=False, gamever="0", gamedata="f.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(VPG._report(results, args, "f.json"), 0)


def _yaml(linux_index=151, windows_index=152):
    return {"library": "server",
            "linux": {"func_va": "0x100", "vtable_name": "CBaseTrigger", "vfunc_index": linux_index},
            "windows": {"func_va": "0x180000200", "vtable_name": "CBaseTrigger", "vfunc_index": windows_index}}


class GeneratorProvesSlotTests(unittest.TestCase):
    def _slot(self, verdicts, existing=None):
        entry = {"signatures": {"library": "server"}}
        if existing is not None:
            entry["vtable"] = existing
        seen = []

        def prove(library, platform, class_name, index, func_va):
            seen.append((library, platform, class_name, index, func_va))
            return verdicts[platform]

        with redirect_stdout(io.StringIO()):
            GEN._update_vtable_slot(entry, _yaml(), ["linux", "windows"], prove)
        return entry.get("vtable"), seen

    def test_proven_slot_is_written(self):
        block, seen = self._slot({"linux": "ok", "windows": "ok"})
        self.assertEqual(block, {"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152})
        self.assertIn(("server", "linux", "CBaseTrigger", 151, 0x100), seen)
        self.assertIn(("server", "windows", "CBaseTrigger", 152, 0x180000200), seen)

    def test_unproven_platform_is_dropped(self):
        block, _ = self._slot({"linux": "ok", "windows": "mismatch"},
                              existing={"class": "CBaseTrigger", "windows_index": 99})
        self.assertEqual(block, {"class": "CBaseTrigger", "linux_index": 151})

    def test_nothing_proven_writes_no_block(self):
        block, _ = self._slot({"linux": "unresolved", "windows": "ambiguous"})
        self.assertIsNone(block)

    def test_missing_binary_keeps_the_slot(self):
        block, _ = self._slot({"linux": "no-binary", "windows": "no-binary"})
        self.assertEqual(block, {"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152})

    def test_no_context_means_no_prover(self):
        self.assertIsNone(GEN._slot_prover(None))


class DriftSeesStaleSlotTests(unittest.TestCase):
    def test_install_only_slot_in_a_generated_entry_is_drift(self):
        dist = {"K": {"signatures": {"linux": "55"}}}
        installed = {"K": {"signatures": {"linux": "55"}, "vtable": {"class": "C", "linux_index": 3}},
                     "InstallOnly": {"signatures": {"linux": "90"}}}
        details = DRIFT._diff_keys(dist, installed, generated_only=True)
        self.assertEqual(sorted(d.split(":")[0] for d in details), ["K.vtable.class", "K.vtable.linux_index"])


if __name__ == "__main__":
    unittest.main()


class ScanLikeCssTests(unittest.TestCase):
    """check_signature parses and scans the way CounterStrikeSharp's ScanSignature does."""

    CODE = b"\x90" * 16 + b"\x48\x8B\x05\x11\x22\x33\x44\xC3" + b"\xCC" * 8
    DATA = b"\x48\x8B\x05\x11\x22\x33\x44\xC3"

    class _Bins:
        def __init__(self, blob, segs):
            self.blob, self.info = blob, {"segs": segs, "base": 0}

        def get(self, module, platform):
            return self.blob, self.info, {}

    def _check(self, pattern, with_data_copy=False):
        blob = self.CODE + (self.DATA if with_data_copy else b"")
        code = (0, 0, len(self.CODE), 0x1)
        segs = [code] + ([(len(self.CODE), len(self.CODE), len(self.DATA), 0)] if with_data_copy else [])
        with mock.patch.object(VPG.V, "is_boundary", return_value=True):
            return VPG.check_signature(self._Bins(blob, segs), "server", "linux", pattern)

    def test_too_few_literal_bytes_is_refused(self):
        self.assertEqual(self._check("48 8B ? ? ? ? ? C3")["status"], "too-few-literals")

    def test_multi_digit_token_is_unparsable(self):
        self.assertEqual(self._check("488B 05 11 22 33")["status"], "unparsable")

    def test_hit_in_data_does_not_make_it_ambiguous(self):
        self.assertEqual(self._check("48 8B 05 11 22 33 44 C3", with_data_copy=True)["status"], "ok")

    def test_hit_only_in_data_is_broken(self):
        data = b"\xDE\xAD\xBE\xEF\x01"
        blob = self.CODE + data
        segs = [(0, 0, len(self.CODE), 0x1), (len(self.CODE), len(self.CODE), len(data), 0)]
        got = VPG.check_signature(self._Bins(blob, segs), "server", "linux", "DE AD BE EF 01")
        self.assertEqual(got, {"status": "broken", "outside_code": 1})

    def test_hit_in_a_linker_stub_is_skipped(self):
        # the second copy sits in a .plt range; CSS skips it, so the first is unique
        blob = self.CODE + self.DATA
        segs = [(0, 0, len(blob), 0x1)]
        with mock.patch.object(VPG, "elf_stub_ranges", return_value=[(len(self.CODE), len(self.DATA))]), \
                mock.patch.object(VPG.V, "is_boundary", return_value=True):
            got = VPG.check_signature(self._Bins(blob, segs), "server", "linux", "48 8B 05 11 22 33 44 C3")
        self.assertEqual(got["status"], "ok")

    def test_stub_sections_are_read_from_the_elf_section_headers(self):
        import struct
        names = b"\x00.plt\x00.text\x00.shstrtab\x00"
        shoff = 0x40
        blob = bytearray(0x40 + 4 * 64) + names
        blob[:5] = b"\x7fELF\x02"
        struct.pack_into("<Q", blob, 0x28, shoff)
        struct.pack_into("<HHH", blob, 0x3A, 64, 4, 3)
        strtab = 0x40 + 4 * 64
        for i, (name, off, size) in enumerate([(0, 0, 0), (1, 0x1000, 0x80), (6, 0x2000, 0x500), (12, strtab, len(names))]):
            struct.pack_into("<IIQQQQ", blob, shoff + i * 64, name, 1, 0, 0, off, size)
        self.assertEqual(VPG.elf_stub_ranges(bytes(blob)), [(0x1000, 0x80)])

    def test_status_is_unhealthy(self):
        results = [{"name": "K", "kind": "signature", "module": "server",
                    "platforms": {"linux": {"status": "too-few-literals"}}}]
        args = argparse.Namespace(json=True, quiet=False, gamever="0", gamedata="f.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(VPG._report(results, args, "f.json"), 1)


class CallSiteOffsetTests(unittest.TestCase):
    """A slot-only offset is checked through the call site its index was read from."""

    def _verdict(self, sig_bytes, want, sig_disp=None, kind="pe"):
        blob = b"\xCC" * 16 + sig_bytes + b"\xCC" * 16
        info = {"segs": [(0, 0, len(blob), 0x1)], "base": 0, "type": kind}
        sig = " ".join(f"{b:02X}" for b in sig_bytes)
        return VPG.V.vfunc_sig_calls_offset(blob, info, sig, want, sig_disp)

    def test_call_with_the_offset_is_ok(self):
        self.assertEqual(self._verdict(bytes.fromhex("FF925005000084C0"), 0x550), "ok")

    def test_call_with_another_offset_is_a_mismatch(self):
        self.assertEqual(self._verdict(bytes.fromhex("FF925805000084C0"), 0x550), "mismatch")

    def test_offset_may_sit_in_a_later_instruction(self):
        # mov rax,[rdi]; mov rax,[rax+0xc0]
        self.assertEqual(self._verdict(bytes.fromhex("488B07488B80C0000000"), 0xC0), "ok")

    def test_itanium_member_pointer_is_offset_plus_one(self):
        # mov qword ptr [rbp-0x38], 0x141: a pointer to virtual slot 40 (0x140)
        sig = bytes.fromhex("48C745C841010000")
        self.assertEqual(self._verdict(sig, 0x140, kind="elf"), "ok")
        self.assertEqual(self._verdict(sig, 0x148, kind="elf"), "mismatch")
        # MSVC has no such encoding: the same immediate is not a slot there
        self.assertEqual(self._verdict(sig, 0x140, kind="pe"), "mismatch")

    def test_offset_reported_and_unhealthy(self):
        index = {VPG.fold("K"): {"linux": {"vfunc_index": 170, "vtable_name": "C",
                                           "vfunc_sig": "FF 92 50 05 00 00 84 C0"}}}
        with mock.patch.object(VPG.V, "vfunc_sig_calls_offset", return_value="mismatch") as call:
            got = VPG.check_offset(index, FakeBinaries(), "K", "linux", 170)
        self.assertEqual(got["callsite"], "mismatch")
        self.assertEqual(call.call_args.args[3], 170 * 8)
        args = argparse.Namespace(json=True, quiet=False, gamever="0", gamedata="f.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(VPG._report([{"name": "K", "kind": "offset", "module": "server",
                                           "platforms": {"linux": got}}], args, "f.json"), 1)


class PrimaryOnlyOffsetTests(unittest.TestCase):
    def test_vfunc_offset_is_checked_against_the_primary_table_only(self):
        index = {VPG.fold("K"): {"linux": {"vfunc_index": 1, "vtable_name": "C", "func_va": "0x20"}}}
        with mock.patch.object(VPG.V, "verify_vfunc_slot", return_value="ok") as slot:
            got = VPG.check_offset(index, FakeBinaries(), "K", "linux", 1)
        self.assertEqual(got["rtti"], "ok")
        self.assertTrue(slot.call_args.kwargs["primary_only"])
