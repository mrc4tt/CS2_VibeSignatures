import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from gamesymbol_snapshot_lib.errors import SnapshotConfigError, SnapshotSchemaError


def validate_snapshot_key(key: object) -> str:
    if not isinstance(key, str) or not key:
        raise SnapshotSchemaError("snapshot file path must be a non-empty string")
    if "\\" in key or PureWindowsPath(key).is_absolute():
        raise SnapshotSchemaError(f"snapshot file path must be relative POSIX: {key!r}")
    path = PurePosixPath(key)
    if path.is_absolute() or len(path.parts) < 2:
        raise SnapshotSchemaError(f"snapshot file path must include module and filename: {key!r}")
    if "//" in key or any(part in {"", ".", ".."} for part in path.parts) or not key.endswith(".yaml"):
        raise SnapshotSchemaError(f"unsafe snapshot file path: {key!r}")
    return path.as_posix()


def canonical_key(game_root: Path, artifact_path: str) -> str:
    root = game_root.resolve()
    candidate = Path(artifact_path).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise SnapshotConfigError(f"artifact path escapes gamever root: {artifact_path}") from exc
    key = relative.as_posix()
    try:
        return validate_snapshot_key(key)
    except SnapshotSchemaError as exc:
        raise SnapshotConfigError(str(exc)) from exc


def path_from_key(game_root: Path, key: str) -> Path:
    safe_key = validate_snapshot_key(key)
    root = game_root.resolve()
    candidate = (root / PurePosixPath(safe_key)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SnapshotSchemaError(f"snapshot path escapes target root: {key}") from exc
    return candidate


def is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & 0x400)


def ensure_real_tree(bindir: Path, game_root: Path) -> None:
    for path in (bindir, game_root):
        if path.exists() and is_reparse_point(path):
            raise SnapshotConfigError(f"snapshot target must not be a link/reparse point: {path}")
    resolved_bin = bindir.resolve()
    resolved_game = game_root.resolve()
    try:
        resolved_game.relative_to(resolved_bin)
    except ValueError as exc:
        raise SnapshotConfigError(f"game version root is outside bin directory: {game_root}") from exc


def iter_yaml_paths(game_root: Path):
    if not game_root.exists():
        return
    for current, directories, files in os.walk(game_root, followlinks=False):
        current_path = Path(current)
        for directory in list(directories):
            child = current_path / directory
            if is_reparse_point(child):
                raise SnapshotConfigError(f"refusing to traverse linked directory: {child}")
        for filename in files:
            path = current_path / filename
            if path.suffix.lower() == ".yaml":
                if is_reparse_point(path):
                    raise SnapshotConfigError(f"refusing to read linked YAML: {path}")
                yield path
