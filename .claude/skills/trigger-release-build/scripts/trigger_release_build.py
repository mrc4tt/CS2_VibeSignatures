#!/usr/bin/env python3
"""Dispatch a same-version release rebuild from immutable origin/main."""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ALLOWED_REPOSITORIES = {"HLND2T/CS2_VibeSignatures", "hzqst/CS2_VibeSignatures"}
GAMEVER_RE = re.compile(r"^[0-9]{4,10}[a-z]?$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WORKFLOW = "build-on-self-runner.yml"
RUN_LIST_LIMIT = "100"
RUN_DISCOVERY_ATTEMPTS = 10
RUN_DISCOVERY_DELAY_SECONDS = 2


class TriggerError(Exception):
    """Raised when a dispatch safety precondition is not satisfied."""


def run_command(command: list[str], cwd: Path, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode not in allowed:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        raise TriggerError(f"{' '.join(command)} failed: {detail}")
    return result


def repository_root() -> Path:
    expected = Path(__file__).resolve().parents[4]
    result = run_command(["git", "rev-parse", "--show-toplevel"], expected)
    actual = Path(result.stdout.strip()).resolve()
    if actual != expected:
        raise TriggerError(f"skill is not running in its owning repository: {actual}")
    return actual


def parse_repository(remote_url: str) -> str:
    patterns = (
        r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, remote_url.strip())
        if match:
            return match.group("repo")
    raise TriggerError(f"unsupported origin URL: {remote_url}")


def require_repository(root: Path) -> str:
    remote = run_command(["git", "remote", "get-url", "origin"], root).stdout.strip()
    repository = parse_repository(remote)
    if repository not in ALLOWED_REPOSITORIES:
        raise TriggerError(f"origin repository is not allowlisted: {repository}")
    return repository


def require_github_access(root: Path, repository: str) -> None:
    run_command(["gh", "auth", "status", "--hostname", "github.com"], root)
    permission = run_command(["gh", "api", f"repos/{repository}", "--jq", ".permissions.push"], root).stdout.strip()
    if permission != "true":
        raise TriggerError(f"authenticated GitHub account cannot dispatch Actions for {repository}")
    run_command(["gh", "api", f"repos/{repository}/actions/workflows/{WORKFLOW}", "--jq", ".id"], root)


def resolve_source(root: Path) -> tuple[str, str]:
    run_command(["git", "fetch", "origin", "main:refs/remotes/origin/main", "--prune"], root)
    source_sha = run_command(["git", "rev-parse", "origin/main"], root).stdout.strip().lower()
    if not SHA_RE.fullmatch(source_sha):
        raise TriggerError("origin/main did not resolve to a full commit SHA")
    subject = run_command(["git", "show", "-s", "--format=%s", source_sha], root).stdout.strip()
    return source_sha, subject


def available_versions(root: Path, source_sha: str) -> list[str]:
    raw = run_command(["git", "show", f"{source_sha}:download.yaml"], root).stdout
    try:
        downloads = yaml.safe_load(raw).get("downloads", [])
    except (AttributeError, yaml.YAMLError) as exc:
        raise TriggerError("download.yaml at origin/main is invalid") from exc
    versions = [str(item.get("tag", "")) for item in downloads if isinstance(item, dict)]
    if not versions or any(not GAMEVER_RE.fullmatch(version) for version in versions):
        raise TriggerError("download.yaml contains no valid release versions")
    return versions


def select_version(requested: str, versions: list[str]) -> str:
    if requested == "latest":
        return versions[-1]
    if not GAMEVER_RE.fullmatch(requested):
        raise TriggerError(f"invalid requested GAMEVER: {requested}")
    if requested not in versions:
        raise TriggerError(f"GAMEVER {requested} is absent from download.yaml at origin/main")
    return requested


def require_existing_release(root: Path, repository: str, gamever: str) -> None:
    tag = run_command(
        ["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{gamever}"],
        root,
        allowed=(0, 2),
    )
    if tag.returncode == 2 or not tag.stdout.strip():
        raise TriggerError(f"republish requires existing tag {gamever}")
    release = run_command(["gh", "release", "view", gamever, "--repo", repository], root, allowed=(0, 1))
    if release.returncode != 0:
        raise TriggerError(f"republish requires existing Release {gamever}")


def parse_json_list(raw: str, label: str) -> list[dict]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise TriggerError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TriggerError(f"{label} did not return a JSON list")
    return value


def list_runs(root: Path) -> list[dict]:
    result = run_command(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--limit",
            RUN_LIST_LIMIT,
            "--json",
            "databaseId,displayTitle,status,url,headSha,event",
        ],
        root,
    )
    return parse_json_list(result.stdout, "gh run list")


def require_no_duplicate(root: Path, gamever: str) -> set[int]:
    pulls = run_command(
        ["gh", "pr", "list", "--state", "open", "--limit", RUN_LIST_LIMIT, "--json", "headRefName,url"], root
    )
    for pull in parse_json_list(pulls.stdout, "gh pr list"):
        if str(pull.get("headRefName", "")).startswith(f"gamesymbols/{gamever}/build-"):
            raise TriggerError(f"an output PR is already open for {gamever}: {pull.get('url')}")
    runs = list_runs(root)
    title = f"Release build {gamever}"
    for run in runs:
        if run.get("status") in {"queued", "in_progress"} and run.get("displayTitle") == title:
            raise TriggerError(f"a release build is already active for {gamever}: {run.get('url')}")
    return {int(run["databaseId"]) for run in runs if "databaseId" in run}


def require_main_unchanged(root: Path, source_sha: str) -> None:
    result = run_command(["git", "ls-remote", "--heads", "origin", "refs/heads/main"], root)
    remote_sha = result.stdout.split()[0].lower() if result.stdout.split() else ""
    if remote_sha != source_sha:
        raise TriggerError("origin/main advanced while validating the rebuild request; run the skill again")


def dispatch(root: Path, gamever: str, source_sha: str) -> None:
    run_command(
        [
            "gh",
            "workflow",
            "run",
            WORKFLOW,
            "--ref",
            "main",
            "-f",
            f"gamever={gamever}",
            "-f",
            f"source_sha={source_sha}",
            "-f",
            "mode=republish",
        ],
        root,
    )


def discover_run(root: Path, known_ids: set[int], *, gamever: str, source_sha: str) -> str:
    for _attempt in range(RUN_DISCOVERY_ATTEMPTS):
        for run in list_runs(root):
            run_id = int(run.get("databaseId", 0))
            if (
                run_id not in known_ids
                and run.get("displayTitle") == f"Release build {gamever}"
                and run.get("event") == "workflow_dispatch"
                and run.get("headSha") == source_sha
            ):
                return str(run.get("url"))
        time.sleep(RUN_DISCOVERY_DELAY_SECONDS)
    raise TriggerError("workflow was dispatched but its Actions run URL could not be discovered")


def execute(requested: str) -> dict:
    root = repository_root()
    repository = require_repository(root)
    require_github_access(root, repository)
    source_sha, subject = resolve_source(root)
    gamever = select_version(requested, available_versions(root, source_sha))
    require_existing_release(root, repository, gamever)
    known_ids = require_no_duplicate(root, gamever)
    require_main_unchanged(root, source_sha)
    dispatch(root, gamever, source_sha)
    run_url = discover_run(root, known_ids, gamever=gamever, source_sha=source_sha)
    return {"gamever": gamever, "source_sha": source_sha, "subject": subject, "run_url": run_url}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gamever", help="A version in download.yaml, or latest")
    args = parser.parse_args(argv)
    try:
        result = execute(args.gamever)
    except (TriggerError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Selected GAMEVER: {result['gamever']}")
    print(f"SOURCE_SHA: {result['source_sha']}")
    print(f"Commit: {result['subject']}")
    print(f"Actions run: {result['run_url']}")
    return 0
