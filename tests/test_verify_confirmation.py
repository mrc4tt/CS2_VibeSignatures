"""verify_plugin_gamedata calls a shipped value VERIFIED only when a method of its own
re-read it from the binary; "it equals what the pipeline produced" is circular."""
import argparse
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify_plugin_gamedata as VPG  # noqa: E402


class VerificationStateTests(unittest.TestCase):
    def test_match_alone_is_unverified(self):
        self.assertEqual(VPG.verification({"status": "match", "value": 8}), "unverified")

    def test_any_confirming_method_verifies(self):
        for method in ("func", "sig", "rtti", "callsite", "inherit", "insn", "schema", "gv", "binary"):
            self.assertEqual(VPG.verification({"status": "match", method: "ok"}), "verified", method)

    def test_one_contradiction_wins(self):
        self.assertEqual(VPG.verification({"status": "match", "insn": "ok", "schema": "mismatch"}),
                         "contradicted")
        self.assertEqual(VPG.verification({"status": "match", "insn": "ok", "align": "mismatch"}),
                         "contradicted")

    def test_nothing_shipped_is_not_judged(self):
        self.assertIsNone(VPG.verification({"status": "not-shipped"}))

    def test_require_verified_fails_an_unverified_value(self):
        rows = [{"name": "K", "kind": "offset", "module": "server",
                 "platforms": {"linux": {"status": "match", "value": 8}}}]
        with redirect_stdout(io.StringIO()):
            loose = argparse.Namespace(json=True, quiet=False, gamever="0", gamedata="f", require_verified=False)
            self.assertEqual(VPG._report([dict(r) for r in rows], loose, "f"), 0)
            strict = argparse.Namespace(json=True, quiet=False, gamever="0", gamedata="f", require_verified=True)
            self.assertEqual(VPG._report(rows, strict, "f"), 1)


class CrossPlatformTests(unittest.TestCase):
    def test_same_offset_from_both_compilers(self):
        row = {"platforms": {"linux": {"status": "match", "value": 56, "insn": "ok"},
                             "windows": {"status": "match", "value": 56, "insn": "ok"}}}
        VPG.cross_platform(row)
        self.assertEqual(row["platforms"]["linux"]["xplat"], "ok")

    def test_different_layout_gets_no_xplat(self):
        row = {"platforms": {"linux": {"status": "match", "value": 3736, "insn": "ok"},
                             "windows": {"status": "match", "value": 3008, "insn": "ok"}}}
        VPG.cross_platform(row)
        self.assertNotIn("xplat", row["platforms"]["linux"])


class RecordResolutionTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(VPG.GENERATOR_ALIASES)

    def tearDown(self):
        VPG.GENERATOR_ALIASES.clear()
        VPG.GENERATOR_ALIASES.update(self.saved)

    def test_generator_alias_comes_before_the_plain_name(self):
        index = {VPG.fold("ClientPrint"): {"linux": {"func_va": "0x1"}},
                 VPG.fold("ClientPrintToController"): {"linux": {"func_va": "0x2"}}}
        VPG.GENERATOR_ALIASES.clear()
        VPG.GENERATOR_ALIASES[VPG.fold("ClientPrint")] = "ClientPrintToController"
        self.assertEqual(VPG.resolve_record(index, "ClientPrint", "linux")["func_va"], "0x2")

    def test_plain_name_without_alias(self):
        index = {VPG.fold("K"): {"linux": {"offset": "0x8"}}}
        VPG.GENERATOR_ALIASES.clear()
        self.assertEqual(VPG.resolve_record(index, "K", "linux")["offset"], "0x8")


class KeyValueBindingTests(unittest.TestCase):
    def test_cs2fow_keys_bind_to_their_generator_symbol(self):
        bindings = VPG.generator_keyvalue_bindings("CS2FOW")
        self.assertEqual(bindings["smoke_storage_offset"], ("server", "SmokeVolume_m_pStorage", "offset"))
        self.assertEqual(bindings["lookup_bone_rva"][2], "func_rva")

    def test_plugin_is_read_from_the_path(self):
        self.assertEqual(VPG.plugin_of("gamedata/14190/CS2FOW/gamedata/cs2fow.games.txt"), "CS2FOW")
        self.assertIsNone(VPG.plugin_of("/tmp/somewhere/file.txt"))

    def test_bound_key_is_checked_against_that_symbol_only(self):
        entries = {"smoke_storage_offset": {"kind": "offset-int", "values": {"linux": 112}}}
        index = {VPG.fold("SmokeVolume_m_pStorage"): {"linux": {"offset": "0x70", "_module": "server"}},
                 VPG.fold("Other_m_x"): {"linux": {"offset": "0x70"}}}

        class NoBinaries:
            def get(self, module, platform):
                return None, None, None

        rows = VPG.check_keyvalue_entries(entries, index, NoBinaries(),
                                          bindings={"smoke_storage_offset": ("server", "SmokeVolume_m_pStorage", "offset")})
        cell = rows[0]["platforms"]["linux"]
        self.assertEqual((cell["status"], cell["resolved"]), ("match", "SmokeVolume_m_pStorage"))


class InstructionValueTests(unittest.TestCase):
    def _blob(self, code):
        blob = b"\xCC" * 16 + code + b"\xCC" * 16
        return blob, {"segs": [(0, 0, len(blob), 0x1)], "base": 0}

    def test_immediate_counts_for_a_struct_size(self):
        blob, info = self._blob(bytes.fromhex("4C6BF270"))           # imul r14, rdx, 0x70
        self.assertEqual(VPG.V.sig_holds_value(blob, info, "4C 6B F2 70", 0x70, allow_imm=True), "ok")
        self.assertEqual(VPG.V.sig_holds_value(blob, info, "4C 6B F2 70", 0x70), "mismatch")

    def test_more_hits_than_allowed_is_ambiguous(self):
        code = bytes.fromhex("488B4738") + b"\xCC" * 4 + bytes.fromhex("488B4738")
        blob, info = self._blob(code)
        self.assertEqual(VPG.V.sig_holds_value(blob, info, "48 8B 47 38", 0x38), "ambiguous")
        self.assertEqual(VPG.V.sig_holds_value(blob, info, "48 8B 47 38", 0x38, max_match=2), "ok")


if __name__ == "__main__":
    unittest.main()
