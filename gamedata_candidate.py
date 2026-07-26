from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from gamedata_contract import (
    GamedataContractError,
    discover_generator_modules,
    gamedata_manifest_sha256,
    generator_contract_sha256,
    prefixed_output_inventory,
    validate_output_tree,
)
from gamesymbol_store import SymbolStoreError
from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.hashing import (
    REGULAR_GIT_MODES,
    load_json_object,
    normalized_relative_path,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from update_gamedata import generate_gamedata

SESSION_FIELDS = {
    "schema_version",
    "gamever",
    "build_id",
    "candidate_root",
    "snapshot_path",
    "analysis_config_path",
    "modules_dir",
    "gamedata_path",
    "candidate_sha256",
    "analysis_config_sha256",
    "generator_contract_sha256",
    "gamedata_manifest_sha256",
    "files",
}
GAMEVER_RE = re.compile(r"^[0-9]{4,10}[a-z]?$", re.ASCII)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
MAX_DIAGNOSTIC_PATHS = 20


class GamedataCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class GamedataInventoryModification:
    path: str
    expected_size: int
    expected_sha256: str
    candidate_size: int
    candidate_sha256: str


@dataclass(frozen=True)
class GamedataInventoryDiff:
    added: tuple[str, ...]
    missing: tuple[str, ...]
    modified: tuple[GamedataInventoryModification, ...]

    @property
    def matches(self) -> bool:
        return not (self.added or self.missing or self.modified)


def _validated_gamever(gamever: str) -> str:
    if not isinstance(gamever, str) or not GAMEVER_RE.fullmatch(gamever):
        raise GamedataCandidateError(f"invalid GAMEVER: {gamever!r}")
    return gamever


def _canonical_inventory_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GamedataCandidateError(f"path must be a non-empty POSIX relative path: {value!r}")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise GamedataCandidateError(f"unsafe relative path: {value!r}")
    try:
        normalized = normalized_relative_path(value)
    except ReleaseWorkflowError as exc:
        raise GamedataCandidateError(str(exc)) from exc
    if normalized != value:
        raise GamedataCandidateError(f"inventory path is not canonical: {value!r}")
    return normalized


def _absolute_file(path: str | Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise GamedataCandidateError(f"{label} is missing: {resolved}")
    return resolved


def _load_session(session_path: str | Path) -> dict:
    session = load_json_object(Path(session_path))
    if set(session) != SESSION_FIELDS or session.get("schema_version") != 1:
        raise GamedataCandidateError("gamedata candidate session has unexpected fields or schema")
    return session


def build_candidate(
    *,
    gamever: str,
    build_id: str,
    snapshot: str | Path,
    analysis_config: str | Path,
    modules_dir: str | Path,
    candidate_root: str | Path,
    session_path: str | Path,
    platforms: list[str] | None = None,
    debug: bool = False,
) -> dict:
    gamever = _validated_gamever(gamever)
    snapshot = _absolute_file(snapshot, "symbol candidate")
    analysis_config = _absolute_file(analysis_config, "analysis config")
    modules_dir = Path(modules_dir).resolve()
    candidate_root = Path(candidate_root).resolve()
    version_root = candidate_root / "gamedata" / gamever
    if version_root.exists():
        raise GamedataCandidateError(f"gamedata candidate output already exists: {version_root}")
    version_root.parent.mkdir(parents=True, exist_ok=True)
    result = generate_gamedata(
        gamever=gamever,
        snapshot_path=snapshot,
        config_path=analysis_config,
        modules_dir=modules_dir,
        output_root=version_root,
        platforms=platforms or ["windows", "linux"],
        debug=debug,
        download_latest=True,
        strict=True,
    )
    session = {
        "schema_version": 1,
        "gamever": gamever,
        "build_id": build_id,
        "candidate_root": str(candidate_root),
        "snapshot_path": str(snapshot),
        "analysis_config_path": str(analysis_config),
        "modules_dir": str(modules_dir),
        "gamedata_path": f"gamedata/{gamever}",
        "candidate_sha256": sha256_file(snapshot),
        "analysis_config_sha256": sha256_file(analysis_config),
        "generator_contract_sha256": result["generator_contract_sha256"],
        "gamedata_manifest_sha256": result["gamedata_manifest_sha256"],
        "files": result["files"],
    }
    write_canonical_json(Path(session_path), session)
    return session


def guard_candidate(session_path: str | Path) -> dict:
    session = _load_session(session_path)
    gamever = _validated_gamever(session["gamever"])
    if session["gamedata_path"] != f"gamedata/{gamever}":
        raise GamedataCandidateError("gamedata candidate session has an invalid versioned output path")
    snapshot = _absolute_file(session["snapshot_path"], "symbol candidate")
    analysis_config = _absolute_file(session["analysis_config_path"], "analysis config")
    if sha256_file(snapshot) != session["candidate_sha256"]:
        raise GamedataCandidateError("symbol candidate changed after gamedata generation")
    if sha256_file(analysis_config) != session["analysis_config_sha256"]:
        raise GamedataCandidateError("analysis config changed after gamedata generation")
    modules = discover_generator_modules(session["modules_dir"])
    if generator_contract_sha256(modules) != session["generator_contract_sha256"]:
        raise GamedataCandidateError("generator contract changed after gamedata generation")
    version_root = Path(session["candidate_root"]) / session["gamedata_path"]
    files = validate_output_tree(version_root, gamever, modules)
    if files != session["files"] or gamedata_manifest_sha256(files) != session["gamedata_manifest_sha256"]:
        raise GamedataCandidateError("gamedata candidate bytes changed after generation")
    return session


def _inventory_by_path(
    files: Sequence[Mapping[str, object]], *, gamever: str, label: str
) -> dict[str, dict[str, object]]:
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)) or not files:
        raise GamedataCandidateError(f"{label} is missing or empty")
    prefix = f"gamedata/{gamever}/"
    by_path: dict[str, dict[str, object]] = {}
    casefolded_paths: dict[str, str] = {}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "size", "sha256"}:
            raise GamedataCandidateError(f"{label} has an invalid inventory record")
        path = _canonical_inventory_path(item["path"])
        if not path.startswith(prefix):
            raise GamedataCandidateError(f"{label} path is outside exact root {prefix}: {path}")
        size = item["size"]
        digest = item["sha256"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise GamedataCandidateError(f"{label} has an invalid size for {path}")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise GamedataCandidateError(f"{label} has an invalid SHA-256 for {path}")
        if path in by_path:
            raise GamedataCandidateError(f"{label} has a duplicate path: {path}")
        folded = path.casefold()
        if folded in casefolded_paths:
            raise GamedataCandidateError(
                f"{label} has a case-insensitive path collision: {casefolded_paths[folded]} and {path}"
            )
        record = {"path": path, "size": size, "sha256": digest}
        by_path[path] = record
        casefolded_paths[folded] = path
    return by_path


def compare_gamedata_inventory(
    *, session: Mapping[str, object], expected_files: Sequence[Mapping[str, object]]
) -> GamedataInventoryDiff:
    gamever = _validated_gamever(session.get("gamever"))
    candidate_files = session.get("files")
    candidate = _inventory_by_path(candidate_files, gamever=gamever, label="candidate gamedata inventory")
    expected = _inventory_by_path(expected_files, gamever=gamever, label="expected gamedata inventory")
    candidate_paths = set(candidate)
    expected_paths = set(expected)
    modified = []
    for path in sorted(candidate_paths & expected_paths):
        candidate_record = candidate[path]
        expected_record = expected[path]
        if (candidate_record["size"], candidate_record["sha256"]) != (
            expected_record["size"],
            expected_record["sha256"],
        ):
            modified.append(
                GamedataInventoryModification(
                    path=path,
                    expected_size=expected_record["size"],
                    expected_sha256=expected_record["sha256"],
                    candidate_size=candidate_record["size"],
                    candidate_sha256=candidate_record["sha256"],
                )
            )
    return GamedataInventoryDiff(
        added=tuple(sorted(expected_paths - candidate_paths)),
        missing=tuple(sorted(candidate_paths - expected_paths)),
        modified=tuple(modified),
    )


def _git_bytes(repo_root: Path, arguments: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise GamedataCandidateError(f"unable to run git: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise GamedataCandidateError(detail or f"git {' '.join(arguments)} failed")
    return result.stdout


def _resolved_checkout_revision(repo_root: Path, revision: str) -> str:
    if not isinstance(revision, str) or not revision or "\0" in revision:
        raise GamedataCandidateError("an explicit Git revision is required")
    if revision != "HEAD" and not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise GamedataCandidateError("Git revision must be explicit HEAD or a full commit SHA")
    resolved = (
        _git_bytes(repo_root, ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"])
        .decode("ascii", errors="strict")
        .strip()
    )
    checkout = (
        _git_bytes(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"]).decode("ascii", errors="strict").strip()
    )
    if not re.fullmatch(r"[0-9a-fA-F]{40}", resolved) or not re.fullmatch(r"[0-9a-fA-F]{40}", checkout):
        raise GamedataCandidateError("Git revision did not resolve to a full commit SHA")
    if resolved.lower() != checkout.lower():
        raise GamedataCandidateError("explicit Git revision does not match the current checkout commit")
    return resolved.lower()


def git_revision_gamedata_inventory(repo_root: str | Path, revision: str, gamever: str) -> list[dict]:
    repo_root = Path(repo_root).resolve()
    if not repo_root.is_dir():
        raise GamedataCandidateError(f"repository root is missing: {repo_root}")
    gamever = _validated_gamever(gamever)
    resolved = _resolved_checkout_revision(repo_root, revision)
    root = f"gamedata/{gamever}"
    prefix = root + "/"
    raw_entries = _git_bytes(repo_root, ["ls-tree", "-r", "-z", "--full-tree", resolved, "--", root])
    objects: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    casefolded_paths: dict[str, str] = {}
    for record in raw_entries.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split()
            path_text = raw_path.decode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise GamedataCandidateError("tracked gamedata has a malformed Git tree entry") from exc
        if object_type != "blob":
            raise GamedataCandidateError(f"tracked gamedata has a non-blob Git tree entry: {path_text}")
        if mode not in REGULAR_GIT_MODES:
            raise GamedataCandidateError(f"tracked gamedata has an unsupported Git tree entry: {path_text}")
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", object_id):
            raise GamedataCandidateError(f"tracked gamedata has an invalid Git object ID: {path_text}")
        if not path_text.startswith(prefix):
            raise GamedataCandidateError(f"tracked gamedata path is outside exact root {root}: {path_text}")
        path = _canonical_inventory_path(path_text)
        if path in seen_paths:
            raise GamedataCandidateError(f"tracked gamedata has a duplicate path: {path}")
        folded = path.casefold()
        if folded in casefolded_paths:
            raise GamedataCandidateError(
                f"tracked gamedata has a case-insensitive path collision: {casefolded_paths[folded]} and {path}"
            )
        seen_paths.add(path)
        casefolded_paths[folded] = path
        objects.append((path, object_id))
    if not objects:
        raise GamedataCandidateError(f"tracked gamedata root is missing or empty at revision {resolved}: {root}")
    inventory = []
    for path, object_id in objects:
        blob = _git_bytes(repo_root, ["cat-file", "blob", object_id])
        inventory.append({"path": path, "size": len(blob), "sha256": sha256_bytes(blob)})
    return sorted(inventory, key=lambda item: item["path"])


def _guard_session_identity(
    *, session_path: str | Path, gamever: str, candidate: str | Path, analysis_config: str | Path
) -> dict:
    gamever = _validated_gamever(gamever)
    session = guard_candidate(session_path)
    candidate = _absolute_file(candidate, "release candidate")
    analysis_config = _absolute_file(analysis_config, "analysis config")
    if session["gamever"] != gamever or session["candidate_sha256"] != sha256_file(candidate):
        raise GamedataCandidateError("gamedata session does not match the release candidate")
    if session["analysis_config_sha256"] != sha256_file(analysis_config):
        raise GamedataCandidateError("gamedata session does not match the analysis config")
    return session


def _bounded_inventory_diagnostics(gamever: str, diff: GamedataInventoryDiff) -> str:
    lines = [f"Tracked gamedata mismatch for {gamever}:"]

    def add_paths(title: str, paths: tuple[str, ...]) -> None:
        if not paths:
            return
        lines.append(f"  {title}:")
        lines.extend(f"    {path}" for path in paths[:MAX_DIAGNOSTIC_PATHS])
        if len(paths) > MAX_DIAGNOSTIC_PATHS:
            lines.append(f"    ... {len(paths) - MAX_DIAGNOSTIC_PATHS} more")

    add_paths("Added in PR head", diff.added)
    add_paths("Missing from PR head", diff.missing)
    if diff.modified:
        lines.append("  Modified:")
        for item in diff.modified[:MAX_DIAGNOSTIC_PATHS]:
            lines.extend(
                (
                    f"    {item.path}",
                    f"      expected size/sha256: {item.expected_size} / {item.expected_sha256}",
                    f"      candidate size/sha256: {item.candidate_size} / {item.candidate_sha256}",
                )
            )
        if len(diff.modified) > MAX_DIAGNOSTIC_PATHS:
            lines.append(f"    ... {len(diff.modified) - MAX_DIAGNOSTIC_PATHS} more")
    return "\n".join(lines)


def verify_published_gamedata(
    *, session_path: str | Path, repo_root: str | Path, gamever: str, candidate: str | Path, analysis_config: str | Path
) -> dict:
    session = _guard_session_identity(
        session_path=session_path,
        gamever=gamever,
        candidate=candidate,
        analysis_config=analysis_config,
    )
    target = Path(repo_root) / "gamedata" / gamever
    files = prefixed_output_inventory(target, gamever)
    if not compare_gamedata_inventory(session=session, expected_files=files).matches:
        raise GamedataCandidateError("published gamedata differs from the guarded candidate")
    return {
        "gamedata_path": session["gamedata_path"],
        "gamedata_manifest_sha256": session["gamedata_manifest_sha256"],
        "generator_contract_sha256": session["generator_contract_sha256"],
    }


def verify_tracked_gamedata(
    *,
    session_path: str | Path,
    repo_root: str | Path,
    revision: str,
    gamever: str,
    candidate: str | Path,
    analysis_config: str | Path,
) -> dict:
    session = _guard_session_identity(
        session_path=session_path,
        gamever=gamever,
        candidate=candidate,
        analysis_config=analysis_config,
    )
    expected_files = git_revision_gamedata_inventory(repo_root, revision, gamever)
    diff = compare_gamedata_inventory(session=session, expected_files=expected_files)
    if not diff.matches:
        raise GamedataCandidateError(_bounded_inventory_diagnostics(gamever, diff))
    return {
        "gamedata_path": session["gamedata_path"],
        "gamedata_manifest_sha256": session["gamedata_manifest_sha256"],
        "generator_contract_sha256": session["generator_contract_sha256"],
    }


def publish_candidate(*, session_path: str | Path, output_dir: str | Path) -> dict:
    session = guard_candidate(session_path)
    gamever = session["gamever"]
    source = Path(session["candidate_root"]) / session["gamedata_path"]
    target = Path(output_dir).resolve()
    if target.name != gamever:
        raise GamedataCandidateError(f"publish target must end with the exact GAMEVER: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    incoming = target.parent / f".{gamever}.incoming-{uuid.uuid4().hex}"
    backup = target.parent / f".{gamever}.backup-{uuid.uuid4().hex}"
    shutil.copytree(source, incoming, copy_function=shutil.copy2)
    incoming_files = prefixed_output_inventory(incoming, gamever)
    if incoming_files != session["files"]:
        shutil.rmtree(incoming)
        raise GamedataCandidateError("copied gamedata candidate failed verification")
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(incoming, target)
    except OSError as exc:
        if moved_old and not target.exists() and backup.exists():
            os.replace(backup, target)
        raise GamedataCandidateError(f"atomic gamedata publication failed: {exc}") from exc
    if backup.exists():
        shutil.rmtree(backup)
    if prefixed_output_inventory(target, gamever) != session["files"]:
        raise GamedataCandidateError("published gamedata failed final verification")
    return session


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build, verify, and publish immutable versioned gamedata candidates")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("-gamever", required=True)
    build.add_argument("-build-id", required=True)
    build.add_argument("-snapshot", required=True)
    build.add_argument("-configyaml", required=True)
    build.add_argument("-modulesdir", default="gamedata-generators")
    build.add_argument("-candidate-root", required=True)
    build.add_argument("-session", required=True)
    build.add_argument("-platform", default="windows,linux")
    build.add_argument("-debug", action="store_true")
    guard = commands.add_parser("guard")
    guard.add_argument("-session", required=True)
    verify_tracked = commands.add_parser("verify-tracked")
    verify_tracked.add_argument("-session", required=True)
    verify_tracked.add_argument("-gamever", required=True)
    verify_tracked.add_argument("-candidate", required=True)
    verify_tracked.add_argument("-configyaml", required=True)
    verify_tracked.add_argument("-repo-root", required=True)
    verify_tracked.add_argument("-revision", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("-session", required=True)
    publish.add_argument("-outputdir", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            build_candidate(
                gamever=args.gamever,
                build_id=args.build_id,
                snapshot=args.snapshot,
                analysis_config=args.configyaml,
                modules_dir=args.modulesdir,
                candidate_root=args.candidate_root,
                session_path=args.session,
                platforms=[item.strip() for item in args.platform.split(",") if item.strip()],
                debug=args.debug,
            )
        elif args.command == "guard":
            guard_candidate(args.session)
        elif args.command == "verify-tracked":
            verify_tracked_gamedata(
                session_path=args.session,
                repo_root=args.repo_root,
                revision=args.revision,
                gamever=args.gamever,
                candidate=args.candidate,
                analysis_config=args.configyaml,
            )
        else:
            publish_candidate(session_path=args.session, output_dir=args.outputdir)
    except (
        GamedataCandidateError,
        GamedataContractError,
        ReleaseWorkflowError,
        SymbolStoreError,
        OSError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
