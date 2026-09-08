import tempfile
from pathlib import Path
import unittest

import yaml

from preprocessor_coverage import coverage, markdown


class CoverageTests(unittest.TestCase):
    def test_missing_invalid_and_platform_scoping(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "ida_preprocessor_scripts"
            scripts.mkdir()
            (scripts / "ready.py").write_text("async def preprocess_skill(): pass\n")
            (scripts / "broken.py").write_text("def !!!")
            (scripts / "helper.py").write_text("VALUE = 1\n")
            source = root / ".claude/skills/missing"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("Instructions")
            config = root / "config.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "modules": [
                            {
                                "name": "server",
                                "skills": [
                                    {"name": "ready"},
                                    {"name": "missing", "platform": "windows"},
                                    {"name": "absent"},
                                    {"name": "broken"},
                                    {"name": "helper"},
                                ],
                            },
                            {"name": "client", "skills": [{"name": "ready"}]},
                        ]
                    }
                )
            )
            rows = coverage(root, config)
            self.assertEqual(len(rows), 6)
            statuses = {row["skill"]: row["status"] for row in rows}
            self.assertEqual(statuses["ready"], "present")
            self.assertEqual(statuses["missing"], "missing_py")
            self.assertTrue(statuses["broken"].startswith("invalid_python:"))
            self.assertEqual(statuses["helper"], "entrypoint_not_declared")
            self.assertEqual(len(coverage(root, config, "linux")), 5)
            report = markdown(rows, "test")
            self.assertIn("Missing Python: 2", report)
            self.assertIn("Missing Python with SKILL.md: 1", report)
            self.assertIn("NO SKILL.md", report)
            self.assertIn("| client | 1 | 1 | 0 | 0 |", report)


if __name__ == "__main__":
    unittest.main()
