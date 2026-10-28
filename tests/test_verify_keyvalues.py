"""Valve KeyValues gamedata: comments must not leak keys, and an entry without a library
is scanned in the module its record lives in (cs2-menus' signatures.txt, 14193)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify_plugin_gamedata as VPG  # noqa: E402

CS2_MENUS_SHAPE = '''"Gamedata"
{
    // Every entry: "linux" and "windows" sig (or vtable offset). Written by CS2_VibeSignatures.
    "GetGameTraceManager"
    {
        "linux"                 "48 8B 3D ? ? ? ? E8 ? ? ? ? 5A"
        "windows"               "48 8B 0D ? ? ? ? 4D 8B C6 88 44 24 ?"
    }
    // Search: "CCSPlayerPawnBase::SwitchTeam( %d ) - invalid team index.\\n"
    "SwitchTeam"
    {
        "linux"                 "55 48 89 E5 41 54 49 89 FC 89 F7"
        "windows"               ""
    }
}
'''


class KeyValuesCommentTests(unittest.TestCase):
    def test_quoted_words_in_comments_are_not_keys(self):
        entries, note = VPG.load_gamedata_text(CS2_MENUS_SHAPE)
        self.assertIsNone(note)
        self.assertEqual(sorted(entries), ["GetGameTraceManager", "SwitchTeam"])

    def test_slashes_inside_a_value_survive(self):
        parsed = VPG._parse_kv('"a" { "url" "http://x//y" "empty" "" // "linux" "z"\n "k" "v" }')
        self.assertEqual(parsed, {"a": {"url": "http://x//y", "empty": "", "k": "v"}})


if __name__ == "__main__":
    unittest.main()
