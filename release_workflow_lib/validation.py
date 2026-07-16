import subprocess
import tempfile
from pathlib import Path

import yaml

from gamesymbol_snapshot_lib.config import load_contract
from gamesymbol_snapshot_lib.operations import load_snapshot_for_contract, restore_snapshot
from gamesymbol_snapshot_lib.paths import ensure_real_tree, iter_yaml_paths, path_from_key
from gamesymbol_snapshot_lib.pr_validation import build_invalidation_plan
from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.manifests import (
    ALLOWED_REPOSITORIES,
    load_tracked_manifest,
    require_gamever,
    require_mode,
    require_sha,
)


def git_output(arguments: list[str], *, text: bool = True):
    result = subprocess.run(["git", *arguments], capture_output=True, text=text, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode(errors="replace").strip()
        raise ReleaseWorkflowError(stderr or f"git {' '.join(arguments)} failed")
    return result.stdout.strip() if text else result.stdout


def validate_build_input(*, repository: str, gamever: str, source_sha: str, mode: str, default_ref: str) -> None:
    if repository not in ALLOWED_REPOSITORIES:
        raise ReleaseWorkflowError(f"repository is not allowlisted: {repository}")
    gamever = require_gamever(gamever)
    source_sha = require_sha(source_sha, "SOURCE_SHA")
    require_mode(mode)
    git_output(["cat-file", "-e", f"{source_sha}^{{commit}}"])
    result = subprocess.run(["git", "merge-base", "--is-ancestor", source_sha, default_ref], check=False)
    if result.returncode != 0:
        raise ReleaseWorkflowError(f"SOURCE_SHA is not reachable from {default_ref}: {source_sha}")
    raw = git_output(["show", f"{source_sha}:download.yaml"], text=False)
    try:
        downloads = yaml.safe_load(raw).get("downloads", [])
    except (AttributeError, yaml.YAMLError) as exc:
        raise ReleaseWorkflowError("download.yaml at SOURCE_SHA is invalid") from exc
    if gamever not in {str(item.get("tag", "")) for item in downloads if isinstance(item, dict)}:
        raise ReleaseWorkflowError(f"GAMEVER {gamever} is absent from download.yaml at SOURCE_SHA")
    tag_exists = (
        subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/tags/{gamever}"], check=False).returncode == 0
    )
    if mode == "new" and tag_exists:
        raise ReleaseWorkflowError(f"mode=new requires tag {gamever} to be absent")
    if mode == "republish" and not tag_exists:
        raise ReleaseWorkflowError(f"mode=republish requires tag {gamever} to exist")


def _changed_files(base_sha: str, source_sha: str) -> list[str]:
    output = git_output(["diff", "--name-only", base_sha, source_sha, "--"])
    return [line for line in output.splitlines() if line]


def invalidate_republish(*, repo_root: Path, gamever: str, source_sha: str, bindir: Path) -> int:
    repo_root = Path(repo_root)
    gamever = require_gamever(gamever)
    source_sha = require_sha(source_sha, "SOURCE_SHA")
    manifest_path = repo_root / "release-manifests" / f"{gamever}.json"
    if not manifest_path.is_file():
        game_root = Path(bindir) / gamever
        ensure_real_tree(Path(bindir), game_root)
        paths = list(iter_yaml_paths(game_root))
        for path in paths:
            path.unlink()
        print(f"No accepted release manifest exists; conservative baseline invalidated {len(paths)} YAML file(s)")
        return len(paths)
    manifest = load_tracked_manifest(manifest_path)
    base_sha = require_sha(manifest["source_sha"], "previous SOURCE_SHA")
    if base_sha == source_sha:
        raise ReleaseWorkflowError("republish SOURCE_SHA must be newer than the accepted generator source")
    result = subprocess.run(["git", "merge-base", "--is-ancestor", base_sha, source_sha], check=False)
    if result.returncode != 0:
        raise ReleaseWorkflowError("previous accepted SOURCE_SHA is not an ancestor of the rebuild SOURCE_SHA")
    snapshot = repo_root / "gamesymbols" / f"{gamever}.yaml"
    with tempfile.TemporaryDirectory(prefix="release-base-") as temp_dir:
        base_config = Path(temp_dir) / "config.yaml"
        base_config.write_bytes(git_output(["show", f"{base_sha}:config.yaml"], text=False))
        base_contract = load_contract(base_config, gamever, bindir)
        head_contract = load_contract(repo_root / "config.yaml", gamever, bindir)
        base_document, _raw = load_snapshot_for_contract(snapshot, base_contract)
        restore_snapshot(gamever, bindir, base_config, snapshot, replace=True)
        plan = build_invalidation_plan(
            base_contract,
            head_contract,
            base_document,
            base_document,
            _changed_files(base_sha, source_sha),
            repo_root,
        )
    ensure_real_tree(Path(bindir), head_contract.game_root)
    deleted = 0
    for key in sorted(plan.paths):
        target = path_from_key(head_contract.game_root, key)
        if target.is_file():
            target.unlink()
            deleted += 1
    for reason in plan.reasons:
        print(reason)
    print(f"Invalidated {len(plan.paths)} affected output(s); deleted {deleted} YAML file(s)")
    return deleted
