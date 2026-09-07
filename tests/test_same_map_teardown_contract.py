"""Exercise the skill's executable entry guard and the runtime interior-VA check."""

from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
import ida_analyze_bin


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude/skills/find-CCSGameRules_SameMapTeardown/SKILL.md"


class SkillEntryGuardTests(unittest.TestCase):
    def guard(self, function):
        code = re.search(r"```python\n(.*?)```", SKILL.read_text(), re.S).group(1)
        namespace = {}
        with patch.dict(
            sys.modules,
            {
                "ida_funcs": SimpleNamespace(get_func=lambda ea: function),
                "ida_nalt": SimpleNamespace(get_imagebase=lambda: 0x180000000),
            },
        ):
            exec(compile(code, str(SKILL), "exec"), namespace)
        return namespace["checked_function_metadata"]

    def test_logged_interior_address_is_not_silently_rounded(self):
        function = SimpleNamespace(start_ea=0x1808E19C0, size=lambda: 0x2000)
        with self.assertRaisesRegex(ValueError, "inside function 0x1808e19c0"):
            self.guard(function)(0x1808E32E0)

    def test_metadata_is_recomputed_from_verified_entry(self):
        function = SimpleNamespace(start_ea=0x1808E19C0, size=lambda: 0x2000)
        data = self.guard(function)(function.start_ea)
        self.assertEqual(data["func_va"], "0x1808e19c0")
        self.assertEqual(data["func_rva"], "0x8e19c0")
        self.assertEqual(data["func_size"], "0x2000")
        self.assertNotIn("func_sig", data)

    def test_undefined_function_fails(self):
        with self.assertRaisesRegex(ValueError, "No defined function"):
            self.guard(None)(0x1808E32E0)

    def test_frontmatter_is_valid_yaml(self):
        frontmatter = yaml.safe_load(SKILL.read_text().split("---", 2)[1])
        self.assertEqual(frontmatter["name"], "find-CCSGameRules_SameMapTeardown")


class RuntimeEntryValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_logged_address_is_rejected_without_rewriting_artifact(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "CCSGameRules_SameMapTeardown.windows.yaml"
            original = "func_name: CCSGameRules_SameMapTeardown\nfunc_va: '0x1808e32e0'\n"
            path.write_text(original)
            with (
                patch.object(ida_analyze_bin, "_lookup_expected_input_artifact_category", return_value="func"),
                patch.object(
                    ida_analyze_bin,
                    "_inspect_func_va_via_session",
                    AsyncMock(
                        return_value={
                            "has_segment": True,
                            "segment_name": ".text",
                            "has_function": True,
                            "is_function_start": False,
                            "function_start": "0x1808e19c0",
                        }
                    ),
                ),
            ):
                issues = await ida_analyze_bin.validate_expected_input_artifacts_via_session(
                    session=MagicMock(),
                    expected_inputs=[str(path)],
                    platform="windows",
                    debug=False,
                )
            self.assertEqual(len(issues), 1)
            self.assertIn(
                "func_va=0x1808e32e0 resolves inside function 0x1808e19c0 instead of a function start", issues[0]
            )
            self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
