import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ida_analyze_util


class TestLlmDecompileDependencies(unittest.TestCase):
    @staticmethod
    def _dynamic_specs():
        specs = []
        specs.append(
            {
                "symbol_name": "DynamicTarget",
                "prompt_path": "prompt/call_llm_decompile.md",
                "reference_yaml_paths": ["references/reference.yaml"],
                "expected_result_sections": ["found_call"],
                "dependencies": ["DynamicDependency.{platform}.yaml"],
            }
        )
        return ida_analyze_util._build_llm_decompile_specs_map(specs)

    def test_dynamic_appended_dependency_accepts_declared_expected_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary_dir = Path(temp_dir) / "server"
            expected_input = binary_dir / "DynamicDependency.windows.yaml"

            valid = ida_analyze_util._validate_llm_decompile_dependencies(
                self._dynamic_specs(),
                llm_config={"_expected_inputs": [expected_input]},
                new_binary_dir=binary_dir,
                platform="windows",
                debug=True,
            )

        self.assertTrue(valid)

    def test_dynamic_appended_dependency_rejects_missing_expected_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = ida_analyze_util._validate_llm_decompile_dependencies(
                self._dynamic_specs(),
                llm_config={"_expected_inputs": []},
                new_binary_dir=Path(temp_dir) / "server",
                platform="windows",
                debug=True,
            )

        self.assertFalse(valid)

    def test_dynamic_spec_without_dependencies_is_rejected(self):
        specs = []
        specs.append(
            {
                "symbol_name": "DynamicTarget",
                "prompt_path": "prompt/call_llm_decompile.md",
                "reference_yaml_paths": ["references/reference.yaml"],
                "expected_result_sections": ["found_call"],
            }
        )

        self.assertIsNone(ida_analyze_util._build_llm_decompile_specs_map(specs))

    def test_empty_dependencies_need_no_expected_input_context(self):
        specs = ida_analyze_util._build_llm_decompile_specs_map(
            [
                {
                    "symbol_name": "IndependentTarget",
                    "prompt_path": "prompt/call_llm_decompile.md",
                    "reference_yaml_paths": ["references/reference.yaml"],
                    "expected_result_sections": ["found_call"],
                    "dependencies": [],
                }
            ]
        )

        self.assertTrue(
            ida_analyze_util._validate_llm_decompile_dependencies(
                specs,
                llm_config=None,
                new_binary_dir=None,
                platform="windows",
                debug=True,
            )
        )


class TestLlmDecompileDependencyIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_common_validates_final_dynamic_specs(self):
        specs = []
        specs.append(
            {
                "symbol_name": "DynamicTarget",
                "prompt_path": "prompt/call_llm_decompile.md",
                "reference_yaml_paths": ["references/reference.yaml"],
                "expected_result_sections": ["found_call"],
                "dependencies": ["DynamicDependency.{platform}.yaml"],
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = str(Path(temp_dir) / "DynamicTarget.windows.yaml")
            with patch.object(
                ida_analyze_util,
                "_validate_llm_decompile_dependencies",
                return_value=False,
            ) as validate_dependencies:
                result = await ida_analyze_util.preprocess_common_skill(
                    session="session",
                    expected_outputs=[output_path],
                    old_yaml_map={},
                    new_binary_dir=temp_dir,
                    platform="windows",
                    image_base=0x180000000,
                    func_names=["DynamicTarget"],
                    llm_decompile_specs=specs,
                    llm_config={"model": "test-model", "_expected_inputs": []},
                    generate_yaml_desired_fields=[
                        ("DynamicTarget", ["func_name", "func_va"]),
                    ],
                )

        self.assertFalse(result)
        normalized_specs = validate_dependencies.call_args.args[0]
        self.assertEqual(
            ["DynamicDependency.{platform}.yaml"],
            normalized_specs["DynamicTarget"]["dependencies"],
        )


if __name__ == "__main__":
    unittest.main()
