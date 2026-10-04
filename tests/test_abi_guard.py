"""Unit tests for abi_guard (ABI-identity guard for sret/ABI-sensitive gamedata symbols)."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import abi_guard  # noqa: E402


def _fake_elf(text: bytes, vaddr: int = 0x1000, file_off: int = 0x1000) -> bytes:
    """Minimal ELF64 with one PT_LOAD segment mapping `text` at vaddr."""
    e_phoff = 0x40
    hdr = bytearray(0x40)
    hdr[:4] = b"\x7fELF"
    struct.pack_into("<Q", hdr, 0x20, e_phoff)
    struct.pack_into("<HH", hdr, 0x36, 56, 1)
    ph = struct.pack("<IIQQQQQQ", 1, 5, file_off, vaddr, vaddr, len(text), len(text), 0x1000)
    blob = bytearray(hdr + ph)
    blob += b"\0" * (file_off - len(blob))
    blob += text
    return bytes(blob)


class TestSigHelpers(unittest.TestCase):
    def test_sig_regex_wildcards(self):
        rx = abi_guard.sig_regex("48 8B ? 90")
        self.assertIsNotNone(rx.match(b"\x48\x8b\x07\x90"))
        self.assertIsNone(rx.match(b"\x48\x8b\x07\x91"))

    def test_to_yaml_sig_uses_double_question_mark(self):
        self.assertEqual(abi_guard.to_yaml_sig("48 ? 8B ??"), "48 ?? 8B ??")


class TestElfMapping(unittest.TestCase):
    def test_roundtrip(self):
        data = _fake_elf(b"\x90" * 64, vaddr=0x400000, file_off=0x1000)
        self.assertEqual(abi_guard.va_to_offset(data, "linux", 0x400010), 0x1010)
        self.assertEqual(abi_guard.offset_to_va(data, "linux", 0x1010), 0x400010)
        self.assertIsNone(abi_guard.va_to_offset(data, "linux", 0x10))


class TestCheckSymbol(unittest.TestCase):
    """End-to-end on a synthetic libserver.so: bad identity is detected and --fix rewrites the yaml."""

    GOOD = bytes.fromhex("488B07 4885C0 7405 488B50".replace(" ", ""))  # NetworkStateChanged good head
    BAD = bytes.fromhex("554889E5 4156 4989F6 4155 4C8D2D".replace(" ", ""))  # known-bad head

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bindir = root / "bin"
        self.artifactdir = root / "bin_artifacts"
        (self.bindir / "14999" / "server").mkdir(parents=True)
        (self.artifactdir / "14999" / "server").mkdir(parents=True)
        # layout: good fn at text+0x00, padding, bad fn at text+0x40, then ret;int3;int3 tails
        text = (
            self.GOOD
            + b"\xc3\xcc\xcc"
            + b"\xcc" * (0x40 - len(self.GOOD) - 3)
            + self.BAD
            + b"\xc3\xcc\xcc"
            + b"\xcc" * 16
        )
        self.text_vaddr = 0x400000
        (self.bindir / "14999" / "server" / "libserver.so").write_bytes(
            _fake_elf(text, vaddr=self.text_vaddr, file_off=0x1000)
        )
        self.rule = abi_guard.ABI_GUARDS["NetworkStateChanged"]["linux"]
        self.yaml = self.artifactdir / "14999" / "server" / "NetworkStateChanged.linux.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, fix: bool):
        return abi_guard.check_symbol(
            "NetworkStateChanged", "linux", self.rule, "14999", str(self.bindir), str(self.artifactdir), fix
        )

    def test_bad_identity_detected_and_fixed(self):
        abi_guard.write_func_yaml(
            str(self.yaml), "NetworkStateChanged", self.text_vaddr + 0x40, "linux", 0, "55 48 89 E5"
        )
        ok, msg = self._run(fix=False)
        self.assertFalse(ok)
        self.assertIn("KNOWN-BAD", msg)

        ok, msg = self._run(fix=True)
        self.assertTrue(ok)
        self.assertIn("FIXED", msg)
        y = abi_guard.read_flat_yaml(str(self.yaml))
        self.assertEqual(int(y["func_va"], 16), self.text_vaddr)
        self.assertEqual(y["func_sig"], abi_guard.to_yaml_sig(self.rule["good_sig"]))

        ok, msg = self._run(fix=False)
        self.assertTrue(ok, msg)

    def _write_vtable(self, entries):
        (self.artifactdir / "14999" / "server" / "CFoo_vtable.linux.yaml").write_text(
            "vtable_class: CFoo\nvtable_entries:\n"
            + "".join(f"  {i}: '{va:#x}'\n" for i, va in entries.items()),
            encoding="utf-8",
        )

    def test_fix_moves_the_vtable_slot_with_the_function(self):
        # vtidx_FinishMove.windows: the wrong function sat in the NEXT slot, and a
        # fix that kept vfunc_* would have shipped the wrong index regardless.
        good, bad = self.text_vaddr, self.text_vaddr + 0x40
        self._write_vtable({38: good, 39: bad})
        abi_guard.write_func_yaml(
            str(self.yaml), "NetworkStateChanged", bad, "linux", 0, "55 48 89 E5",
            {"vtable_name": "CFoo", "vfunc_offset": "0x138", "vfunc_index": "39"},
        )
        ok, msg = self._run(fix=False)
        self.assertFalse(ok)
        self.assertIn("KNOWN-BAD", msg)

        ok, msg = self._run(fix=True)
        self.assertTrue(ok, msg)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("vfunc_index: 38\n", text)
        self.assertIn("vfunc_offset: '0x130'\n", text)
        ok, msg = self._run(fix=False)
        self.assertTrue(ok, msg)

    def test_fix_keeps_a_decimal_index_and_an_unflagged_size(self):
        # A rewrite once turned vfunc_index: 38 into '0x26'. A repair that only
        # adds the sig keeps the size.
        good = self.text_vaddr
        self._write_vtable({38: good})
        self.yaml.write_text(
            f"func_name: NetworkStateChanged\nfunc_va: '{good:#x}'\nfunc_rva: '{good:#x}'\n"
            "func_size: '0xa'\nvtable_name: CFoo\nvfunc_offset: '0x130'\nvfunc_index: 38\n",
            encoding="utf-8",
        )
        ok, msg = self._run(fix=True)
        self.assertIn("no func_sig", msg)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("vfunc_index: 38\n", text)
        self.assertIn("func_size: '0xa'\n", text)

    def test_wrong_slot_on_the_right_function_is_reported(self):
        good = self.text_vaddr
        self._write_vtable({38: good})
        abi_guard.write_func_yaml(
            str(self.yaml), "NetworkStateChanged", good, "linux", 0, self.rule["good_sig"],
            {"vtable_name": "CFoo", "vfunc_offset": "0x138", "vfunc_index": "39"},
        )
        ok, msg = self._run(fix=False)
        self.assertFalse(ok)
        self.assertIn("vfunc_index 39 is not the slot of func_va (38)", msg)

    def test_offset_must_be_eight_times_the_index(self):
        good = self.text_vaddr
        self._write_vtable({38: good})
        abi_guard.write_func_yaml(
            str(self.yaml), "NetworkStateChanged", good, "linux", 0, self.rule["good_sig"],
            {"vtable_name": "CFoo", "vfunc_offset": "0x138", "vfunc_index": "38"},
        )
        ok, msg = self._run(fix=False)
        self.assertFalse(ok)
        self.assertIn("is not 8 x vfunc_index (0x130)", msg)

    def test_any_slot_holding_func_va_is_accepted(self):
        # A slot thunk or a folded body can fill several slots.
        good = self.text_vaddr
        self._write_vtable({38: good, 40: good})
        abi_guard.write_func_yaml(
            str(self.yaml), "NetworkStateChanged", good, "linux", 0, self.rule["good_sig"],
            {"vtable_name": "CFoo", "vfunc_offset": "0x140", "vfunc_index": "40"},
        )
        ok, msg = self._run(fix=False)
        self.assertTrue(ok, msg)

    def test_fix_refuses_when_the_slot_cannot_be_derived(self):
        bad = self.text_vaddr + 0x40
        abi_guard.write_func_yaml(
            str(self.yaml), "NetworkStateChanged", bad, "linux", 0, "55 48 89 E5",
            {"vtable_name": "CFoo", "vfunc_offset": "0x138", "vfunc_index": "39"},
        )
        before = self.yaml.read_text(encoding="utf-8")
        for entries in ({39: bad}, {37: self.text_vaddr, 38: self.text_vaddr}):  # absent / ambiguous
            self._write_vtable(entries)
            ok, msg = self._run(fix=True)
            self.assertFalse(ok)
            self.assertIn("NOT FIXED", msg)
            self.assertEqual(self.yaml.read_text(encoding="utf-8"), before)

    def test_fix_of_a_missing_virtual_writes_its_slot(self):
        self._write_vtable({38: self.text_vaddr})
        rule = {**self.rule, "vtable_name": "CFoo"}
        ok, msg = abi_guard.check_symbol(
            "NetworkStateChanged", "linux", rule, "14999", str(self.bindir), str(self.artifactdir), True
        )
        self.assertTrue(ok, msg)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("vtable_name: CFoo\nvfunc_offset: '0x130'\nvfunc_index: 38\n", text)

    def test_empty_vfunc_index_does_not_crash_the_fix(self):
        good = self.text_vaddr
        self._write_vtable({38: good})
        self.yaml.write_text(
            f"func_name: NetworkStateChanged\nfunc_va: '{good:#x}'\nfunc_rva: '{good:#x}'\n"
            "func_size: '0x0'\nvtable_name: CFoo\nvfunc_offset:\nvfunc_index:\n",
            encoding="utf-8",
        )
        ok, msg = self._run(fix=True)
        self.assertTrue(ok, msg)
        self.assertIn("vfunc_index: 38\n", self.yaml.read_text(encoding="utf-8"))

    def test_missing_yaml_reported(self):
        ok, msg = self._run(fix=False)
        self.assertFalse(ok)
        self.assertIn("missing", msg)

    def test_relocation_verdict_rejects_the_known_bad_head(self):
        """The lock ida_analyze_util puts on a relocation for a NON-virtual symbol.

        A virtual can be constrained by its class vtable; NetworkStateChanged and
        CCSPlayer_MovementServices_FullWalkMove cannot, because neither is
        virtual. Their ABI_GUARDS entry is the only thing that can tell the right
        function from the one relocation keeps landing on, so this is the check
        that stops a bad baseline propagating (rule 21).
        """
        good = self.text_vaddr
        bad = self.text_vaddr + 0x40
        binary_dir = self.bindir / "14999" / "server"

        self.assertEqual(
            abi_guard.relocation_verdict("NetworkStateChanged", "linux", hex(good), str(binary_dir)),
            "ok",
        )
        self.assertEqual(
            abi_guard.relocation_verdict("NetworkStateChanged", "linux", hex(bad), str(binary_dir)),
            "bad",
        )

    def test_relocation_verdict_only_ever_rejects_when_certain(self):
        """Everything unanswerable is 'unknown', so a caller can never bless on it."""
        binary_dir = self.bindir / "14999" / "server"
        # no rule for this symbol
        self.assertEqual(
            abi_guard.relocation_verdict("SomeSymbolWithNoRule", "linux", hex(self.text_vaddr), str(binary_dir)),
            "unknown",
        )
        # an address that maps into no section
        self.assertEqual(
            abi_guard.relocation_verdict("NetworkStateChanged", "linux", "0xdeadbeef", str(binary_dir)),
            "unknown",
        )
        # no binary to read
        self.assertEqual(
            abi_guard.relocation_verdict("NetworkStateChanged", "linux", hex(self.text_vaddr), str(self.bindir / "nope")),
            "unknown",
        )
        # an unparseable address
        self.assertEqual(
            abi_guard.relocation_verdict("NetworkStateChanged", "linux", None, str(binary_dir)),
            "unknown",
        )


if __name__ == "__main__":
    unittest.main()


class TestBoundaryBefore(unittest.TestCase):
    def setUp(self):
        try:
            import capstone  # noqa: F401
        except ImportError:
            self.skipTest("capstone not installed")

    def test_nop_bytes_inside_a_displacement_are_not_padding(self):
        # call [rax+0x890]; ret; int3 int3 - the 90 08 is a displacement, not nops
        code = bytes.fromhex("ff9090080000" "c3" "cccc")
        self.assertEqual(abi_guard.boundary_before(code, 0), 7)

    def test_padding_jumped_past_is_internal_alignment(self):
        # jmp +2 over two int3, then the real end
        code = bytes.fromhex("eb02" "cccc" "c3" "cccc")
        self.assertEqual(abi_guard.boundary_before(code, 0), 5)


class TestReadFlatYaml(unittest.TestCase):
    def test_folded_func_sig_is_read_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "X.windows.yaml"
            path.write_text("func_va: '0x180ae3950'\nfunc_sig: 48 8B C4 0F 29 70 ??\n  48 8B F1\n", encoding="utf-8")
            y = abi_guard.read_flat_yaml(str(path))
        self.assertEqual(y["func_sig"], "48 8B C4 0F 29 70 ?? 48 8B F1")
        self.assertEqual(y["func_va"], "0x180ae3950")


    def test_values_keep_their_yaml_type_and_round_trip(self):
        # It used to render every int as hex, so a rewrite turned vfunc_index: 38
        # into '0x26' and func_sig_allow_across_function_boundary: true into True.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "X.linux.yaml"
            path.write_text(
                "func_name: X\nfunc_va: '0x1000'\nfunc_rva: '0x1000'\nfunc_size: '0x10'\nfunc_sig: 55 48\n"
                "func_sig_allow_across_function_boundary: true\nvtable_name: CFoo\n"
                "vfunc_offset: 0x130\nvfunc_index: 38\nvfunc_sig:\n",
                encoding="utf-8",
            )
            y = abi_guard.read_flat_yaml(str(path))
            self.assertEqual(y["vfunc_index"], 38)
            self.assertIs(y["func_sig_allow_across_function_boundary"], True)
            self.assertEqual(y["vfunc_offset"], 0x130)  # unquoted hex is an int to YAML
            self.assertEqual(y["vfunc_sig"], "")
            abi_guard.write_func_yaml(str(path), "X", 0x1000, "linux", 0x10, "55 48", y)
            text = path.read_text(encoding="utf-8")
        self.assertIn("func_sig_allow_across_function_boundary: true\n", text)
        self.assertIn("vfunc_offset: '0x130'\n", text)
        self.assertIn("vfunc_index: 38\n", text)
        self.assertIn("vfunc_sig: \n", text)


class TestGoodSigHit(unittest.TestCase):
    def test_older_head_in_the_list_is_used_when_the_newest_misses(self):
        data = b"\x00" * 8 + bytes.fromhex("53 41 57 48") + b"\x00" * 8
        rule = {"good_sig": ["53 55 48", "53 41 57 48"]}
        sig, hits = abi_guard.good_sig_hit(rule, data)
        self.assertEqual((sig, hits), ("53 41 57 48", [8]))

    def test_no_unique_sig_reports_the_first(self):
        rule = {"good_sig": ["53 55 48", "53 41 57 48"]}
        sig, hits = abi_guard.good_sig_hit(rule, b"\x00" * 16)
        self.assertEqual((sig, hits), ("53 55 48", []))
