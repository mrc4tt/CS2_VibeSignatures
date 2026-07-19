import re
from collections.abc import Mapping

import yaml

from gamesymbol_snapshot_lib.errors import SnapshotSchemaError
from gamesymbol_snapshot_lib.paths import validate_snapshot_key

LEGACY_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
SCHEMA_1_KEYS = ("schema_version", "game_version", "config_sha256", "file_count", "files")
SCHEMA_2_KEYS = (
    "schema_version",
    "config_digest_version",
    "game_version",
    "config_sha256",
    "file_count",
    "files",
)
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CanonicalDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _key_sort_key(key):
    return type(key).__name__, str(key)


def canonicalize(value):
    if isinstance(value, Mapping):
        return {key: canonicalize(value[key]) for key in sorted(value, key=_key_sort_key)}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def canonical_yaml_bytes(value) -> bytes:
    text = yaml.dump(
        canonicalize(value),
        Dumper=CanonicalDumper,
        allow_unicode=True,
        default_flow_style=False,
        explicit_end=False,
        explicit_start=False,
        indent=2,
        line_break="\n",
        sort_keys=False,
        width=1_000_000,
    )
    return text.rstrip("\r\n").encode("utf-8") + b"\n"


def snapshot_config_digest_version(document: Mapping) -> int:
    schema_version = document.get("schema_version")
    if schema_version == LEGACY_SCHEMA_VERSION:
        return 1
    if schema_version == SCHEMA_VERSION:
        version = document.get("config_digest_version")
        if not isinstance(version, int) or isinstance(version, bool) or version != 2:
            raise SnapshotSchemaError(
                f"unsupported snapshot config_digest_version: {version!r}",
                reason="unsupported_config_digest_version",
            )
        return version
    raise SnapshotSchemaError(
        f"unsupported snapshot schema_version: {schema_version!r}",
        reason="unsupported_snapshot_schema",
    )


def build_snapshot_document(
    game_version: str,
    config_sha256: str,
    files: Mapping,
    *,
    schema_version: int = SCHEMA_VERSION,
    config_digest_version: int | None = None,
) -> dict:
    ordered_files = {path: canonicalize(files[path]) for path in sorted(files)}
    if schema_version == LEGACY_SCHEMA_VERSION:
        if config_digest_version not in (None, 1):
            raise SnapshotSchemaError("schema 1 snapshots require config digest version 1")
        return {
            "schema_version": LEGACY_SCHEMA_VERSION,
            "game_version": str(game_version),
            "config_sha256": config_sha256,
            "file_count": len(ordered_files),
            "files": ordered_files,
        }
    if schema_version != SCHEMA_VERSION:
        raise SnapshotSchemaError(
            f"unsupported snapshot schema_version: {schema_version!r}",
            reason="unsupported_snapshot_schema",
        )
    if config_digest_version is None:
        config_digest_version = 2
    if config_digest_version != 2:
        raise SnapshotSchemaError(
            f"unsupported snapshot config_digest_version: {config_digest_version!r}",
            reason="unsupported_config_digest_version",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "config_digest_version": config_digest_version,
        "game_version": str(game_version),
        "config_sha256": config_sha256,
        "file_count": len(ordered_files),
        "files": ordered_files,
    }


def canonical_snapshot_bytes(document: Mapping) -> bytes:
    schema_version = document.get("schema_version")
    digest_version = snapshot_config_digest_version(document)
    canonical = build_snapshot_document(
        str(document["game_version"]),
        document["config_sha256"],
        document["files"],
        schema_version=schema_version,
        config_digest_version=digest_version,
    )
    return canonical_yaml_bytes(canonical)


def _validate_metadata(document: object, expected_game_version: str | None) -> dict:
    if not isinstance(document, dict):
        raise SnapshotSchemaError("snapshot top level must be a mapping")
    schema_version = document.get("schema_version")
    expected_keys = SCHEMA_1_KEYS if schema_version == LEGACY_SCHEMA_VERSION else SCHEMA_2_KEYS
    if schema_version not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}:
        raise SnapshotSchemaError(
            f"unsupported snapshot schema_version: {schema_version!r}",
            reason="unsupported_snapshot_schema",
        )
    if set(document) != set(expected_keys):
        raise SnapshotSchemaError(f"snapshot schema {schema_version} must contain exactly: {', '.join(expected_keys)}")
    snapshot_config_digest_version(document)
    game_version = document.get("game_version")
    if not isinstance(game_version, str):
        raise SnapshotSchemaError("snapshot game_version must be a string")
    if expected_game_version is not None and game_version != str(expected_game_version):
        raise SnapshotSchemaError(
            f"snapshot game_version {game_version!r} does not match {str(expected_game_version)!r}"
        )
    if not isinstance(document.get("config_sha256"), str) or not DIGEST_PATTERN.fullmatch(document["config_sha256"]):
        raise SnapshotSchemaError("snapshot config_sha256 is invalid")
    if not isinstance(document.get("files"), dict):
        raise SnapshotSchemaError("snapshot files must be a mapping")
    count = document.get("file_count")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(document["files"]):
        raise SnapshotSchemaError("snapshot file_count does not match files")
    return document


def parse_snapshot_bytes(data: bytes, expected_game_version: str | None = None) -> dict:
    try:
        document = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise SnapshotSchemaError(f"unable to parse snapshot YAML: {exc}") from exc
    document = _validate_metadata(document, expected_game_version)
    normalized_files = {}
    case_spellings = {}
    for raw_path, payload in document["files"].items():
        path = validate_snapshot_key(raw_path)
        prior = case_spellings.setdefault(path.casefold(), path)
        if prior != path:
            raise SnapshotSchemaError(f"case-insensitive snapshot path collision: {prior} and {path}")
        if not isinstance(payload, dict):
            raise SnapshotSchemaError(f"snapshot payload must be a mapping: {path}")
        normalized_files[path] = payload
    document["files"] = normalized_files
    return document
