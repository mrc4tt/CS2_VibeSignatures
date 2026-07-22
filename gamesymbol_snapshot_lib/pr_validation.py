from collections import defaultdict, deque
from pathlib import Path
from typing import Mapping

from gamesymbol_snapshot_lib.analysis_sources import (
    AnalysisSourceIndex,
    PREPROCESSOR_PREFIX,
    REFERENCE_PREFIX,
    workspace_python_sources,
)
from gamesymbol_snapshot_lib.codec import snapshot_analysis_output_contract_version
from gamesymbol_snapshot_lib.errors import SnapshotConfigError
from gamesymbol_snapshot_lib.model import ChangedPath, InvalidationPlan

BROAD_ANALYSIS_FILES = {
    ".claude/agents/sig-finder.md",
    ".opencode/agents/sig-finder.md",
}


def _snapshot_delta(base_snapshot: dict, head_snapshot: dict) -> set[str]:
    base_files = base_snapshot.get("files", {})
    head_files = head_snapshot.get("files", {})
    paths = set(base_files) | set(head_files)
    return {path for path in paths if base_files.get(path) != head_files.get(path)}


def _nodes_by_logical(contract):
    grouped = defaultdict(set)
    for node in contract.nodes.values():
        grouped[node.logical_key].add(node.node_id)
    return grouped


def _fingerprints_by_logical(contract):
    grouped = defaultdict(list)
    for node in contract.nodes.values():
        grouped[node.logical_key].append(node.fingerprint)
    return {key: sorted(values) for key, values in grouped.items()}


def _config_changed_logical_keys(base_contract, head_contract) -> set[tuple[str, str, str]]:
    base_fingerprints = _fingerprints_by_logical(base_contract)
    head_fingerprints = _fingerprints_by_logical(head_contract)
    return {
        key
        for key in set(base_fingerprints) | set(head_fingerprints)
        if base_fingerprints.get(key) != head_fingerprints.get(key)
    }


def _config_changed_nodes(base_contract, head_contract) -> set[str]:
    changed_keys = _config_changed_logical_keys(base_contract, head_contract)
    base_groups = _nodes_by_logical(base_contract)
    head_groups = _nodes_by_logical(head_contract)
    return set().union(*(base_groups.get(key, set()) | head_groups.get(key, set()) for key in changed_keys))


def _skill_nodes(contract):
    by_skill = defaultdict(set)
    for node in contract.nodes.values():
        by_skill[node.skill_name].add(node.node_id)
    return by_skill


def _nodes_for_skills(by_skill: Mapping[str, set[str]], skill_names: set[str]) -> set[str]:
    if not skill_names:
        return set()
    return set().union(*(by_skill.get(name, set()) for name in skill_names))


def _normalize_changes(changed_files: list[str | ChangedPath]) -> list[ChangedPath]:
    changes = []
    for changed in changed_files:
        if isinstance(changed, ChangedPath):
            changes.append(changed)
            continue
        path = str(changed).replace("\\", "/").removeprefix("./")
        if path:
            changes.append(ChangedPath("M", path, path))
    return changes


def _base_path(change: ChangedPath) -> str | None:
    return change.old_path if change.status in {"M", "D", "R"} else None


def _head_path(change: ChangedPath) -> str | None:
    return change.new_path if change.status in {"A", "M", "R", "C"} else None


def _is_reference(path: str | None) -> bool:
    return bool(path and path.startswith(REFERENCE_PREFIX) and path.endswith(".yaml"))


def _is_preprocessor(path: str | None) -> bool:
    return bool(path and path.startswith(PREPROCESSOR_PREFIX) and path.endswith(".py"))


def _format_names(names: set[str]) -> str:
    return ",".join(sorted(names)) or "none"


