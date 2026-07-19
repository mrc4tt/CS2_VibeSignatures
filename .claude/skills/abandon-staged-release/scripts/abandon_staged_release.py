#!/usr/bin/env python3
"""Dispatch the protected workflow that abandons one unpromoted staged release."""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


ALLOWED_REPOSITORIES = {"HLND2T/CS2_VibeSignatures", "hzqst/CS2_VibeSignatures"}
OUTPUT_BRANCH_RE = re.compile(r"^gamesymbols/build/(?P<gamever>[0-9]{4,10}[a-z]?)/(?P<build_id>[0-9]+-[0-9]+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WORKFLOW = "abandon-staged-release.yml"
RUN_LIST_LIMIT = "50"
RUN_DISCOVERY_ATTEMPTS = 10
RUN_DISCOVERY_DELAY_SECONDS = 2
REASON_MAX_LENGTH = 500


class AbandonError(Exception):
    """Raised when an explicit staged-release abandonment is unsafe."""


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        raise AbandonError(f"{' '.join(command)} failed: {detail}")
    return result


def repository_root() -> Path:
    expected = Path(__file__).resolve().parents[4]
    result = run_command(["git", "rev-parse", "--show-toplevel"], expected)
    actual = Path(result.stdout.strip()).resolve()
    if actual != expected:
        raise AbandonError(f"skill is not running in its owning repository: {actual}")
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
    raise AbandonError(f"unsupported origin URL: {remote_url}")


def require_repository(root: Path) -> str:
    remote = run_command(["git", "remote", "get-url", "origin"], root).stdout.strip()
    repository = parse_repository(remote)
    if repository not in ALLOWED_REPOSITORIES:
        raise AbandonError(f"origin repository is not allowlisted: {repository}")
    return repository


def require_github_access(root: Path, repository: str) -> None:
    run_command(["gh", "auth", "status", "--hostname", "github.com"], root)
    permission = run_command(["gh", "api", f"repos/{repository}", "--jq", ".permissions.push"], root).stdout.strip()
    if permission != "true":
        raise AbandonError(f"authenticated GitHub account cannot dispatch Actions for {repository}")
    run_command(["gh", "api", f"repos/{repository}/actions/workflows/{WORKFLOW}", "--jq", ".id"], root)


def parse_json_object(raw: str, label: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AbandonError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AbandonError(f"{label} did not return a JSON object")
    return value


def parse_json_list(raw: str, label: str) -> list[dict]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise AbandonError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AbandonError(f"{label} did not return a JSON list")
    return value


def resolve_main(root: Path) -> str:
    run_command(["git", "fetch", "origin", "main", "--quiet"], root)
    source_sha = run_command(["git", "rev-parse", "refs/remotes/origin/main"], root).stdout.strip().lower()
    if not SHA_RE.fullmatch(source_sha):
        raise AbandonError("origin/main did not resolve to a full commit SHA")
    run_command(["git", "cat-file", "-e", f"{source_sha}:.github/workflows/{WORKFLOW}"], root)
    return source_sha


def validate_reason(reason: str) -> str:
    reason = reason.strip()
    if not reason or len(reason) > REASON_MAX_LENGTH or any(char in reason for char in "\r\n"):
        raise AbandonError("reason must be one non-empty line of at most 500 characters")
    return reason


def load_pr_identity(root: Path, repository: str, pr_number: int, confirmation: str, reason: str) -> dict:
    raw = run_command(["gh", "api", f"repos/{repository}/pulls/{pr_number}"], root).stdout
    pull = parse_json_object(raw, "pull request lookup")
    head = pull.get("head") or {}
    head_repo = head.get("repo") or {}
    base = pull.get("base") or {}
    author = pull.get("user") or {}
    if pull.get("state") != "closed" or not pull.get("merged_at"):
        raise AbandonError(f"PR #{pr_number} must be merged before its staged build can be abandoned")
    if author.get("login") != "github-actions[bot]":
        raise AbandonError(f"PR #{pr_number} was not created by github-actions[bot]")
    if head_repo.get("full_name") != repository or base.get("ref") != "main":
        raise AbandonError(f"PR #{pr_number} does not match the trusted same-repository main-branch contract")
    match = OUTPUT_BRANCH_RE.fullmatch(str(head.get("ref", "")))
    if not match:
        raise AbandonError(f"PR #{pr_number} does not use the generated-output branch protocol")
    head_sha = str(head.get("sha", "")).lower()
    if not SHA_RE.fullmatch(head_sha):
        raise AbandonError(f"PR #{pr_number} head did not resolve to a full commit SHA")
    gamever, build_id = match.group("gamever"), match.group("build_id")
    expected_confirmation = f"ABANDON {gamever}/{build_id}"
    if confirmation != expected_confirmation:
        raise AbandonError(f"confirmation must exactly equal {expected_confirmation!r}")
    return {
        "pr_number": pr_number,
        "pr_url": str(pull.get("html_url", "")),
        "gamever": gamever,
        "build_id": build_id,
        "head_sha": head_sha,
        "confirmation": confirmation,
        "reason": validate_reason(reason),
    }


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


def require_no_duplicate(root: Path, pr_number: int) -> set[int]:
    runs = list_runs(root)
    title = f"Abandon staged release PR #{pr_number}"
    for run in runs:
        if run.get("status") in {"queued", "in_progress"} and run.get("displayTitle") == title:
            raise AbandonError(f"an abandonment workflow is already active for PR #{pr_number}: {run.get('url')}")
    return {int(run["databaseId"]) for run in runs if "databaseId" in run}


def require_main_unchanged(root: Path, source_sha: str) -> None:
    if resolve_main(root) != source_sha:
        raise AbandonError("origin/main advanced during validation; rerun the skill")


def dispatch(root: Path, identity: dict) -> None:
    run_command(
        [
            "gh",
            "workflow",
            "run",
            WORKFLOW,
            "--ref",
            "main",
            "-f",
            f"pr_number={identity['pr_number']}",
            "-f",
            f"confirmation={identity['confirmation']}",
            "-f",
            f"reason={identity['reason']}",
        ],
        root,
    )


def discover_run(root: Path, known_ids: set[int], *, pr_number: int, source_sha: str) -> str:
    for _attempt in range(RUN_DISCOVERY_ATTEMPTS):
        for run in list_runs(root):
            run_id = int(run.get("databaseId", 0))
            if (
                run_id not in known_ids
                and run.get("displayTitle") == f"Abandon staged release PR #{pr_number}"
                and run.get("event") == "workflow_dispatch"
                and run.get("headSha") == source_sha
            ):
                return str(run.get("url"))
        time.sleep(RUN_DISCOVERY_DELAY_SECONDS)
    raise AbandonError("workflow was dispatched but its Actions run URL could not be discovered")


def execute(pr_number: int, confirmation: str, reason: str) -> dict:
    root = repository_root()
    repository = require_repository(root)
    require_github_access(root, repository)
    source_sha = resolve_main(root)
    identity = load_pr_identity(root, repository, pr_number, confirmation, reason)
    known_ids = require_no_duplicate(root, pr_number)
    require_main_unchanged(root, source_sha)
    dispatch(root, identity)
    identity["run_url"] = discover_run(root, known_ids, pr_number=pr_number, source_sha=source_sha)
    identity["source_sha"] = source_sha
    return identity


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_number", type=int, help="Merged generated-output PR number")
    parser.add_argument("--confirm", required=True, help="Exact ABANDON <gamever>/<build-id> confirmation")
    parser.add_argument("--reason", required=True, help="One-line audit reason")
    args = parser.parse_args(argv)
    if args.pr_number <= 0:
        parser.error("pr_number must be positive")
    try:
        result = execute(args.pr_number, args.confirm, args.reason)
    except (AbandonError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"PR: #{result['pr_number']} ({result['pr_url']})")
    print(f"GAMEVER: {result['gamever']}")
    print(f"BUILD_ID: {result['build_id']}")
    print(f"PR_HEAD_SHA: {result['head_sha']}")
    print(f"Reason: {result['reason']}")
    print(f"Actions run: {result['run_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
