import hashlib
import json
from pathlib import Path

import yaml

import ida_analyze_bin
from gamesymbol_snapshot_lib.errors import SnapshotConfigError
from gamesymbol_snapshot_lib.model import SkillNode, SnapshotContract
from gamesymbol_snapshot_lib.paths import canonical_key

PLATFORMS = ("windows", "linux")
SKILL_FIELDS = (
    "name",
    "platform",
    "expected_output",
    "expected_output_windows",
    "expected_output_linux",
    "optional_output",
    "expected_input",
    "expected_input_windows",
    "expected_input_linux",
    "optional_input",
    "optional_input_windows",
    "optional_input_linux",
    "prerequisite",
    "skip_if_exists",
)


def _load_raw_config(config_path: Path) -> dict:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SnapshotConfigError(f"unable to read config {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("modules", []), list):
        raise SnapshotConfigError("analysis config must contain a modules list")
    return raw


def _string_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise SnapshotConfigError(f"{field} must be a list of non-empty strings")
    return list(value)


def _normalized_skill(skill: object, context: str) -> dict:
    if not isinstance(skill, dict):
        raise SnapshotConfigError(f"{context} skill must be a mapping")
    normalized = {}
    for field in SKILL_FIELDS:
        value = skill.get(field)
        if field in {"name", "platform"}:
            if value is not None and not isinstance(value, str):
                raise SnapshotConfigError(f"{context}.{field} must be a string")
            normalized[field] = value
        else:
            normalized[field] = _string_list(value, f"{context}.{field}")
    return normalized


def _normalized_contract(raw: dict) -> list[dict]:
    modules = []
    for stage_index, module in enumerate(raw.get("modules", [])):
        if not isinstance(module, dict):
            raise SnapshotConfigError(f"modules[{stage_index}] must be a mapping")
        name = module.get("name")
        if not isinstance(name, str) or not name:
            raise SnapshotConfigError(f"modules[{stage_index}].name must be a non-empty string")
        entry = {"stage_index": stage_index, "name": name}
        for platform in PLATFORMS:
            field = f"path_{platform}"
            value = module.get(field)
            if value is not None and not isinstance(value, str):
                raise SnapshotConfigError(f"modules[{stage_index}].{field} must be a string")
            entry[field] = {"present": field in module, "value": value}
        skills = module.get("skills", []) or []
        if not isinstance(skills, list):
            raise SnapshotConfigError(f"modules[{stage_index}].skills must be a list")
        entry["skills"] = [
            _normalized_skill(skill, f"modules[{stage_index}].skills[{index}]") for index, skill in enumerate(skills)
        ]
        modules.append(entry)
    return modules


def _digest(normalized: list[dict]) -> str:
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _resolved_keys(binary_dir: Path, paths: list[str], platform: str, game_root: Path) -> frozenset[str]:
    resolved = []
    for path in paths:
        artifact = ida_analyze_bin.resolve_artifact_path(str(binary_dir), path, platform)
        key = canonical_key(game_root, artifact)
        if key.endswith(".yaml"):
            resolved.append(key)
    return frozenset(resolved)


def _make_node(module: dict, skill: dict, skill_index: int, platform: str, game_root: Path) -> SkillNode:
    binary_dir = game_root / module["name"]
    required, optional, _combined = ida_analyze_bin.expand_skill_output_paths(str(binary_dir), skill, platform)
    required_keys = frozenset(canonical_key(game_root, path) for path in required if path.endswith(".yaml"))
    optional_keys = frozenset(canonical_key(game_root, path) for path in optional if path.endswith(".yaml"))
    input_paths = list(skill.get("expected_input", []) or [])
    input_paths += list(skill.get(f"expected_input_{platform}", []) or [])
    input_paths += list(skill.get("optional_input", []) or [])
    input_paths += list(skill.get(f"optional_input_{platform}", []) or [])
    inputs = _resolved_keys(binary_dir, input_paths, platform, game_root)
    node_id = f"{module['stage_index']}:{skill_index}:{module['name']}:{platform}:{skill['name']}"
    fingerprint_data = {
        "stage_index": module["stage_index"],
        "module_name": module["name"],
        "path_windows": module.get("path_windows"),
        "path_linux": module.get("path_linux"),
        "skill_index": skill_index,
        "skill": {field: skill.get(field) for field in SKILL_FIELDS},
        "platform": platform,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SkillNode(
        node_id,
        (module["name"], skill["name"], platform),
        module["stage_index"],
        module["name"],
        skill["name"],
        platform,
        required_keys,
        optional_keys,
        inputs,
        tuple(skill.get("prerequisite", []) or []),
        fingerprint,
    )


def _collect_nodes(modules: list[dict], game_root: Path) -> dict[str, SkillNode]:
    nodes = {}
    for module in modules:
        for platform in PLATFORMS:
            if not module.get(f"path_{platform}"):
                continue
            for skill_index, skill in enumerate(module.get("skills", []) or []):
                if not ida_analyze_bin._skill_runs_on_platform(skill, platform):
                    continue
                node = _make_node(module, skill, skill_index, platform, game_root)
                nodes[node.node_id] = node
    return nodes


def _collect_paths(nodes: dict[str, SkillNode]):
    required = set()
    optional = set()
    owners = {}
    case_spellings = {}
    for node in nodes.values():
        for path in node.outputs:
            prior = case_spellings.setdefault(path.casefold(), path)
            if prior != path:
                raise SnapshotConfigError(f"case-insensitive artifact collision: {prior} and {path}")
            owners.setdefault(path, set()).add(node.node_id)
        required.update(node.required_outputs)
        optional.update(node.optional_outputs)
    optional.difference_update(required)
    frozen_owners = {path: frozenset(node_ids) for path, node_ids in owners.items()}
    return frozenset(required), frozenset(optional), frozen_owners


def load_contract(config_path, game_version, bindir) -> SnapshotContract:
    config_path = Path(config_path)
    bindir = Path(bindir)
    game_version = str(game_version)
    raw = _load_raw_config(config_path)
    normalized = _normalized_contract(raw)
    try:
        modules = ida_analyze_bin.parse_config(str(config_path))
        nodes = _collect_nodes(modules, bindir / game_version)
    except (OSError, ValueError, TypeError) as exc:
        raise SnapshotConfigError(f"invalid analysis contract: {exc}") from exc
    required, optional, owners = _collect_paths(nodes)
    return SnapshotContract(
        game_version,
        bindir / game_version,
        _digest(normalized),
        required,
        optional,
        owners,
        nodes,
    )
