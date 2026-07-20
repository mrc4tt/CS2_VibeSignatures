from pathlib import Path

from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.hashing import (
    contained_path,
    inventory_sha256,
    file_inventory,
    load_json_object,
    reject_reparse_components,
    reject_reparse_points,
    sha256_file,
    verify_inventory,
    write_canonical_json,
)
from release_workflow_lib.manifests import PRE_GAMEDATA_SCHEMA_VERSION, require_build_id, require_gamever, require_sha
from release_workflow_lib.promotion import _matching_pr_indexes, _recovery_paths, _validate_completion_record
from release_workflow_lib.staging import staging_directory


def _require_hash(value: str, label: str) -> str:
    value = str(value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ReleaseWorkflowError(f"invalid {label}")
    return value


def _verify_legacy_provenance(provenance: dict, pending: dict, output_merge_sha: str) -> None:
    expected = {
        "gamever": pending["gamever"],
        "build_id": pending["build_id"],
        "source_sha": pending["source_sha"],
        "output_merge_sha": output_merge_sha,
        "candidate_sha256": pending["candidate_sha256"],
        "bin_manifest_sha256": pending["bin_manifest_sha256"],
        "tracked_output_manifest_sha256": pending["tracked_output_manifest_sha256"],
    }
    if {key: provenance.get(key) for key in expected} != expected:
        raise ReleaseWorkflowError("legacy published provenance does not match completed private staging")


def migrate_legacy_completed(
    *,
    staging_root: Path,
    persisted_root: Path,
    gamever: str,
    build_id: str,
    release_provenance: Path,
    expected_provenance_sha256: str,
) -> dict:
    gamever = require_gamever(gamever)
    build_id = require_build_id(build_id)
    staging_root = Path(staging_root)
    persisted_root = Path(persisted_root)
    if (persisted_root / "release-staging").resolve() != staging_root.resolve():
        raise ReleaseWorkflowError("staging_root must be persisted_root/release-staging")
    stage_dir = staging_directory(staging_root, gamever, build_id)
    reject_reparse_components(staging_root, stage_dir)
    reject_reparse_points(stage_dir)
    if _matching_pr_indexes(staging_root, gamever, build_id):
        raise ReleaseWorkflowError("legacy completed stage still has a matching PR index")
    incoming, backup = _recovery_paths(persisted_root, gamever, build_id)
    if incoming.exists() or backup.exists():
        raise ReleaseWorkflowError("legacy completed stage still has promotion recovery paths")

    pending = load_json_object(stage_dir / "manifest.json")
    if pending.get("schema_version") != PRE_GAMEDATA_SCHEMA_VERSION:
        raise ReleaseWorkflowError("legacy migration requires a schema-3 private manifest")
    complete = load_json_object(stage_dir / "PROMOTION_COMPLETE")
    output_merge_sha = require_sha(complete.get("output_merge_sha", ""), "legacy OUTPUT_MERGE_SHA")
    promoted = load_json_object(stage_dir / "PROMOTED.json")
    expected_accepted = contained_path(persisted_root, "bin", gamever)
    if Path(promoted.get("accepted", "")) != expected_accepted:
        raise ReleaseWorkflowError("legacy promoted state accepted path mismatch")
    if promoted.get("backup") is not None and Path(promoted["backup"]) != backup:
        raise ReleaseWorkflowError("legacy promoted state backup path mismatch")

    release_provenance = Path(release_provenance)
    expected_hash = _require_hash(expected_provenance_sha256, "expected provenance SHA-256")
    if sha256_file(release_provenance) != expected_hash:
        raise ReleaseWorkflowError("legacy release provenance SHA-256 mismatch")
    provenance = load_json_object(release_provenance)
    _verify_legacy_provenance(provenance, pending, output_merge_sha)

    if expected_accepted.is_dir():
        current_hash = inventory_sha256(file_inventory(expected_accepted))
        if current_hash == pending["bin_manifest_sha256"]:
            verify_inventory(expected_accepted, pending["bin_files"])

    record = _validate_completion_record(
        {
            "schema_version": 0,
            "gamever": gamever,
            "build_id": build_id,
            "pr_head_sha": pending["pr_head_sha"],
            "output_merge_sha": output_merge_sha,
            "candidate_sha256": pending["candidate_sha256"],
            "tracked_output_manifest_sha256": pending["tracked_output_manifest_sha256"],
            "bin_manifest_sha256": pending["bin_manifest_sha256"],
            "release_provenance_sha256": expected_hash,
        },
        gamever,
        build_id,
    )
    completed_path = contained_path(staging_root, "completed", gamever, f"{build_id}.json")
    write_canonical_json(completed_path, record)
    return record
