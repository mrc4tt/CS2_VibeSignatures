"""The safe gate and the site history read KeyValues gamedata through parse_keyvalues.

A regex over `"name" { ... }` stopped at the first closing brace: GameBanFix's nested
"Games"/"csgo"/"Signatures" file read as one "Games" key (its first entry lost) and
cs2-menus' first key as "Gamedata".
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autopilot_safe_gate as G  # noqa: E402
import publish_site_data as P  # noqa: E402

NESTED = '''"Games"
{
\t"csgo"
\t{
\t\t"Signatures"
\t\t{
\t\t\t// "Kicking user %s (sv_kick_players_with_cooldown=%d)\\n"
\t\t\t"First"
\t\t\t{
\t\t\t\t"library"\t\t"server"
\t\t\t\t"windows"\t\t"41 54 ?"
\t\t\t\t"linux"\t\t\t"55 48 ?"
\t\t\t}
\t\t\t"Second"
\t\t\t{
\t\t\t\t"library"\t\t"server"
\t\t\t\t"windows"\t\t"48 8D 0D ? ? ? ?"
\t\t\t\t"linux"\t\t\t"48 8D 35 ? ? ? ?"
\t\t\t}
\t\t}
\t}
}
'''

FLAT = '''"Gamedata"
{
\t// Search: "CBaseEntity::SetModel"
\t"SetModel"
\t{
\t\t"linux"\t\t"55 48"
\t\t"windows"\t"40 53"
\t}
\t"Slot"
\t{
\t\t"linux"\t\t"12"
\t\t"windows"\t"11"
\t}
}
'''


class KeyValuesReaderTests(unittest.TestCase):
    def _write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".games.txt", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_nested_games_file(self):
        path = self._write(NESTED)
        self.assertEqual(G.read_keys(path), {
            "First": {"linux": "55 48 ?", "windows": "41 54 ?"},
            "Second": {"linux": "48 8D 35 ? ? ? ?", "windows": "48 8D 0D ? ? ? ?"},
        })
        self.assertEqual(P.read_values(path), {
            "First": ["55 48 ?", "41 54 ?"],
            "Second": ["48 8D 35 ? ? ? ?", "48 8D 0D ? ? ? ?"],
        })

    def test_flat_file_keeps_its_first_key(self):
        path = self._write(FLAT)
        self.assertEqual(sorted(G.read_keys(path)), ["SetModel", "Slot"])
        self.assertEqual(P.read_values(path)["SetModel"], ["55 48", "40 53"])


if __name__ == "__main__":
    unittest.main()
