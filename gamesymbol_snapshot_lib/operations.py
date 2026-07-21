import logging
import os
import tempfile
from pathlib import Path

import yaml

from analysis_output_contract import ANALYSIS_OUTPUT_CONTRACT_MISMATCH_REASON
from analysis_config import resolve_analysis_config
from gamesymbol_snapshot_lib.codec import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_2_VERSION,
    SCHEMA_VERSION,
    build_snapshot_document,
    canonical_snapshot_bytes,
    canonical_yaml_bytes,
    parse_snapshot_bytes,
    snapshot_analysis_output_contract_version,
    snapshot_config_digest_version,
)
from gamesymbol_snapshot_lib.config import (
    LATEST_CONFIG_DIGEST_VERSION,
    load_contract,
    load_unversioned_schema1_contract,
)
from gamesymbol_snapshot_lib.diff import format_mismatch
from gamesymbol_snapshot_lib.errors import (
    SnapshotMismatchError,
    SnapshotSchemaError,
    SnapshotUntrustedError,
)
from gamesymbol_snapshot_lib.model import SnapshotContext
from gamesymbol_snapshot_lib.paths import canonical_key, ensure_real_tree, iter_yaml_paths, path_from_key


LOGGER = logging.getLogger(__name__)


def _load_yaml_mapping(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SnapshotMismatchError(f"unable to read symbol YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SnapshotMismatchError(f"symbol YAML top level must be a mapping: {path}")
    return payload


def _actual_yaml_keys(contract) -> set[str]:
    return {canonical_key(contract.game_root, str(path)) for path in iter_yaml_paths(contract.game_root)}


def collect_actual_files(contract, strict=True) -> dict[str, dict]:
    missing = [
        path for path in sorted(contract.required_paths) if not path_from_key(contract.game_root, path).is_file()
    ]
    if missing:
        lines = "\n".join(f"  {path}" for path in missing)
        raise SnapshotMismatchError(f"Missing required symbol YAML:\n{lines}")
    actual_keys = _actual_yaml_keys(contract)
    undeclared = sorted(actual_keys - contract.formal_paths)
    if undeclared:
        lines = "\n".join(f"  {path}" for path in undeclared)
        if strict:
            raise SnapshotMismatchError(f"Undeclared symbol YAML:\n{lines}")
        LOGGER.warning("WARNING: Ignoring undeclared symbol YAML:\n%s", lines)
    selected = sorted(contract.required_paths | (contract.optional_paths & actual_keys))
    return {path: _load_yaml_mapping(path_from_key(contract.game_root, path)) for path in selected}


def _schema_for_digest(config_digest_version: int) -> int:
    return LEGACY_SCHEMA_VERSION if config_digest_version == 1 else SCHEMA_VERSION


def build_actual_document(contract, *, strict: bool = False, schema_version: int | None = None) -> dict:
    schema_version = schema_version or _schema_for_digest(contract.config_digest_version)
    return build_snapshot_document(
        contract.game_version,
        contract.config_sha256,
        collect_actual_files(contract, strict=strict),
        schema_version=schema_version,
        config_digest_version=contract.config_digest_version,
        analysis_output_contract_version=contract.analysis_output_contract_version,
    )


def _validate_snapshot_paths(document: dict, contract) -> None:
    paths = set(document["files"])
    undeclared = sorted(paths - contract.formal_paths)
    missing = sorted(contract.required_paths - paths)
    if undeclared or missing:
        details = []
        if undeclared:
            details.append("Undeclared in snapshot:\n" + "\n".join(f"  {path}" for path in undeclared))
        if missing:
            details.append("Required missing from snapshot:\n" + "\n".join(f"  {path}" for path in missing))
        raise SnapshotMismatchError("\n\n".join(details), reason="snapshot_contract_mismatch")


def validate_snapshot_contract(document: dict, contract) -> None:
    document_digest_version = snapshot_config_digest_version(document)
    if document_digest_version != contract.config_digest_version:
        raise SnapshotMismatchError(
            "snapshot config digest version mismatch: "
            f"snapshot={document_digest_version} actual={contract.config_digest_version}",
            reason="config_digest_mismatch",
        )
    if document["config_sha256"] != contract.config_sha256:
        raise SnapshotMismatchError(
            f"snapshot config digest mismatch: snapshot={document['config_sha256']} actual={contract.config_sha256}",
            reason="config_digest_mismatch",
        )
    document_output_contract_version = snapshot_analysis_output_contract_version(document)
    if document_output_contract_version != contract.analysis_output_contract_version:
        raise SnapshotMismatchError(
            "snapshot analysis output contract version mismatch: "
            f"snapshot={document_output_contract_version} "
            f"actual={contract.analysis_output_contract_version}",
            reason=ANALYSIS_OUTPUT_CONTRACT_MISMATCH_REASON,
        )
    _validate_snapshot_paths(document, contract)


def _read_snapshot(snapshot_path: Path) -> bytes:
    try:
        return snapshot_path.read_bytes()
    except OSError as exc:
        raise SnapshotMismatchError(f"unable to read snapshot {snapshot_path}: {exc}") from exc


def load_snapshot_for_contract(snapshot_path, contract, require_canonical=True):
    snapshot_path = Path(snapshot_path)
    raw = _read_snapshot(snapshot_path)
    document = parse_snapshot_bytes(raw, contract.game_version)
    validate_snapshot_contract(document, contract)
    canonical = canonical_snapshot_bytes(document)
    if require_canonical and raw != canonical:
        raise SnapshotMismatchError(
            f"snapshot is not canonical: {snapshot_path}",
            reason="noncanonical_snapshot",
        )
    return document, raw


def load_snapshot_context(snapshot_path, config_path, game_version, bindir, require_canonical=True) -> SnapshotContext:
    snapshot_path = Path(snapshot_path)
    raw = _read_snapshot(snapshot_path)
    document = parse_snapshot_bytes(raw, str(game_version))
    digest_version = snapshot_config_digest_version(document)
    contract = load_contract(config_path, game_version, bindir, digest_version)
    validate_snapshot_contract(document, contract)
    if require_canonical and raw != canonical_snapshot_bytes(document):
        raise SnapshotMismatchError(
            f"snapshot is not canonical: {snapshot_path}",
            reason="noncanonical_snapshot",
        )
    return SnapshotContext(document, raw, contract)


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


def pack_snapshot(game_version, bindir="bin", config_path=None, snapshot_path=None) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    config_path = resolve_analysis_config(game_version, config_path)
    contract = load_contract(config_path, game_version, bindir, LATEST_CONFIG_DIGEST_VERSION)
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
    digest_version = snapshot_config_digest_version(document)
    with tempfile.TemporaryDirectory(prefix="gamesymbol-snapshot-") as temp_dir:
        bindir = Path(temp_dir) / "bin"
        contract = load_contract(config_path, game_version, bindir, digest_version)
        ensure_real_tree(bindir, contract.game_root)
        _write_document_files(contract, document, overwrite=True)
        actual = build_actual_document(contract, schema_version=document["schema_version"])
        return canonical_snapshot_bytes(actual)


def check_snapshot_contract(game_version, bindir="bin", config_path=None, snapshot_path=None) -> SnapshotContext:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    config_path = resolve_analysis_config(game_version, config_path)
    try:
        context = load_snapshot_context(snapshot_path, config_path, game_version, bindir, require_canonical=True)
    except SnapshotSchemaError as exc:
        raise SnapshotUntrustedError(exc.reason, str(exc)) from exc
    except SnapshotMismatchError as exc:
        if exc.reason is None:
            raise
        raise SnapshotUntrustedError(exc.reason, str(exc)) from exc
    round_trip = _round_trip_document(context.document, str(game_version), config_path)
    if round_trip != context.raw_bytes:
        raise SnapshotUntrustedError(
            "snapshot_round_trip_mismatch",
            "snapshot restore/pack round-trip is not byte-stable",
        )
    return context


def restore_snapshot(game_version, bindir="bin", config_path=None, snapshot_path=None, replace=False) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    config_path = resolve_analysis_config(game_version, config_path)
    context = load_snapshot_context(snapshot_path, config_path, game_version, bindir, require_canonical=True)
    ensure_real_tree(Path(bindir), context.contract.game_root)
    if not replace:
        _preflight_default_restore(context.contract, context.document)
    else:
        _delete_yaml_tree(context.contract.game_root)
    _write_document_files(context.contract, context.document, overwrite=replace)
    if replace:
        restored = canonical_snapshot_bytes(
            build_actual_document(context.contract, schema_version=context.document["schema_version"])
        )
        if restored != context.raw_bytes:
            raise SnapshotMismatchError("restore -replace round-trip did not reproduce the snapshot")
    return context.raw_bytes


def verify_snapshot(game_version, bindir="bin", config_path=None, snapshot_path=None) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    config_path = resolve_analysis_config(game_version, config_path)
    context = load_snapshot_context(snapshot_path, config_path, game_version, bindir, require_canonical=True)
    actual_document = build_actual_document(context.contract, schema_version=context.document["schema_version"])
    actual_bytes = canonical_snapshot_bytes(actual_document)
    if actual_bytes != context.raw_bytes:
        raise SnapshotMismatchError(format_mismatch(context.document["files"], actual_document["files"]))
    snapshot_round_trip = _round_trip_document(context.document, str(game_version), config_path)
    if snapshot_round_trip != context.raw_bytes:
        raise SnapshotMismatchError("snapshot restore/pack round-trip is not byte-stable")
    actual_round_trip = _round_trip_document(actual_document, str(game_version), config_path)
    if actual_round_trip != actual_bytes:
        raise SnapshotMismatchError("actual bin pack/restore/pack round-trip is not byte-stable")
    return actual_bytes


def migrate_snapshot(
    game_version,
    bindir="bin",
    config_path=None,
    snapshot_path=None,
    output_path=None,
    source_config_path=None,
) -> bytes:
    snapshot_path = Path(snapshot_path or f"gamesymbols/{game_version}.yaml")
    output_path = Path(output_path or snapshot_path)
    config_path = resolve_analysis_config(game_version, config_path)
    source_config_path = resolve_analysis_config(game_version, source_config_path or config_path)
    try:
        source = load_snapshot_context(snapshot_path, source_config_path, game_version, bindir, require_canonical=True)
    except SnapshotMismatchError as exc:
        if exc.reason != "config_digest_mismatch":
            raise
        raw = _read_snapshot(snapshot_path)
        document = parse_snapshot_bytes(raw, str(game_version))
        if document["schema_version"] != LEGACY_SCHEMA_VERSION:
            raise
        transitional_contract = load_unversioned_schema1_contract(source_config_path, game_version, bindir)
        validate_snapshot_contract(document, transitional_contract)
        if raw != canonical_snapshot_bytes(document):
            raise SnapshotMismatchError(
                f"snapshot is not canonical: {snapshot_path}",
                reason="noncanonical_snapshot",
            )
        source = SnapshotContext(document, raw, transitional_contract)
    if source.document["schema_version"] not in {LEGACY_SCHEMA_VERSION, SCHEMA_2_VERSION}:
        raise SnapshotMismatchError("snapshot migration requires a schema 1 or 2 source")
    target_contract = load_contract(config_path, game_version, bindir, LATEST_CONFIG_DIGEST_VERSION)
    _validate_snapshot_paths(source.document, target_contract)
    migrated = build_snapshot_document(
        game_version,
        target_contract.config_sha256,
        source.document["files"],
        schema_version=SCHEMA_VERSION,
        config_digest_version=target_contract.config_digest_version,
        analysis_output_contract_version=target_contract.analysis_output_contract_version,
    )
    data = canonical_snapshot_bytes(migrated)
    reparsed = parse_snapshot_bytes(data, str(game_version))
    validate_snapshot_contract(reparsed, target_contract)
    if reparsed["files"] != source.document["files"]:
        raise SnapshotMismatchError("snapshot migration changed files payload")
    if _round_trip_document(reparsed, str(game_version), config_path) != data:
        raise SnapshotMismatchError("migrated snapshot restore/pack round-trip is not byte-stable")
    _atomic_write(output_path, data)
    return data
