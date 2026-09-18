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
