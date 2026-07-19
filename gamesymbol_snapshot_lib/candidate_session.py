import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from gamesymbol_snapshot_lib.paths import is_reparse_point

SESSION_SCHEMA_VERSION = 2
VALIDATION_STEPS = ("gamedata", "cpp_tests")


class CandidateContractError(Exception):
    """Candidate path, session, or state contract is invalid."""


def absolute_path(path) -> Path:
    return Path(os.path.abspath(Path(path)))


def ensure_real_path(path: Path, *, require_file: bool = False) -> None:
    candidates = (path, *path.parents) if require_file else (path.parent, *path.parent.parents)
    for candidate in candidates:
        if candidate.exists() and is_reparse_point(candidate):
            raise CandidateContractError(f"candidate path must not traverse a link/reparse point: {candidate}")
    if require_file and not path.is_file():
        raise CandidateContractError(f"candidate file does not exist: {path}")


def file_identity(path: Path) -> dict[str, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise CandidateContractError(f"unable to stat candidate {path}: {exc}") from exc
    return {
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def atomic_json_write(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise CandidateContractError(f"unable to update candidate session {path}: {exc}") from exc
    finally:
        if temporary and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def initial_manifest(info, output: Path) -> dict:
    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        **asdict(info),
        "candidate_path": str(output),
        "file_identity": file_identity(output),
        "state": "candidate_ready",
        "completed_steps": {
            "analysis": True,
            "pack": True,
            "expected_compare": None,
            "gamedata": False,
            "cpp_tests": False,
        },
    }


def _validate_manifest(manifest: object, session: Path) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SESSION_SCHEMA_VERSION:
        raise CandidateContractError(f"unsupported candidate session: {session}")
    required = {
        "candidate_path": str,
        "candidate_sha256": str,
        "game_version": str,
        "snapshot_schema_version": int,
        "config_digest_version": int,
        "config_sha256": str,
        "file_count": int,
        "file_identity": dict,
        "state": str,
        "completed_steps": dict,
    }
    invalid = [key for key, value_type in required.items() if not isinstance(manifest.get(key), value_type)]
    if invalid:
        raise CandidateContractError(f"candidate session has invalid fields: {', '.join(invalid)}")
    expected_steps = ("analysis", "pack", "expected_compare", *VALIDATION_STEPS)
    missing_steps = [key for key in expected_steps if key not in manifest["completed_steps"]]
    if missing_steps:
        raise CandidateContractError(f"candidate session is missing steps: {', '.join(missing_steps)}")
    return manifest


def load_manifest(session_path) -> tuple[Path, dict]:
    session = absolute_path(session_path)
    ensure_real_path(session, require_file=True)
    try:
        manifest = json.loads(session.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"unable to read candidate session {session}: {exc}") from exc
    return session, _validate_manifest(manifest, session)


def update_session(session: Path, manifest: dict, *, state: str | None = None) -> None:
    if state is not None:
        manifest["state"] = state
    atomic_json_write(session, manifest)
