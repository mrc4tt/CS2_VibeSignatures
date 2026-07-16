"""Resolve versioned analysis configs from the worktree or Git history."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


GAMEVER_RE = re.compile(r"^[0-9]{4,10}[a-z]?$")
REPO_ROOT = Path(__file__).resolve().parent


class AnalysisConfigError(RuntimeError):
    """Raised when an analysis config cannot be selected safely."""


@dataclass(frozen=True)
class HistoricalConfig:
    revision: str
    repository_path: str
    data: bytes
    sha256: str
    used_legacy_root: bool


def _validated_gamever(gamever: str) -> str:
    value = str(gamever)
    if not GAMEVER_RE.fullmatch(value):
        raise AnalysisConfigError(f"Invalid GAMEVER: {gamever!r}")
    return value


def analysis_config_repo_path(gamever: str) -> str:
    """Return the canonical repository-relative path for one game version."""
    return f"configs/{_validated_gamever(gamever)}.yaml"


def default_analysis_config_path(gamever: str, *, repo_root: Path | None = None) -> Path:
    """Return the repository-root-anchored default analysis config path."""
    root = Path(repo_root or REPO_ROOT).expanduser().resolve()
    expected = root / analysis_config_repo_path(gamever)
    resolved = expected.resolve()
    config_root = (root / "configs").resolve()
    if resolved.parent != config_root:
        raise AnalysisConfigError(f"Analysis config escapes configs directory: {expected}")
    return resolved


def _require_plain_file(path: Path) -> Path:
    if not path.exists():
        raise AnalysisConfigError(f"Analysis config file not found: {path}")
    if not path.is_file():
        raise AnalysisConfigError(f"Analysis config is not a plain file: {path}")
    return path


def resolve_analysis_config(
    gamever: str,
    explicit_path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
) -> Path:
    """Resolve and require one current-worktree analysis config."""
    _validated_gamever(gamever)
    if explicit_path is None:
        return _require_plain_file(default_analysis_config_path(gamever, repo_root=repo_root))
    path = Path(explicit_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return _require_plain_file(path.resolve())


def analysis_config_sha256(path: str | Path) -> str:
    """Return the SHA-256 of the exact analysis-config file bytes."""
    resolved = _require_plain_file(Path(path).expanduser().resolve())
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def _resolved_revision(revision: str, repo_root: Path) -> str:
    if not revision or "\0" in revision:
        raise AnalysisConfigError("Git revision must be non-empty")
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown revision"
        raise AnalysisConfigError(f"Unable to resolve Git revision {revision!r}: {detail}")
    return result.stdout.strip().lower()


def _read_git_blob(repo_root: Path, revision: str, repository_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{revision}:{repository_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def read_analysis_config_at_revision(
    revision: str,
    gamever: str,
    *,
    allow_legacy_root: bool,
    repo_root: Path | None = None,
) -> HistoricalConfig:
    """Read exact analysis-config bytes from one Git revision."""
    root = Path(repo_root or REPO_ROOT).expanduser().resolve()
    resolved_revision = _resolved_revision(revision, root)
    candidates = [(analysis_config_repo_path(gamever), False)]
    if allow_legacy_root:
        candidates.append(("config.yaml", True))
    for repository_path, used_legacy_root in candidates:
        data = _read_git_blob(root, resolved_revision, repository_path)
        if data is not None:
            return HistoricalConfig(
                revision=resolved_revision,
                repository_path=repository_path,
                data=data,
                sha256=hashlib.sha256(data).hexdigest(),
                used_legacy_root=used_legacy_root,
            )
    expected = analysis_config_repo_path(gamever)
    legacy = " or legacy config.yaml" if allow_legacy_root else ""
    raise AnalysisConfigError(f"Analysis config not found at {resolved_revision}: expected {expected}{legacy}")
