import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath

from release_workflow_lib.errors import ReleaseWorkflowError

HEX_SHA256_LENGTH = 64
READ_CHUNK_SIZE = 1024 * 1024


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_canonical_json(path: Path, value: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical_json_bytes(value))
    os.replace(temporary, path)


def load_json_object(path: Path) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseWorkflowError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowError(f"unable to read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseWorkflowError(f"JSON top level must be an object: {path}")
    return value


def normalized_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ReleaseWorkflowError(f"path must be a non-empty POSIX relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseWorkflowError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def contained_path(root: Path, *parts: str) -> Path:
    root = Path(os.path.abspath(root))
    target = Path(os.path.abspath(root.joinpath(*parts)))
    resolved_root = root.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ReleaseWorkflowError(f"path escapes root {root}: {target}") from exc
    return target


def _is_reparse_point(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def reject_reparse_points(root: Path) -> None:
    root = Path(root)
    if not root.exists():
        raise ReleaseWorkflowError(f"path does not exist: {root}")
    candidates = [root, *root.rglob("*")]
    for path in candidates:
        try:
            if _is_reparse_point(path):
                raise ReleaseWorkflowError(f"reparse points are not allowed: {path}")
        except OSError as exc:
            raise ReleaseWorkflowError(f"unable to inspect path {path}: {exc}") from exc


def reject_reparse_components(root: Path, target: Path) -> None:
    root = Path(os.path.abspath(root))
    target = Path(os.path.abspath(target))
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowError(f"path escapes root {root}: {target}") from exc
    current = root
    candidates = [root]
    for part in relative.parts:
        current /= part
        candidates.append(current)
    for path in candidates:
        if path.exists() and _is_reparse_point(path):
            raise ReleaseWorkflowError(f"reparse path component is not allowed: {path}")


def file_inventory(root: Path) -> list[dict]:
    root = Path(root)
    reject_reparse_points(root)
    inventory = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = normalized_relative_path(path.relative_to(root).as_posix())
        inventory.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return inventory


def inventory_sha256(inventory: list[dict]) -> str:
    return sha256_bytes(canonical_json_bytes({"files": inventory}))


def verify_inventory(root: Path, expected: list[dict]) -> str:
    actual = file_inventory(root)
    if actual != expected:
        raise ReleaseWorkflowError(f"file inventory mismatch under {root}")
    return inventory_sha256(actual)


def tracked_output_inventory(repo_root: Path, gamever: str) -> list[dict]:
    repo_root = Path(repo_root)
    paths = [repo_root / "gamesymbols" / f"{gamever}.yaml"]
    dist = repo_root / "dist"
    if dist.is_dir():
        paths.extend(sorted(item for item in dist.rglob("*") if item.is_file()))
    inventory = []
    for path in paths:
        if not path.is_file():
            raise ReleaseWorkflowError(f"required tracked output is missing: {path}")
        relative = normalized_relative_path(path.relative_to(repo_root).as_posix())
        inventory.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return inventory


def allowed_output_path(path: str, gamever: str) -> bool:
    path = normalized_relative_path(path)
    return path in {
        f"gamesymbols/{gamever}.yaml",
        f"release-manifests/{gamever}.json",
    } or path.startswith("dist/")


def validate_output_paths(paths: list[str], gamever: str) -> None:
    rejected = [path for path in paths if not allowed_output_path(path, gamever)]
    if rejected:
        raise ReleaseWorkflowError("generated-output PR contains disallowed paths: " + ", ".join(sorted(rejected)))
    required = {f"release-manifests/{gamever}.json"}
    if not required.issubset(paths):
        raise ReleaseWorkflowError(f"generated-output PR must change release-manifests/{gamever}.json")
