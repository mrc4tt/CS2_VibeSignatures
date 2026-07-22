import ast
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from gamesymbol_snapshot_lib.errors import SnapshotConfigError

PREPROCESSOR_PREFIX = "ida_preprocessor_scripts/"
REFERENCE_PREFIX = f"{PREPROCESSOR_PREFIX}references/"


def workspace_python_sources(repo_root: Path) -> dict[str, str]:
    scripts = repo_root / "ida_preprocessor_scripts"
    sources = {}
    if not scripts.is_dir():
        return sources
    for path in scripts.rglob("*.py"):
        key = path.relative_to(repo_root).as_posix()
        try:
            sources[key] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SnapshotConfigError(f"unable to read analysis source {key}: {exc}") from exc
    return sources


def _parse_source(path: str, source: str, revision: str) -> ast.AST:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise SnapshotConfigError(f"unable to parse {revision} analysis source {path}: {exc}") from exc


def _literal_strings(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = []
        for element in node.elts:
            values.extend(_literal_strings(element))
        return values
    return []


def _reference_templates(tree: ast.AST) -> set[str]:
    templates = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "reference_yaml_paths":
                templates.update(_literal_strings(value))
    return {_normalize_reference_path(template) for template in templates}


def _normalize_reference_path(path: str) -> str:
    normalized = path.replace("\\", "/").removeprefix("./")
    return normalized.removeprefix(PREPROCESSOR_PREFIX)


def _reference_matches(template: str, changed_path: str) -> bool:
    relative = _normalize_reference_path(changed_path)
    if template == relative:
        return True
    return any(template.replace("{platform}", platform) == relative for platform in ("windows", "linux"))


def _imported_preprocessor_names(tree: ast.AST) -> set[str]:
    imported = set()
    prefix = "ida_preprocessor_scripts."
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        for module in modules:
            if module.startswith(prefix):
                imported.add(module.removeprefix(prefix).split(".")[0])
    return imported


def _is_top_level_python(path: str) -> bool:
    pure_path = PurePosixPath(path)
    return pure_path.parent.as_posix() == PREPROCESSOR_PREFIX.rstrip("/") and pure_path.suffix == ".py"


@dataclass(frozen=True)
class AnalysisSourceIndex:
    reference_owners: tuple[tuple[str, str], ...]
    importers: dict[str, frozenset[str]]

    @classmethod
    def build(cls, sources: Mapping[str, str], revision: str) -> "AnalysisSourceIndex":
        reference_owners = []
        importers = defaultdict(set)
        for raw_path, source in sorted(sources.items()):
            path = raw_path.replace("\\", "/").removeprefix("./")
            if not _is_top_level_python(path):
                continue
            tree = _parse_source(path, source, revision)
            stem = PurePosixPath(path).stem
            if stem.startswith("find-"):
                reference_owners.extend((template, stem) for template in _reference_templates(tree))
            for imported in _imported_preprocessor_names(tree):
                importers[imported].add(stem)
        return cls(
            tuple(sorted(reference_owners)),
            {name: frozenset(values) for name, values in sorted(importers.items())},
        )

    def reference_consumers(self, changed_path: str) -> set[str]:
        return {
            skill_name for template, skill_name in self.reference_owners if _reference_matches(template, changed_path)
        }

    def dependent_preprocessors(self, changed_path: str) -> set[str]:
        changed_stem = PurePosixPath(changed_path).stem
        visited = {changed_stem}
        queue = deque([changed_stem])
        while queue:
            for importer in self.importers.get(queue.popleft(), frozenset()):
                if importer not in visited:
                    visited.add(importer)
                    queue.append(importer)
        return {stem for stem in visited if stem.startswith("find-")}
