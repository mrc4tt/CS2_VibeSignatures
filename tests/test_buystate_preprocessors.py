"""Contract tests; MCP and binary identity still require a live IDA session."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(suffix):
    path = ROOT / f"ida_preprocessor_scripts/find-BuyState_{suffix}.py"
    spec = importlib.util.spec_from_file_location(f"buystate_{suffix}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuyStatePreprocessors(unittest.IsolatedAsyncioTestCase):
    async def test_typed_dispatch_and_failure_propagation_on_both_platforms(self):
        for suffix in ("OnUpdate", "DoneBuying", "InitialDelay"):
            module = load(suffix)
            symbol = f"BuyState_{suffix}"
            for platform in ("windows", "linux"):
                for outcome in (False, True):
                    with (
                        self.subTest(symbol=symbol, platform=platform, outcome=outcome),
                        TemporaryDirectory() as folder,
                    ):
                        output = str(Path(folder) / f"{symbol}.{platform}.yaml")
                        old = {output: str(Path(folder) / "prior.yaml")}
                        session = object()
                        with patch.object(module, "preprocess_common_skill", AsyncMock(return_value=outcome)) as common:
                            result = await module.preprocess_skill(
                                session, f"find-{symbol}", [output], old, folder, platform, 0x180000000
                            )
                        self.assertIs(result, outcome)
                        kwargs = common.call_args.kwargs
                        self.assertIs(kwargs["session"], session)
                        self.assertIs(kwargs["old_yaml_map"], old)
                        self.assertEqual(kwargs["expected_outputs"], [output])
                        self.assertEqual(kwargs["platform"], platform)
                        kind = "func" if suffix == "OnUpdate" else "struct_member"
                        self.assertEqual(kwargs[f"{kind}_names"], [symbol])
                        fields = dict(kwargs["generate_yaml_desired_fields"])[symbol]
                        self.assertIn("func_sig" if kind == "func" else "offset_sig", fields)
                        self.assertNotIn("vfunc_index", fields)
                        if kind != "func":
                            self.assertNotIn("func_names", kwargs)
                            self.assertNotIn("func_va", fields)
                        self.assertNotIn("llm_decompile_specs", kwargs)
                        self.assertFalse(Path(output).exists())

    async def test_config_and_retained_skills_match_target_schemas(self):
        config = yaml.safe_load((ROOT / "configs/14178b.yaml").read_text())
        server = next(module for module in config["modules"] if module["name"] == "server")
        for suffix in ("OnUpdate", "DoneBuying", "InitialDelay"):
            symbol = f"BuyState_{suffix}"
            producers = [item for item in server["skills"] if item["name"] == f"find-{symbol}"]
            self.assertEqual(len(producers), 1)
            self.assertEqual(producers[0]["expected_output"], [f"{symbol}.{{platform}}.yaml"])
            entry = next(item for item in server["symbols"] if item["name"] == symbol)
            self.assertEqual(entry["category"], "func" if suffix == "OnUpdate" else "structmember")
            text = (ROOT / f".claude/skills/find-{symbol}/SKILL.md").read_text()
            self.assertEqual(yaml.safe_load(text.split("---", 2)[1])["name"], f"find-{symbol}")
            if suffix != "OnUpdate":
                self.assertIn(f"member_name: {entry['member']}", text)
                self.assertNotIn("Struct-member alternative", text)


if __name__ == "__main__":
    unittest.main()
