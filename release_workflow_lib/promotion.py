import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.hashing import (
    contained_path,
    file_inventory,
    inventory_sha256,
    load_json_object,
    reject_reparse_points,
    reject_reparse_components,
    validate_output_paths,
    verify_inventory,
    write_canonical_json,
)
from release_workflow_lib.manifests import (
    ALLOWED_REPOSITORIES,
    SCHEMA_VERSION,
    load_tracked_manifest,
    parse_output_branch,
    require_build_id,
    require_gamever,
    require_sha,
    verify_tracked_outputs,
)
from release_workflow_lib.staging import load_indexed_pending


def _git_output(arguments: list[str]) -> str:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReleaseWorkflowError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def verify_output_pr(
    *,
    repo_root: Path,
    repository: str,
    head_repository: str,
    author: str,
    branch: str,
    base_sha: str,
    head_sha: str,
) -> dict:
    if repository not in ALLOWED_REPOSITORIES:
        raise ReleaseWorkflowError(f"repository is not allowlisted: {repository}")
    base_sha = require_sha(base_sha, "PR base SHA")
    require_sha(head_sha, "PR head SHA")
    if repository != head_repository:
        raise ReleaseWorkflowError("generated-output PR must originate from the base repository")
    if author != "github-actions[bot]":
        raise ReleaseWorkflowError("generated-output PR author is not github-actions[bot]")
    gamever, build_id = parse_output_branch(branch)
    paths = [line for line in _git_output(["diff", "--name-only", base_sha, head_sha, "--"]).splitlines() if line]
    validate_output_paths(paths, gamever)
    manifest = load_tracked_manifest(Path(repo_root) / "release-manifests" / f"{gamever}.json")
    if manifest["source_sha"] != base_sha or manifest["build_id"] != build_id:
        raise ReleaseWorkflowError("output PR is stale or its manifest identity does not match the branch")
    verify_tracked_outputs(repo_root, manifest)
    return manifest


def verify_promotion(
    *,
    repo_root: Path,
    staging_root: Path,
    repository: str,
    head_repository: str,
    author: str,
    branch: str,
    base_branch: str,
    default_branch: str,
    pr_number: int,
    event_head_sha: str,
    merge_sha: str,
) -> dict:
    if repository not in ALLOWED_REPOSITORIES:
        raise ReleaseWorkflowError(f"repository is not allowlisted: {repository}")
    merge_sha = require_sha(merge_sha, "OUTPUT_MERGE_SHA")
    if repository != head_repository:
        raise ReleaseWorkflowError("promotion requires a same-repository PR")
    if author != "github-actions[bot]":
        raise ReleaseWorkflowError("promotion requires github-actions[bot] as PR author")
    if base_branch != default_branch:
        raise ReleaseWorkflowError("generated-output PR base is not the default branch")
    gamever, build_id = parse_output_branch(branch)
    index, pending, stage_dir = load_indexed_pending(staging_root, pr_number, event_head_sha)
    if index["output_branch"] != branch or (index["gamever"], index["build_id"]) != (gamever, build_id):
        raise ReleaseWorkflowError("pull request branch does not match pending index")
    if pending.get("repository") != repository:
        raise ReleaseWorkflowError("private manifest repository identity mismatch")
    parents = _git_output(["rev-list", "--parents", "-n", "1", merge_sha]).split()
    if len(parents) != 3:
        raise ReleaseWorkflowError("promotion requires a two-parent merge commit")
    if parents[1] != pending["source_sha"] or parents[2] != event_head_sha:
        raise ReleaseWorkflowError("merge parents do not match SOURCE_SHA and PR head SHA")
    paths = [line for line in _git_output(["diff", "--name-only", parents[1], merge_sha, "--"]).splitlines() if line]
    validate_output_paths(paths, gamever)
    tracked = load_tracked_manifest(Path(repo_root) / "release-manifests" / f"{gamever}.json")
    if {key: pending.get(key) for key in tracked} != tracked:
        raise ReleaseWorkflowError("tracked and private manifests disagree during promotion")
    tracked_files = verify_tracked_outputs(repo_root, tracked)
    if tracked_files != pending.get("tracked_files"):
        raise ReleaseWorkflowError("tracked output inventory differs from pending build")
    bin_hash = verify_inventory(stage_dir / "bin" / gamever, pending.get("bin_files", []))
    if bin_hash != tracked["bin_manifest_sha256"]:
        raise ReleaseWorkflowError("staged bin hash differs from tracked manifest")
    return {**tracked, "stage_dir": str(stage_dir), "output_merge_sha": merge_sha}


def reconstruct_workspace(repo_root: Path, stage_dir: Path, gamever: str) -> Path:
    repo_root = Path(repo_root).resolve()
    stage_dir = Path(stage_dir)
    reject_reparse_components(stage_dir, stage_dir)
    source = contained_path(stage_dir, "bin", gamever)
    reject_reparse_points(source)
    target = contained_path(repo_root, "bin", gamever)
    if target.exists():
        reject_reparse_points(target)
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, copy_function=shutil.copy2)
    return target