def _reference_change_nodes(
    change: ChangedPath,
    base_index: AnalysisSourceIndex,
    head_index: AnalysisSourceIndex,
    base_by_skill,
    head_by_skill,
) -> tuple[set[str], list[str]]:
    base_path = _base_path(change)
    head_path = _head_path(change)
    base_reference = base_path if _is_reference(base_path) else None
    head_reference = head_path if _is_reference(head_path) else None
    if base_reference is None and head_reference is None:
        return set(), []
    base_consumers = base_index.reference_consumers(base_reference) if base_reference else set()
    head_consumers = head_index.reference_consumers(head_reference) if head_reference else set()
    if head_reference and not head_consumers:
        raise SnapshotConfigError(f"error[orphan_active_reference]: {head_reference} has no HEAD consumer")
    nodes = _nodes_for_skills(base_by_skill, base_consumers)
    nodes.update(_nodes_for_skills(head_by_skill, head_consumers))
    reasons = []
    if base_reference and head_reference and change.status == "R":
        reasons.append(f"reference rename: base {base_reference} -> HEAD {head_reference}")
    elif base_reference and head_reference:
        reasons.append(f"reference modify: {head_reference}")
    elif head_reference:
        action = "copy" if change.status == "C" else "add"
        reasons.append(f"reference {action}: HEAD {head_reference}")
    elif base_consumers:
        reasons.append(f"reference delete: base {base_reference}")
    else:
        action = "renamed" if change.status == "R" else "deleted"
        reasons.append(f"warning: {action} orphan reference had no base consumer: {base_reference}")
    if base_consumers or head_consumers:
        reasons.append(
            f"reference consumers: base={_format_names(base_consumers)}; HEAD={_format_names(head_consumers)}"
        )
    return nodes, reasons


def _preprocessor_change_nodes(
    change: ChangedPath,
    base_index: AnalysisSourceIndex,
    head_index: AnalysisSourceIndex,
    base_by_skill,
    head_by_skill,
    head_contract,
) -> tuple[set[str], list[str]]:
    base_path = _base_path(change)
    head_path = _head_path(change)
    base_source = base_path if _is_preprocessor(base_path) else None
    head_source = head_path if _is_preprocessor(head_path) else None
    if base_source is None and head_source is None:
        return set(), []
    base_skills = base_index.dependent_preprocessors(base_source) if base_source else set()
    head_skills = head_index.dependent_preprocessors(head_source) if head_source else set()
    nodes = _nodes_for_skills(base_by_skill, base_skills)
    nodes.update(_nodes_for_skills(head_by_skill, head_skills))
    if not base_skills and not head_skills:
        path_text = f"base={base_source or 'none'}; HEAD={head_source or 'none'}"
        return set(head_contract.nodes), [f"unmapped analysis source (broad rebuild): {path_text}"]
    paths = [path for path in (base_source, head_source) if path]
    reason = f"preprocessor change: {' -> '.join(dict.fromkeys(paths))}"
    return nodes, [reason]


def _agent_skill_change_nodes(change: ChangedPath, base_by_skill, head_by_skill) -> tuple[set[str], list[str]]:
    nodes = set()
    paths = []
    for path, by_skill in ((_base_path(change), base_by_skill), (_head_path(change), head_by_skill)):
        if not path or not path.startswith(".claude/skills/"):
            continue
        parts = path.split("/")
        if len(parts) >= 3 and parts[2] in by_skill:
            nodes.update(by_skill[parts[2]])
            paths.append(path)
    return nodes, [f"Agent skill change: {' -> '.join(dict.fromkeys(paths))}"] if paths else []


def _source_changed_nodes(
    base_contract,
    head_contract,
    changes: list[ChangedPath],
    base_sources: Mapping[str, str],
    head_sources: Mapping[str, str],
) -> tuple[set[str], list[str]]:
    nodes = set()
    reasons = []
    base_by_skill = _skill_nodes(base_contract)
    head_by_skill = _skill_nodes(head_contract)
    needs_source_index = any(
        _is_reference(change.old_path)
        or _is_reference(change.new_path)
        or _is_preprocessor(change.old_path)
        or _is_preprocessor(change.new_path)
        for change in changes
    )
    empty_index = AnalysisSourceIndex((), {})
    base_index = AnalysisSourceIndex.build(base_sources, "base") if needs_source_index else empty_index
    head_index = AnalysisSourceIndex.build(head_sources, "HEAD") if needs_source_index else empty_index
    for change in changes:
        broad_paths = {path for path in (change.old_path, change.new_path) if path in BROAD_ANALYSIS_FILES}
        if broad_paths:
            nodes.update(head_contract.nodes)
            reasons.extend(f"core analysis change: {path}" for path in sorted(broad_paths))
        reference_nodes, reference_reasons = _reference_change_nodes(
            change, base_index, head_index, base_by_skill, head_by_skill
        )
        preprocessor_nodes, preprocessor_reasons = _preprocessor_change_nodes(
            change, base_index, head_index, base_by_skill, head_by_skill, head_contract
        )
        agent_nodes, agent_reasons = _agent_skill_change_nodes(change, base_by_skill, head_by_skill)
        nodes.update(reference_nodes | preprocessor_nodes | agent_nodes)
        reasons.extend(reference_reasons + preprocessor_reasons + agent_reasons)
    return nodes, reasons


