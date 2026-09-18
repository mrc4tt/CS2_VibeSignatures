import ast
import unittest
from pathlib import Path

import ida_analyze_bin
import ida_analyze_util


CONFIG_ROOT = Path("configs")
PREPROCESSOR_ROOT = Path("ida_preprocessor_scripts")


def _assignment_targets(node):
    if isinstance(node, ast.Assign):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _resolve_static_value(value, literals):
    """literal_eval, plus one indirection: NAME[<literal key>] where NAME is a module-level literal.

    Four preprocessors keep their anchors in a FUNC_XREFS_BY_PLATFORM dict because the
    signatures differ per platform, and then expose FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]
    for importers that want one list. That subscript is still statically inspectable -- it just
    is not a literal -- so resolve it rather than making those scripts duplicate their specs.
    """
    try:
        return ast.literal_eval(value)
    except (TypeError, ValueError, SyntaxError):
        pass
    if (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Name)
        and value.value.id in literals
    ):
        container = literals[value.value.id]
        key = ast.literal_eval(value.slice)  # raises for a non-literal key, which is the point
        return container[key]
    raise ValueError("not statically inspectable")


def _literal_assignment(script_path, assignment_name):
    tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
    literals = {}
    for node in tree.body:
        targets = _assignment_targets(node)
        if not targets or node.value is None:
            continue
        if assignment_name not in targets:
            # Remember every module-level literal seen so far, so a later subscript of one
            # (FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]) can be resolved against it.
            try:
                resolved = ast.literal_eval(node.value)
            except (TypeError, ValueError, SyntaxError):
                continue
            for name in targets:
                literals[name] = resolved
            continue
        try:
            return _resolve_static_value(node.value, literals)
        except (TypeError, ValueError, SyntaxError, KeyError, IndexError) as exc:
            raise AssertionError(
                f"{script_path}:{node.lineno}: {assignment_name} must remain statically inspectable"
            ) from exc
    return []


def _required_xref_vtable_artifacts_by_skill():
    dependencies = {}
    for script_path in sorted(PREPROCESSOR_ROOT.glob("find-*.py")):
        relation_map = {
            func_name: vtable_ref
            for func_name, vtable_ref in _literal_assignment(script_path, "FUNC_VTABLE_RELATIONS")
            if ida_analyze_util._is_vtable_artifact_stem(vtable_ref)
        }
        required_artifacts = {
            relation_map[xref_spec.get("func_name")]
            for xref_spec in _literal_assignment(script_path, "FUNC_XREFS")
            if isinstance(xref_spec, dict) and xref_spec.get("func_name") in relation_map
        }
        if required_artifacts:
            dependencies[script_path.stem] = required_artifacts
    return dependencies


def _declared_expected_input_names(skill, platform):
    declared_inputs = list(skill.get("expected_input", []))
    declared_inputs.extend(skill.get(f"expected_input_{platform}", []))
    return {
        str(artifact_path).replace("{platform}", platform).replace("\\", "/").rsplit("/", 1)[-1]
        for artifact_path in declared_inputs
    }


class TestConfigSchedulingDependencies(unittest.TestCase):
    def test_all_configs_have_satisfied_dependency_graphs(self) -> None:
        for config_path in sorted(CONFIG_ROOT.glob("*.yaml")):
            with self.subTest(config=config_path.name):
                modules = ida_analyze_bin.parse_config(config_path)
                gaps = []
                for platform in ("windows", "linux"):
                    gaps.extend(ida_analyze_bin.find_module_skill_dependency_gaps(modules, platform))
                self.assertEqual([], gaps)
                ida_analyze_bin.validate_module_skill_dependencies(modules)

    def test_func_xref_vtable_artifacts_are_declared_as_expected_inputs(self) -> None:
        required_artifacts_by_skill = _required_xref_vtable_artifacts_by_skill()
        missing_declarations = []

        for config_path in sorted(CONFIG_ROOT.glob("*.yaml")):
            for module in ida_analyze_bin.parse_config(config_path):
                for skill in module["skills"]:
                    required_artifacts = required_artifacts_by_skill.get(skill["name"], set())
                    for platform in ("windows", "linux"):
                        if skill.get("platform") not in (None, platform):
                            continue
                        declared_inputs = _declared_expected_input_names(skill, platform)
                        for artifact_stem in sorted(required_artifacts):
                            artifact_name = f"{artifact_stem}.{platform}.yaml"
                            if artifact_name not in declared_inputs:
                                missing_declarations.append(
                                    f"{config_path}:{module['name']}/{skill['name']} "
                                    f"[{platform}] missing expected_input: {artifact_name}"
                                )

        self.assertEqual([], missing_declarations)


if __name__ == "__main__":
    unittest.main()
