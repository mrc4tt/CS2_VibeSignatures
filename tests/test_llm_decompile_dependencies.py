import ast
import posixpath
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import ida_analyze_util
from trusted_yaml import load_yaml_file


def _artifact_key(module_name, artifact_path, platform):
    expanded = artifact_path.replace("{platform}", platform).replace("\\", "/")
    return posixpath.normpath(posixpath.join(module_name, expanded))


class TestLlmDecompileDependencyPolicy(unittest.TestCase):
    @staticmethod
    def _spec(policy=None, references=None):
        spec = {
            "symbol_name": "DynamicTarget",
            "prompt_path": "prompt/call_llm_decompile.md",
            "reference_yaml_paths": references or ["references/required.{platform}.yaml"],
            "expected_result_sections": ["found_call"],
        }
        if policy is not None:
            spec["dependency_policy"] = policy
        return spec

    @staticmethod
    def _write_reference(scripts_dir, name, func_name, platform="windows"):
        reference_path = scripts_dir / "references" / f"{name}.{platform}.yaml"
        reference_path.parent.mkdir(parents=True, exist_ok=True)
        reference_path.write_text(yaml.safe_dump({"func_name": func_name}), encoding="utf-8")
        return reference_path

    def test_schema_requires_non_empty_dependency_policy(self):
        invalid_specs = [
            self._spec(),
            self._spec({}),
            self._spec({"Required.{platform}.yaml": "runtime"}),
            self._spec({"Required.{platform}.yaml": 1}),
            {**self._spec({"Required.{platform}.yaml": "required"}), "dependencies": []},
            {**self._spec({"Required.{platform}.yaml": "required"}), "optional_dependencies": []},
        ]

        for spec in invalid_specs:
            with self.subTest(spec=spec):
                self.assertIsNone(ida_analyze_util._build_llm_decompile_specs_map([spec], debug=True))

    def test_schema_normalizes_required_and_optional_policy(self):
        specs = ida_analyze_util._build_llm_decompile_specs_map(
            [
                self._spec(
                    {
                        "Required.{platform}.yaml": "required",
                        "Optional.{platform}.yaml": "optional",
                    }
                )
            ]
        )

        self.assertEqual(
            {
                "Required.{platform}.yaml": "required",
                "Optional.{platform}.yaml": "optional",
            },
            specs["DynamicTarget"]["dependency_policy"],
        )

    def test_validation_matches_reference_artifacts_and_config_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scripts_dir = temp_path / "scripts"
            binary_dir = temp_path / "server"
            self._write_reference(scripts_dir, "required", "Required")
            self._write_reference(scripts_dir, "optional", "Optional")
            specs = ida_analyze_util._build_llm_decompile_specs_map(
                [
                    self._spec(
                        {
                            "Required.{platform}.yaml": "required",
                            "Optional.{platform}.yaml": "optional",
                        },
                        references=[
                            "references/required.{platform}.yaml",
                            "references/optional.{platform}.yaml",
                        ],
                    )
                ]
            )
            llm_config = {
                "_expected_inputs": [binary_dir / "Required.windows.yaml"],
                "_optional_inputs": [binary_dir / "Optional.windows.yaml"],
            }

            with patch.object(ida_analyze_util, "_get_preprocessor_scripts_dir", return_value=scripts_dir):
                valid = ida_analyze_util._validate_llm_decompile_dependency_policy(
                    specs,
                    llm_config,
                    binary_dir,
                    "windows",
                    debug=True,
                )

        self.assertTrue(valid)

    def test_validation_rejects_reference_policy_set_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scripts_dir = temp_path / "scripts"
            binary_dir = temp_path / "server"
            self._write_reference(scripts_dir, "required", "Required")
            specs = ida_analyze_util._build_llm_decompile_specs_map(
                [
                    self._spec(
                        {
                            "Required.{platform}.yaml": "required",
                            "Extra.{platform}.yaml": "optional",
                        }
                    )
                ]
            )

            with patch.object(ida_analyze_util, "_get_preprocessor_scripts_dir", return_value=scripts_dir):
                valid = ida_analyze_util._validate_llm_decompile_dependency_policy(
                    specs,
                    {
                        "_expected_inputs": [binary_dir / "Required.windows.yaml"],
                        "_optional_inputs": [binary_dir / "Extra.windows.yaml"],
                    },
                    binary_dir,
                    "windows",
                    debug=True,
                )

        self.assertFalse(valid)

    def test_validation_rejects_missing_or_misclassified_config_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scripts_dir = temp_path / "scripts"
            binary_dir = temp_path / "server"
            self._write_reference(scripts_dir, "required", "Required")
            specs = ida_analyze_util._build_llm_decompile_specs_map(
                [self._spec({"Required.{platform}.yaml": "required"})]
            )

            invalid_configs = [
                {"_expected_inputs": [], "_optional_inputs": []},
                {
                    "_expected_inputs": [],
                    "_optional_inputs": [binary_dir / "Required.windows.yaml"],
                },
            ]
            with patch.object(ida_analyze_util, "_get_preprocessor_scripts_dir", return_value=scripts_dir):
                for llm_config in invalid_configs:
                    with self.subTest(llm_config=llm_config):
                        self.assertFalse(
                            ida_analyze_util._validate_llm_decompile_dependency_policy(
                                specs,
                                llm_config,
                                binary_dir,
                                "windows",
                                debug=True,
                            )
                        )

    def test_validation_rejects_overlap_and_basename_ambiguity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scripts_dir = temp_path / "scripts"
            binary_dir = temp_path / "server"
            self._write_reference(scripts_dir, "required", "Required")
            specs = ida_analyze_util._build_llm_decompile_specs_map(
                [self._spec({"Required.{platform}.yaml": "required"})]
            )
            invalid_configs = [
                {
                    "_expected_inputs": [binary_dir / "Required.windows.yaml"],
                    "_optional_inputs": [binary_dir / "Required.windows.yaml"],
                },
                {
                    "_expected_inputs": [
                        binary_dir / "Required.windows.yaml",
                        temp_path / "engine" / "Required.windows.yaml",
                    ],
                    "_optional_inputs": [],
                },
            ]

            with patch.object(ida_analyze_util, "_get_preprocessor_scripts_dir", return_value=scripts_dir):
                for llm_config in invalid_configs:
                    with self.subTest(llm_config=llm_config):
                        self.assertFalse(
                            ida_analyze_util._validate_llm_decompile_dependency_policy(
                                specs,
                                llm_config,
                                binary_dir,
                                "windows",
                                debug=True,
                            )
                        )

    def test_validation_rejects_platform_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scripts_dir = temp_path / "scripts"
            binary_dir = temp_path / "server"
            self._write_reference(scripts_dir, "required", "Required")
            specs = ida_analyze_util._build_llm_decompile_specs_map([self._spec({"Required.linux.yaml": "required"})])

            with patch.object(ida_analyze_util, "_get_preprocessor_scripts_dir", return_value=scripts_dir):
                valid = ida_analyze_util._validate_llm_decompile_dependency_policy(
                    specs,
                    {"_expected_inputs": [binary_dir / "Required.windows.yaml"], "_optional_inputs": []},
                    binary_dir,
                    "windows",
                    debug=True,
                )

        self.assertFalse(valid)


class TestLlmDecompileDependencyPolicyIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_common_validates_policy_before_fast_path(self):
        specs = [
            {
                "symbol_name": "DynamicTarget",
                "prompt_path": "prompt/call_llm_decompile.md",
                "reference_yaml_paths": ["references/reference.{platform}.yaml"],
                "expected_result_sections": ["found_call"],
                "dependency_policy": {"DynamicDependency.{platform}.yaml": "required"},
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scripts_dir = temp_path / "scripts"
            reference_path = scripts_dir / "references" / "reference.windows.yaml"
            reference_path.parent.mkdir(parents=True)
            reference_path.write_text(yaml.safe_dump({"func_name": "DynamicDependency"}), encoding="utf-8")
            output_path = str(temp_path / "DynamicTarget.windows.yaml")
            with (
                patch.object(ida_analyze_util, "_get_preprocessor_scripts_dir", return_value=scripts_dir),
                patch.object(
                    ida_analyze_util,
                    "_validate_llm_decompile_dependency_policy",
                    return_value=False,
                ) as validate_policy,
                patch.object(ida_analyze_util, "preprocess_func_sig_via_mcp") as fast_path,
            ):
                result = await ida_analyze_util.preprocess_common_skill(
                    session="session",
                    expected_outputs=[output_path],
                    old_yaml_map={},
                    new_binary_dir=temp_dir,
                    platform="windows",
                    image_base=0x180000000,
                    func_names=["DynamicTarget"],
                    llm_decompile_specs=specs,
                    llm_config={
                        "model": "test-model",
                        "_expected_inputs": [temp_path / "DynamicDependency.windows.yaml"],
                        "_optional_inputs": [],
                    },
                    generate_yaml_desired_fields=[("DynamicTarget", ["func_name", "func_va"])],
                )

        self.assertFalse(result)
        validate_policy.assert_called_once()
        fast_path.assert_not_called()


class TestRepositoryLlmDecompileDependencyPolicy(unittest.TestCase):
    @staticmethod
    def _literal_llm_specs(script_path):
        tree = ast.parse(script_path.read_text(encoding="utf-8-sig"))
        specs = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            llm_names = [name for name in target_names if name.startswith("LLM_DECOMPILE") or name == "llm_decompile"]
            if not llm_names:
                continue
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                continue
            if isinstance(value, list):
                specs.extend((llm_names[0], spec) for spec in value if isinstance(spec, dict))
        return specs

    @staticmethod
    def _platforms_for_spec(variable_name, skill):
        platforms = [skill["platform"]] if skill.get("platform") else ["windows", "linux"]
        if variable_name.endswith("_WINDOWS"):
            return [platform for platform in platforms if platform == "windows"]
        if variable_name.endswith("_LINUX"):
            return [platform for platform in platforms if platform == "linux"]
        return platforms

    @staticmethod
    def _config_data(config_path):
        config = load_yaml_file(config_path, cache=True, copy_result=False)
        configured = {}
        producers = {"required": {}, "optional": {}}
        for module in config["modules"]:
            module_name = module["name"]
            for skill in module.get("skills", []) or []:
                if not isinstance(skill, dict) or not skill.get("name"):
                    continue
                configured.setdefault(skill["name"], []).append((module_name, skill))
                platforms = [skill["platform"]] if skill.get("platform") else ["windows", "linux"]
                for platform in platforms:
                    for policy, output_key in (("required", "expected_output"), ("optional", "optional_output")):
                        outputs = list(skill.get(output_key, []) or [])
                        outputs.extend(skill.get(f"{output_key}_{platform}", []) or [])
                        for output in outputs:
                            key = _artifact_key(module_name, output, platform)
                            producers[policy].setdefault((platform, key), set()).add(skill["name"])
        return configured, producers

    def test_all_llm_specs_have_complete_policy_and_config_contract(self):
        scripts_dir = Path("ida_preprocessor_scripts")
        config_paths = [Path("configs/14168b.yaml")]

        for config_path in config_paths:
            configured, producers = self._config_data(config_path)
            for script_path in scripts_dir.glob("find-*.py"):
                for module_name, skill in configured.get(script_path.stem, []):
                    for variable_name, spec in self._literal_llm_specs(script_path):
                        symbol_name = spec.get("symbol_name")
                        with self.subTest(config=config_path.name, script=script_path.name, symbol=symbol_name):
                            self.assertNotIn("dependencies", spec)
                            self.assertNotIn("optional_dependencies", spec)
                            policy = spec.get("dependency_policy")
                            self.assertIsInstance(policy, dict)
                            self.assertTrue(policy)
                            self.assertTrue(set(policy.values()) <= {"required", "optional"})

                        for platform in self._platforms_for_spec(variable_name, skill):
                            inferred = set()
                            for reference in spec.get("reference_yaml_paths", []):
                                resolved = reference.replace("{platform}", platform)
                                resolved = resolved.replace("{module}", module_name).replace(
                                    "{module_name}", module_name
                                )
                                reference_path = scripts_dir / resolved
                                with self.subTest(
                                    config=config_path.name,
                                    script=script_path.name,
                                    symbol=symbol_name,
                                    platform=platform,
                                    reference=resolved,
                                ):
                                    self.assertTrue(reference_path.is_file())
                                if not reference_path.is_file():
                                    continue
                                payload = load_yaml_file(reference_path, cache=True, copy_result=False) or {}
                                inferred.add(f"{payload['func_name']}.{platform}.yaml")

                            resolved_policy = {
                                Path(key.replace("{platform}", platform)).name: value for key, value in policy.items()
                            }
                            with self.subTest(
                                config=config_path.name,
                                script=script_path.name,
                                symbol=symbol_name,
                                platform=platform,
                            ):
                                self.assertEqual(inferred, set(resolved_policy))

                            declared = {"required": [], "optional": []}
                            for policy_name, input_key in (
                                ("required", "expected_input"),
                                ("optional", "optional_input"),
                            ):
                                declared[policy_name].extend(skill.get(input_key, []) or [])
                                declared[policy_name].extend(skill.get(f"{input_key}_{platform}", []) or [])

                            declared_by_name = {
                                policy_name: {Path(path.replace("{platform}", platform)).name: path for path in paths}
                                for policy_name, paths in declared.items()
                            }
                            self.assertFalse(set(declared_by_name["required"]) & set(declared_by_name["optional"]))

                            for artifact_name, policy_name in resolved_policy.items():
                                with self.subTest(
                                    config=config_path.name,
                                    script=script_path.name,
                                    symbol=symbol_name,
                                    platform=platform,
                                    artifact=artifact_name,
                                    policy=policy_name,
                                ):
                                    self.assertIn(artifact_name, declared_by_name[policy_name])
                                declared_path = declared_by_name[policy_name].get(artifact_name)
                                if declared_path is None:
                                    continue
                                key = _artifact_key(module_name, declared_path, platform)
                                matching_producers = producers[policy_name].get((platform, key), set())
                                with self.subTest(
                                    config=config_path.name,
                                    script=script_path.name,
                                    symbol=symbol_name,
                                    platform=platform,
                                    producer_key=key,
                                ):
                                    self.assertEqual(1, len(matching_producers))

    def test_execute_queued_deletion_skills_are_split(self):
        scripts_dir = Path("ida_preprocessor_scripts")
        old_name = "find-CEntitySystem_QueueDestroyEntity-AND-CEntitySystem_ExecuteQueuedDeletion-decompiles"
        self.assertFalse((scripts_dir / f"{old_name}.py").exists())

        expected = {
            "find-CEntitySystem_ExecuteQueuedDeletion": (
                "CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml",
                "CEntitySystem_QueueDestroyEntity.{platform}.yaml",
            ),
            "find-CEntitySystem_m_nExecuteQueuedDeletionDepth": (
                "CEntitySystem_m_nExecuteQueuedDeletionDepth.{platform}.yaml",
                "CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml",
            ),
        }
        for skill_name, (output_name, input_name) in expected.items():
            script_path = scripts_dir / f"{skill_name}.py"
            self.assertTrue(script_path.is_file())
            specs = self._literal_llm_specs(script_path)
            self.assertEqual(1, len(specs))
            self.assertEqual({input_name: "required"}, specs[0][1]["dependency_policy"])

            for config_path in Path("configs").glob("*.yaml"):
                configured, _producers = self._config_data(config_path)
                matches = configured.get(skill_name, [])
                self.assertTrue(matches, f"{config_path}: missing {skill_name}")
                for _module_name, skill in matches:
                    self.assertEqual([output_name], skill.get("expected_output"))
                    self.assertEqual([input_name], skill.get("expected_input"))
                self.assertNotIn(old_name, config_path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