def _dependency_graph(contract) -> dict[str, set[str]]:
    producers = defaultdict(set)
    by_scope_name = defaultdict(set)
    for node in contract.nodes.values():
        for output in node.required_outputs:
            producers[output].add(node.node_id)
        by_scope_name[(node.stage_index, node.module_name, node.platform, node.skill_name)].add(node.node_id)
    consumers = defaultdict(set)
    for node in contract.nodes.values():
        for input_path in node.inputs:
            for producer in producers.get(input_path, set()):
                consumers[producer].add(node.node_id)
        for prerequisite in node.prerequisites:
            key = (node.stage_index, node.module_name, node.platform, prerequisite)
            for producer in by_scope_name.get(key, set()):
                consumers[producer].add(node.node_id)
    return consumers


def _head_seed_nodes(base_contract, head_contract, seed_nodes: set[str]) -> set[str]:
    head_groups = _nodes_by_logical(head_contract)
    logical_by_node = {node.node_id: node.logical_key for node in base_contract.nodes.values()}
    logical_by_node.update({node.node_id: node.logical_key for node in head_contract.nodes.values()})
    head_seeds = {node_id for node_id in seed_nodes if node_id in head_contract.nodes}
    for node_id in seed_nodes:
        head_seeds.update(head_groups.get(logical_by_node.get(node_id), set()))
    return head_seeds


def _closure(graph: dict[str, set[str]], seeds: set[str]) -> set[str]:
    visited = set(seeds)
    queue = deque(seeds)
    while queue:
        for consumer in graph.get(queue.popleft(), set()):
            if consumer not in visited:
                visited.add(consumer)
                queue.append(consumer)
    return visited


def _owners_for_paths(contract, paths: set[str]) -> set[str]:
    owners = set()
    for path in paths:
        owners.update(contract.owners_by_path.get(path, set()))
    return owners


def _outputs_for_nodes(contract, node_ids: set[str]) -> set[str]:
    paths = set()
    for node_id in node_ids:
        node = contract.nodes.get(node_id)
        if node:
            paths.update(node.outputs)
    return paths


def build_invalidation_plan(
    base_contract,
    head_contract,
    base_snapshot: dict,
    head_snapshot: dict,
    changed_files: list[str | ChangedPath],
    repo_root,
    *,
    base_sources: Mapping[str, str] | None = None,
    head_sources: Mapping[str, str] | None = None,
) -> InvalidationPlan:
    repo_root = Path(repo_root)
    changes = _normalize_changes(changed_files)
    if base_sources is None or head_sources is None:
        workspace_sources = workspace_python_sources(repo_root)
        base_sources = workspace_sources if base_sources is None else base_sources
        head_sources = workspace_sources if head_sources is None else head_sources
    delta_paths = _snapshot_delta(base_snapshot, head_snapshot)
    seed_nodes = _owners_for_paths(base_contract, delta_paths)
    seed_nodes.update(_owners_for_paths(head_contract, delta_paths))
    config_keys = _config_changed_logical_keys(base_contract, head_contract)
    config_nodes = _config_changed_nodes(base_contract, head_contract)
    seed_nodes.update(config_nodes)
    base_output_contract_version = snapshot_analysis_output_contract_version(base_snapshot)
    contract_version_changed = base_output_contract_version != head_contract.analysis_output_contract_version
    if contract_version_changed:
        seed_nodes.update(head_contract.nodes)
    source_nodes, source_reasons = _source_changed_nodes(
        base_contract, head_contract, changes, base_sources, head_sources
    )
    seed_nodes.update(source_nodes)
    head_seeds = _head_seed_nodes(base_contract, head_contract, seed_nodes)
    closed_head_nodes = _closure(_dependency_graph(head_contract), head_seeds)
    paths = set(delta_paths)
    paths.update(_outputs_for_nodes(base_contract, seed_nodes))
    paths.update(_outputs_for_nodes(head_contract, closed_head_nodes | seed_nodes))
    reasons = [f"snapshot delta: {len(delta_paths)} path(s)"] if delta_paths else []
    if config_keys:
        reasons.append(f"config delta: {len(config_keys)} logical producer(s)")
    if contract_version_changed:
        reasons.append(
            "analysis output contract version: "
            f"{base_output_contract_version} -> {head_contract.analysis_output_contract_version}"
        )
    reasons.extend(source_reasons)
    closure_count = len(closed_head_nodes - head_seeds)
    if closure_count:
        reasons.append(f"dependency closure: {closure_count} additional producer(s)")
    return InvalidationPlan(frozenset(paths), frozenset(seed_nodes | closed_head_nodes), tuple(reasons))
