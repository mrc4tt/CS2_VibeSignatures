"""Regression coverage for CCSBot::Profile's configured member-offset contract."""

from pathlib import Path
import unittest

import yaml

from ida_analyze_bin import _artifact_symbol_category_map_from_document
from ida_analyze_util import SymbolArtifactError, canonical_symbol_yaml_bytes


ROOT = Path(__file__).resolve().parents[1]


class CCSBotProfileContractTests(unittest.TestCase):
    def test_configs_accept_member_payload_and_reject_function_payload(self):
        # Synthetic bytes/offset exercise the schema only, not live CS2 evidence.
        member_payload = {
            "struct_name": "CCSBot",
            "member_name": "m_profile",
            "offset": "0x88",
            "size": 8,
            "offset_sig": "48 8B 81 88 00 00 00",
        }
        for version in ("14178", "14178b"):
            with self.subTest(version=version):
                document = yaml.safe_load((ROOT / "configs" / f"{version}.yaml").read_text())
                symbols = [
                    symbol
                    for module in document["modules"]
                    for symbol in module.get("symbols", [])
                    if symbol["name"] == "CCSBot_Profile"
                ]
                self.assertEqual(len(symbols), 1)
                self.assertEqual(symbols[0]["struct"], "CCSBot")
                self.assertEqual(symbols[0]["member"], "m_profile")
                self.assertIn("CCSBot::Profile", symbols[0]["alias"])
                category = _artifact_symbol_category_map_from_document(document)["CCSBot_Profile"]
                self.assertEqual(category, "structmember")
                normalized = yaml.safe_load(canonical_symbol_yaml_bytes(member_payload, category=category))
                self.assertEqual(normalized, member_payload)
                with self.assertRaises(SymbolArtifactError):
                    canonical_symbol_yaml_bytes({"func_name": "CCSBot_Profile", "func_va": "0x1234"}, category=category)

    def test_original_failure_is_category_mismatch_without_mixed_fields(self):
        with self.assertRaisesRegex(SymbolArtifactError, "vfunc artifact has unknown fields"):
            canonical_symbol_yaml_bytes(
                {
                    "struct_name": "CCSBot",
                    "member_name": "m_profile",
                    "offset": "0x88",
                    "size": 8,
                    "offset_sig": "48 8B 81 88 00 00 00",
                },
                category="vfunc",
            )

    def test_skill_frontmatter_parses_and_forbids_schema_switch(self):
        text = (ROOT / ".claude/skills/find-CCSBot_Profile/SKILL.md").read_text()
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(frontmatter["name"], "find-CCSBot_Profile")
        self.assertTrue(frontmatter["disable-model-invocation"])
        self.assertIn("member_name: m_profile", text)
        self.assertIn("Do not switch output schema", text)
        self.assertNotIn("Struct-member alternative", text)


if __name__ == "__main__":
    unittest.main()
