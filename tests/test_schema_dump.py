"""schema_dump reads Source 2 schema descriptors statically from the shipped binaries."""
import os
import unittest

import schema_dump

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINUX = os.path.join(REPO, "bin", "14182", "server", "libserver.so")
WINDOWS = os.path.join(REPO, "bin", "14182", "server", "server.dll")


@unittest.skipUnless(os.path.isfile(LINUX) and os.path.isfile(WINDOWS), "needs the 14182 server binaries")
class SchemaDumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.linux = schema_dump.dump_image(LINUX)
        cls.windows = schema_dump.dump_image(WINDOWS)

    def test_both_platforms_read_the_same_schema(self):
        count = lambda classes: sum(len(c["fields"]) for c in classes.values())
        self.assertEqual(count(self.linux), count(self.windows))
        self.assertLess(abs(len(self.linux) - len(self.windows)), 10)

    def test_pawn_chain_and_known_offsets(self):
        self.assertEqual(self.linux["CCSPlayerPawn"]["bases"][0]["name"], "CCSPlayerPawnBase")
        owner, name, start = schema_dump.field_at(self.linux, "CCSPlayerPawn", 2432)
        self.assertEqual((owner, name, start), ("CBaseModelEntity", "m_Glow", 0x980))
        health = {f["name"]: f["offset"] for f in self.linux["CBaseEntity"]["fields"]}["m_iHealth"]
        self.assertEqual(health, 0x5B0)

    def test_no_string_tables_masquerade_as_classes(self):
        self.assertNotIn("Add Money Player", self.linux)
        self.assertNotIn("ASN1_BOOLEAN", self.windows)


if __name__ == "__main__":
    unittest.main()