@contextmanager
def _version_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except OSError as exc:
        raise ReleaseWorkflowError(f"unable to acquire per-version promotion lock: {lock_path}") from exc
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _write_promoted_state(*, stage_dir: Path, target: Path, backup: Path | None) -> dict:
    state = {
        "schema_version": SCHEMA_VERSION,
        "accepted": str(target),
        "backup": str(backup) if backup else None,
    }
    write_canonical_json(stage_dir / "PROMOTED.json", state)
    return state


def _swap_verified_bin(
    *,
    source: Path,
    target: Path,
    incoming: Path,
    backup: Path,
    expected_files: list[dict],
    expected_hash: str,
) -> bool:
    if backup.exists():
        raise ReleaseWorkflowError(f"promotion backup already exists while accepted bin differs: {backup}")
    if incoming.exists():
        reject_reparse_points(incoming)
        shutil.rmtree(incoming)
    shutil.copytree(source, incoming, copy_function=shutil.copy2)
    if verify_inventory(incoming, expected_files) != expected_hash:
        shutil.rmtree(incoming)
        raise ReleaseWorkflowError("incoming accepted-bin directory failed verification")
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(incoming, target)
    except OSError as exc:
        if moved_old and not target.exists() and backup.exists():
            os.replace(backup, target)
        raise ReleaseWorkflowError(f"transactional accepted-bin swap failed: {exc}") from exc
    return moved_old


def promote_bin(*, persisted_root: Path, stage_dir: Path, gamever: str, build_id: str) -> dict:
    gamever = require_gamever(gamever)
    build_id = require_build_id(build_id)
    persisted_root = Path(persisted_root)
    reject_reparse_components(persisted_root, persisted_root)
    persisted_root = persisted_root.resolve()
    stage_dir = Path(stage_dir)
    reject_reparse_components(stage_dir, stage_dir)
    source = contained_path(stage_dir, "bin", gamever)
    reject_reparse_components(stage_dir, stage_dir / "manifest.json")
    pending = load_json_object(stage_dir / "manifest.json")
    if (pending.get("gamever"), pending.get("build_id")) != (gamever, build_id):
        raise ReleaseWorkflowError("promotion request does not match private pending manifest")
    expected_files = pending.get("bin_files", [])
    expected_hash = pending.get("bin_manifest_sha256")
    if verify_inventory(source, expected_files) != expected_hash:
        raise ReleaseWorkflowError("staged bin failed verification before promotion")
    accepted_root = contained_path(persisted_root, "bin")
    reject_reparse_components(persisted_root, accepted_root)
    accepted_root.mkdir(parents=True, exist_ok=True)
    target = contained_path(accepted_root, gamever)
    incoming = contained_path(accepted_root, f".{gamever}.{build_id}.incoming")
    backup = contained_path(accepted_root, f".{gamever}.{build_id}.backup")
    lock_path = contained_path(persisted_root, "release-staging", "locks", f"{gamever}.lock")
    with _version_lock(lock_path):
        started_path = stage_dir / "PROMOTION_STARTED"
        reject_reparse_components(stage_dir, started_path)
        write_canonical_json(
            started_path,
            {"schema_version": SCHEMA_VERSION, "gamever": gamever, "build_id": build_id},
        )
        if target.is_dir() and inventory_sha256(file_inventory(target)) == expected_hash:
            return _write_promoted_state(stage_dir=stage_dir, target=target, backup=backup if backup.exists() else None)
        moved_old = _swap_verified_bin(
            source=source,
            target=target,
            incoming=incoming,
            backup=backup,
            expected_files=expected_files,
            expected_hash=expected_hash,
        )
        return _write_promoted_state(stage_dir=stage_dir, target=target, backup=backup if moved_old else None)


def finalize_promotion(*, staging_root: Path, pr_number: int, event_head_sha: str, output_merge_sha: str) -> None:
    _index, pending, stage_dir = load_indexed_pending(staging_root, pr_number, event_head_sha)
    state = load_json_object(stage_dir / "PROMOTED.json")
    accepted = Path(state["accepted"])
    if verify_inventory(accepted, pending["bin_files"]) != pending["bin_manifest_sha256"]:
        raise ReleaseWorkflowError("accepted bin changed before promotion completion")
    complete = {
        "schema_version": SCHEMA_VERSION,
        "output_merge_sha": require_sha(output_merge_sha, "OUTPUT_MERGE_SHA"),
    }
    write_canonical_json(stage_dir / "PROMOTION_COMPLETE", complete)
    backup = state.get("backup")
    if backup and Path(backup).exists():
        reject_reparse_points(Path(backup))
        shutil.rmtree(backup)
    index_path = contained_path(Path(staging_root), "pr-index", f"{pr_number}.json")
    index_path.unlink()
