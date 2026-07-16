import ast
from collections import defaultdict, deque
from pathlib import Path

from gamesymbol_snapshot_lib.model import InvalidationPlan

CORE_ANALYSIS_FILES = {
    "agent_runner.py",
    "ida_analyze_bin.py",
    "ida_analyze_util.py",
    "ida_llm_decompile.py",
    "ida_llm_utils.py",
    "ida_skill_preprocessor.py",
}
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


def _config_changed_nodes(base_contract, head_contract) -> set[str]:
    base_fingerprints = _fingerprints_by_logical(base_contract)
    head_fingerprints = _fingerprints_by_logical(head_contract)
    changed_keys = {
        key
        for key in set(base_fingerprints) | set(head_fingerprints)
        if base_fingerprints.get(key) != head_fingerprints.get(key)
    }
    base_groups = _nodes_by_logical(base_contract)
    head_groups = _nodes_by_logical(head_contract)
    return set().union(*(base_groups.get(key, set()) | head_groups.get(key, set()) for key in changed_keys))


def _skill_nodes(head_contract):
    by_skill = defaultdict(set)
    for node in head_contract.nodes.values():
        by_skill[node.skill_name].add(node.node_id)
    return by_skill


def _python_importers(repo_root: Path) -> dict[str, set[str]]:
    importers = defaultdict(set)
    scripts = repo_root / "ida_preprocessor_scripts"
    for path in scripts.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                prefix = "ida_preprocessor_scripts."
                if module.startswith(prefix):
                    imported = module.removeprefix(prefix).split(".")[0]
                    importers[imported].add(path.stem)
    return importers


def _dependent_preprocessors(repo_root: Path, changed_stem: str) -> set[str]:
    importers = _python_importers(repo_root)
    visited = {changed_stem}
    queue = deque([changed_stem])
    while queue:
        for importer in importers.get(queue.popleft(), set()):
            if importer not in visited:
                visited.add(importer)
                queue.append(importer)
    return {stem for stem in visited if stem.startswith("find-")}


def _reference_consumers(repo_root: Path, changed_path: str) -> set[str]:
    prefix = "ida_preprocessor_scripts/"
    relative = changed_path.removeprefix(prefix)
    templates = {relative}
    for platform in ("windows", "linux"):
        templates.add(relative.replace(f".{platform}.yaml", ".{platform}.yaml"))
    consumers = set()
    for path in (repo_root / "ida_preprocessor_scripts").glob("find-*.py"):
        try:
            source = path.read_text(encoding="utf-8").replace("\\", "/")
        except (OSError, UnicodeError):
            continue
        if any(template in source for template in templates):
            consumers.add(path.stem)
    return consumers


def _source_changed_nodes(head_contract, changed_files: list[str], repo_root: Path) -> tuple[set[str], list[str]]:
    nodes = set()
    reasons = []
    by_skill = _skill_nodes(head_contract)
    for raw_path in changed_files:
        path = raw_path.replace("\\", "/")
        if path == f"configs/{head_contract.game_version}.yaml":
            nodes.update(head_contract.nodes)
            reasons.append(f"active analysis config change: {path}")
        elif path in CORE_ANALYSIS_FILES or path in BROAD_ANALYSIS_FILES:
            nodes.update(head_contract.nodes)
            reasons.append(f"core analysis change: {path}")
        elif path.startswith("ida_preprocessor_scripts/references/") and path.endswith(".yaml"):
            skill_names = _reference_consumers(repo_root, path)
            matched = set().union(*(by_skill.get(name, set()) for name in skill_names)) if skill_names else set()
            if matched:
                nodes.update(matched)
                reasons.append(f"reference change: {path}")
            else:
                nodes.update(head_contract.nodes)
                reasons.append(f"unmapped analysis reference (broad rebuild): {path}")
        elif path.startswith("ida_preprocessor_scripts/") and path.endswith(".py"):
            skill_names = _dependent_preprocessors(repo_root, Path(path).stem)
            matched = set().union(*(by_skill.get(name, set()) for name in skill_names)) if skill_names else set()
            if matched:
                nodes.update(matched)
                reasons.append(f"preprocessor change: {path}")
            else:
                nodes.update(head_contract.nodes)
                reasons.append(f"unmapped analysis source (broad rebuild): {path}")
        elif path.startswith(".claude/skills/"):
            parts = path.split("/")
            if len(parts) >= 3 and parts[2] in by_skill:
                nodes.update(by_skill[parts[2]])
                reasons.append(f"Agent skill change: {path}")
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
    changed_files: list[str],
    repo_root,
) -> InvalidationPlan:
    repo_root = Path(repo_root)
    delta_paths = _snapshot_delta(base_snapshot, head_snapshot)
    seed_nodes = _owners_for_paths(base_contract, delta_paths)
    seed_nodes.update(_owners_for_paths(head_contract, delta_paths))
    config_nodes = _config_changed_nodes(base_contract, head_contract)
    seed_nodes.update(config_nodes)
    source_nodes, source_reasons = _source_changed_nodes(head_contract, changed_files, repo_root)
    seed_nodes.update(source_nodes)
    head_seeds = _head_seed_nodes(base_contract, head_contract, seed_nodes)
    closed_head_nodes = _closure(_dependency_graph(head_contract), head_seeds)
    paths = set(delta_paths)
    paths.update(_outputs_for_nodes(base_contract, seed_nodes))
    paths.update(_outputs_for_nodes(head_contract, closed_head_nodes | seed_nodes))
    reasons = [f"snapshot delta: {len(delta_paths)} path(s)"] if delta_paths else []
    if config_nodes:
        reasons.append(f"config delta: {len(config_nodes)} producer(s)")
    reasons.extend(source_reasons)
    return InvalidationPlan(frozenset(paths), frozenset(seed_nodes | closed_head_nodes), tuple(reasons))
