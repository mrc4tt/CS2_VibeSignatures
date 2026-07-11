import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "fix-cppheaders" / "SKILL.md"


class TestFixCppHeadersSkill(unittest.TestCase):
    def test_skill_owns_header_fix_workflow(self) -> None:
        content = SKILL_PATH.read_text(encoding="utf-8")
        frontmatter_text = content.split("---", 2)[1]
        frontmatter = yaml.safe_load(frontmatter_text)

        self.assertEqual("fix-cppheaders", frontmatter["name"])
        self.assertIn("Use when", frontmatter["description"])
        self.assertIn("uv run run_cpp_tests.py", content)
        self.assertIn("config.yaml", content)
        self.assertIn("headers", content)
        self.assertIn("hl2sdk_cs2", content)
        self.assertNotIn("-fixheader", content)


if __name__ == "__main__":
    unittest.main()
