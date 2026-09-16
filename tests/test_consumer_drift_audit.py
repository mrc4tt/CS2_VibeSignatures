"""Unit tests for consumer_drift_audit (upstream-consumer cross-check of generated gamedata)."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import consumer_drift_audit as cda  # noqa: E402


def _fake_elf(text: bytes, vaddr: int = 0x400000, file_off: int = 0x1000) -> bytes:
    hdr = bytearray(0x40)
    hdr[:4] = b"\x7fELF"
    struct.pack_into("<Q", hdr, 0x20, 0x40)
    struct.pack_into("<HH", hdr, 0x36, 56, 1)
    ph = struct.pack("<IIQQQQQQ", 1, 5, file_off, vaddr, vaddr, len(text), len(text), 0x1000)
    blob = bytearray(hdr + ph)
    blob += b"\0" * (file_off - len(blob))
    blob += text
    return bytes(blob)


class TestParsers(unittest.TestCase):
    def test_json_walker_handles_css_cs2fixes_plugify_shapes(self):
        text = """
        {
          // comment
          "Signatures": {
            "Foo": {"library": "server", "windows": "40 53 ? 48", "linux": "55 48 89 E5"},
          },
          "Offsets": {"Bar": {"windows": 384, "linux": 384}},
          "Patches": {"SomePatch": {"library": "server", "windows": "90 90", "linux": "90 90"}},
          "csgo": {"Signatures": {"Baz::Qux": {"library": "engine2", "win64": "48 89 5C 24 ?", "linuxsteamrt64": "55 48 8D 05 ? ? ? ?"}}}
        }
        """
        out = cda.parse_json_gamedata(text)
        self.assertEqual(out["Foo"]["sig"], {"windows": "40 53 ? 48", "linux": "55 48 89 E5"})
        self.assertEqual(out["Foo"]["library"], "server")
        self.assertEqual(out["Bar"]["offset"], {"windows": 384, "linux": 384})
        self.assertNotIn("SomePatch", out)
        self.assertEqual(out["Baz::Qux"]["library"], "engine2")
        self.assertEqual(out["Baz::Qux"]["sig"]["linux"], "55 48 8D 05 ? ? ? ?")

    def test_keyvalues_parser_and_escaped_wildcards(self):
        text = r"""
        "Games"
        {
            "csgo"
            {
                "Signatures"
                {
                    "CCSPlayerController_SwitchTeam"
                    {
                        "library" "server"
                        "windows" "\x40\x53\x57\x2A\x2A"
                        "linux" "\x55\x48\x89\xE5"
                    }
                }
                "Offsets" { "GameEntitySystem" { "windows" "88" "linux" "80" } }
            }
        }
        """
        out = cda.parse_keyvalues_gamedata(text)
        self.assertEqual(out["CCSPlayerController_SwitchTeam"]["sig"]["windows"], "40 53 57 ? ?")
        self.assertEqual(out["CCSPlayerController_SwitchTeam"]["library"], "server")
        self.assertEqual(out["GameEntitySystem"]["offset"], {"windows": 88, "linux": 80})

    def test_norm_sig_rejects_non_signature_strings(self):
        self.assertIsNone(cda._norm_sig("GetAbsAngles"))
        self.assertIsNone(cda._norm_sig("TODO"))
        self.assertEqual(cda._norm_sig("48 8b 07 ?? 90"), "48 8B 07 ? 90")


class TestGeneratorEnabled(unittest.TestCase):
    def test_reads_module_enabled_flag_textually(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "gamedata.py"), "w", encoding="utf-8") as f:
                f.write("MODULE_NAME = 'x'\nMODULE_ENABLED = False  # fork does not run it\n")
            self.assertFalse(cda.generator_enabled(d))
            with open(os.path.join(d, "gamedata.py"), "w", encoding="utf-8") as f:
                f.write("MODULE_ENABLED = True\n")
            self.assertTrue(cda.generator_enabled(d))
            with open(os.path.join(d, "gamedata.py"), "w", encoding="utf-8") as f:
                f.write("MODULE_NAME = 'x'\n")
            self.assertTrue(cda.generator_enabled(d))


class TestClassify(unittest.TestCase):
    def setUp(self):
        # fnA at +0x00: `55 48 89 E5 ... ret`; thunk at +0x40: `48 89 F8 E8 <rel32 to fnA> ret`; fnC at +0x80.
        text = bytearray(b"\xcc" * 0x100)
        text[0:6] = b"\x55\x48\x89\xe5\x90\xc3"
        rel = 0x00 - (0x40 + 3 + 5)
        text[0x40:0x49] = b"\x48\x89\xf8\xe8" + struct.pack("<i", rel) + b"\xc3"
        text[0x80:0x86] = b"\x40\x53\x48\x83\xec\xc3"
        self.data = _fake_elf(bytes(text))

    def test_same_wrapper_different_stale(self):
        v, _ = cda.classify_sig("55 48 89 E5 90 C3", "55 48 89 E5 90 C3", self.data, "linux")
        self.assertEqual(v, "SAME")
        v, _ = cda.classify_sig("48 89 F8 E8 ? ? ? ? C3", "55 48 89 E5 90 C3", self.data, "linux")
        self.assertEqual(v, "WRAPPER")
        v, _ = cda.classify_sig("40 53 48 83 EC C3", "55 48 89 E5 90 C3", self.data, "linux")
        self.assertEqual(v, "DIFFERENT")
        v, _ = cda.classify_sig("55 48 89 E5 90 C3", "DE AD BE EF 00 11", self.data, "linux")
        self.assertEqual(v, "UPSTREAM_STALE")
        v, _ = cda.classify_sig(None, "55 48 89 E5 90 C3", self.data, "linux")
        self.assertEqual(v, "OURS_MISSING")
        v, _ = cda.classify_sig("CC CC", "55 48 89 E5 90 C3", self.data, "linux")
        self.assertEqual(v, "OURS_AMBIG")
        v, _ = cda.classify_sig("55 48 89 E5 90 C3", "48 89 E5 90 C3", self.data, "linux")
        self.assertEqual(v, "UPSTREAM_MISALIGNED")


if __name__ == "__main__":
    unittest.main()
