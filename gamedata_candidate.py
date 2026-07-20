from __future__ import annotations

import argparse
import os
import shutil
import uuid
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
from release_workflow_lib.hashing import load_json_object, sha256_file, write_canonical_json
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


class GamedataCandidateError(ValueError):
    pass


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
    gamever = session["gamever"]
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


def verify_published_gamedata(
    *, session_path: str | Path, repo_root: str | Path, gamever: str, candidate: str | Path, analysis_config: str | Path
) -> dict:
    session = guard_candidate(session_path)
    if session["gamever"] != gamever or session["candidate_sha256"] != sha256_file(Path(candidate)):
        raise GamedataCandidateError("gamedata session does not match the release candidate")
    if session["analysis_config_sha256"] != sha256_file(Path(analysis_config)):
        raise GamedataCandidateError("gamedata session does not match the analysis config")
    target = Path(repo_root) / "gamedata" / gamever
    files = prefixed_output_inventory(target, gamever)
    if files != session["files"]:
        raise GamedataCandidateError("published gamedata differs from the guarded candidate")
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
    parser = argparse.ArgumentParser(description="Build and publish immutable versioned gamedata candidates")
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
        else:
            publish_candidate(session_path=args.session, output_dir=args.outputdir)
    except (GamedataCandidateError, GamedataContractError, SymbolStoreError, OSError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
