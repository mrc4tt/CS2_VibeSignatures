import os
import tempfile
from pathlib import Path

import yaml

from gamesymbol_snapshot_lib.codec import (
    build_snapshot_document,
    canonical_snapshot_bytes,
    canonical_yaml_bytes,
    parse_snapshot_bytes,
)
from gamesymbol_snapshot_lib.config import load_contract
from gamesymbol_snapshot_lib.diff import format_mismatch
from gamesymbol_snapshot_lib.errors import SnapshotMismatchError, SnapshotSchemaError
from gamesymbol_snapshot_lib.paths import (
    canonical_key,
    ensure_real_tree,
    iter_yaml_paths,
    path_from_key,
)


def _load_yaml_mapping(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SnapshotMismatchError(f"unable to read symbol YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SnapshotMismatchError(f"symbol YAML top level must be a mapping: {path}")
    return payload


def _actual_yaml_keys(contract) -> set[str]:
    keys = set()
    for path in iter_yaml_paths(contract.game_root):
        keys.add(canonical_key(contract.game_root, str(path)))
    return keys


def collect_actual_files(contract, strict=True) -> dict[str, dict]:
    missing = [
        path for path in sorted(contract.required_paths) if not path_from_key(contract.game_root, path).is_file()
    ]
    if missing:
        lines = "\n".join(f"  {path}" for path in missing)
        raise SnapshotMismatchError(f"Missing required symbol YAML:\n{lines}")
    actual_keys = _actual_yaml_keys(contract)
    undeclared = sorted(actual_keys - contract.formal_paths)
    if strict and undeclared:
        lines = "\n".join(f"  {path}" for path in undeclared)
        raise SnapshotMismatchError(f"Undeclared symbol YAML:\n{lines}")
    selected = sorted(contract.required_paths | (contract.optional_paths & actual_keys))
    return {path: _load_yaml_mapping(path_from_key(contract.game_root, path)) for path in selected}


def build_actual_document(contract) -> dict:
    return build_snapshot_document(
        contract.game_version,
        contract.config_sha256,
        collect_actual_files(contract, strict=True),
    )


def validate_snapshot_contract(document: dict, contract) -> None:
    if document["config_sha256"] != contract.config_sha256:
        raise SnapshotMismatchError(
            f"snapshot config digest mismatch: snapshot={document['config_sha256']} actual={contract.config_sha256}"
        )
    paths = set(document["files"])
    undeclared = sorted(paths - contract.formal_paths)
    missing = sorted(contract.required_paths - paths)
    if undeclared or missing:
        details = []
        if undeclared:
            details.append("Undeclared in snapshot:\n" + "\n".join(f"  {path}" for path in undeclared))
        if missing:
            details.append("Required missing from snapshot:\n" + "\n".join(f"  {path}" for path in missing))
        raise SnapshotMismatchError("\n\n".join(details))


def load_snapshot_for_contract(snapshot_path, contract, require_canonical=True):
    snapshot_path = Path(snapshot_path)
    try:
        raw = snapshot_path.read_bytes()
    except OSError as exc:
        raise SnapshotMismatchError(f"unable to read snapshot {snapshot_path}: {exc}") from exc
    document = parse_snapshot_bytes(raw, contract.game_version)
    validate_snapshot_contract(document, contract)
    canonical = canonical_snapshot_bytes(document)
    if require_canonical and raw != canonical:
        raise SnapshotMismatchError(f"snapshot is not canonical: {snapshot_path}")
    return document, raw


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def pack_snapshot(game_version, bindir="bin", config_path="config.yaml", snapshot_path=None) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    contract = load_contract(config_path, game_version, bindir)
    document = build_actual_document(contract)
    data = canonical_snapshot_bytes(document)
    reparsed = parse_snapshot_bytes(data, str(game_version))
    validate_snapshot_contract(reparsed, contract)
    if canonical_snapshot_bytes(reparsed) != data:
        raise SnapshotSchemaError("generated snapshot failed canonical self-check")
    _atomic_write(snapshot_path, data)
    return data


def _preflight_default_restore(contract, document: dict) -> None:
    conflicts = []
    for key, expected in document["files"].items():
        target = path_from_key(contract.game_root, key)
        if target.exists() and _load_yaml_mapping(target) != expected:
            conflicts.append(key)
    if conflicts:
        lines = "\n".join(f"  {path}" for path in conflicts)
        raise SnapshotMismatchError(f"Refusing to overwrite different symbol YAML:\n{lines}")


def _delete_yaml_tree(game_root: Path) -> None:
    for path in list(iter_yaml_paths(game_root)):
        path.unlink()


def _write_document_files(contract, document: dict, overwrite: bool) -> None:
    for key, payload in document["files"].items():
        target = path_from_key(contract.game_root, key)
        if target.exists() and not overwrite:
            continue
        _atomic_write(target, canonical_yaml_bytes(payload))


def _round_trip_document(document: dict, game_version: str, config_path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="gamesymbol-snapshot-") as temp_dir:
        bindir = Path(temp_dir) / "bin"
        contract = load_contract(config_path, game_version, bindir)
        ensure_real_tree(bindir, contract.game_root)
        _write_document_files(contract, document, overwrite=True)
        return canonical_snapshot_bytes(build_actual_document(contract))


def restore_snapshot(
    game_version,
    bindir="bin",
    config_path="config.yaml",
    snapshot_path=None,
    replace=False,
) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    contract = load_contract(config_path, game_version, bindir)
    document, raw = load_snapshot_for_contract(snapshot_path, contract, require_canonical=True)
    ensure_real_tree(Path(bindir), contract.game_root)
    if not replace:
        _preflight_default_restore(contract, document)
    else:
        _delete_yaml_tree(contract.game_root)
    _write_document_files(contract, document, overwrite=replace)
    if replace:
        restored = canonical_snapshot_bytes(build_actual_document(contract))
        if restored != raw:
            raise SnapshotMismatchError("restore -replace round-trip did not reproduce the snapshot")
    return raw


def verify_snapshot(game_version, bindir="bin", config_path="config.yaml", snapshot_path=None) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    contract = load_contract(config_path, game_version, bindir)
    document, raw = load_snapshot_for_contract(snapshot_path, contract, require_canonical=True)
    actual_document = build_actual_document(contract)
    actual_bytes = canonical_snapshot_bytes(actual_document)
    if actual_bytes != raw:
        raise SnapshotMismatchError(format_mismatch(document["files"], actual_document["files"]))
    snapshot_round_trip = _round_trip_document(document, str(game_version), config_path)
    if snapshot_round_trip != raw:
        raise SnapshotMismatchError("snapshot restore/pack round-trip is not byte-stable")
    actual_round_trip = _round_trip_document(actual_document, str(game_version), config_path)
    if actual_round_trip != actual_bytes:
        raise SnapshotMismatchError("actual bin pack/restore/pack round-trip is not byte-stable")
    return actual_bytes
