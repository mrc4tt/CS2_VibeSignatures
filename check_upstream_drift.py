#!/usr/bin/env python3
"""Report what upstream carries that this fork does not, for skills and YAML.

`sync_upstream.sh` resolves every content conflict in upstream's favour, and this fork
re-asserts its own state afterwards from the declarative tables in
`ensure_local_gamedata_symbols.py`. Both halves are about files that exist on both sides.
Neither answers the other question: did upstream grow a file this fork never received?

That gap is quiet in both directions. A finder skill only loads when its directory name
equals the task name, so a skill upstream added and this fork lacks means the task it backs
has no agent fallback at all - the preprocessor simply fails and the symbol is gone. An
artifact YAML upstream carries and this fork lacks is a symbol nothing here can relocate
from, and the first sign is a hunt that should have been free.

Three states are reported, and only the first is actionable:

    missing     upstream has it, this fork does not  -> the exit code
    modified    both sides have it, contents differ  -> expected, this fork diverges
    fork-only   only this fork has it                -> expected, FORK_OWNED_* and generated

Adding a missing file is a decision rather than a repair, so nothing is ever written here:
an artifact whose find-task this fork does not declare is dropped at pack time as
undeclared, and a skill this fork retired on purpose should stay retired.

    uv run check_upstream_drift.py                  # both sections
    uv run check_upstream_drift.py -full            # every path, not just per-directory counts
    uv run check_upstream_drift.py -fetch           # git fetch upstream first
    uv run check_upstream_drift.py -skills          # one section only
    uv run check_upstream_drift.py -ref origin/main # compare against something else
    uv run check_upstream_drift.py -json            # machine-readable

Exit code 1 when upstream has files this fork lacks, 2 on a setup problem (no such ref,
not a repository, fetch failed).
"""

import argparse
import json
import os
import subprocess
import sys

SKILLS_PATH = ".claude/skills"
YAML_GLOB = "*.yaml"

# ensure_agent_fallback_skills.py stamps what it writes, and only rewrites stamped files
# even under -force. The same marker separates a generated fork-only skill from one written
# by hand here, which is the difference between "regenerate it" and "someone decided this".
GENERATED_MARKER = "auto-generated"


class GitError(RuntimeError):
    """A git invocation this tool cannot work without."""


def run_git(args, repo_root=None):
    """Return stdout of a git command, raising GitError with git's own message."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout


def diff_names(ref, status, pathspec, repo_root=None):
    """Paths differing from *ref* under one status letter.

    ``git diff <ref>`` reads *ref* as the old side and this working tree as the new one, so
    D means upstream has a file this fork does not, and A means the reverse.
    """
    output = run_git(
        ["diff", "--name-only", f"--diff-filter={status}", ref, "--", pathspec],
        repo_root=repo_root,
    )
    return [line for line in output.splitlines() if line]


def untracked_paths(pathspec, repo_root=None):
    """Files git has never seen - a new gamever's artifacts until they are committed.

    ``git diff`` cannot see these, so they belong in the report as their own line rather
    than silently missing from the fork-only count.
    """
    output = run_git(
        ["ls-files", "--others", "--exclude-standard", "--", pathspec],
        repo_root=repo_root,
    )
    return [line for line in output.splitlines() if line]


def group_by_directory(paths):
    """Count paths per ``<top>/<second>`` component, most populated first."""
    counts = {}
    for path in paths:
        parts = path.split("/")
        key = "/".join(parts[:2]) if len(parts) > 1 else path
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def split_generated(paths, repo_root=None):
    """Split fork-only skill files into generated and hand-written.

    A file that no longer exists (deleted since the diff) counts as hand-written: the
    conservative answer, since the generators refuse to touch anything unstamped.
    """
    generated, handwritten = [], []
    for path in paths:
        full_path = os.path.join(repo_root, path) if repo_root else path
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
                stamped = GENERATED_MARKER in handle.read().lower()
        except OSError:
            stamped = False
        (generated if stamped else handwritten).append(path)
    return generated, handwritten


def collect_section(ref, pathspec, repo_root=None):
    """The three states for one pathspec."""
    return {
        "missing": diff_names(ref, "D", pathspec, repo_root=repo_root),
        "modified": diff_names(ref, "M", pathspec, repo_root=repo_root),
        "fork_only": diff_names(ref, "A", pathspec, repo_root=repo_root),
    }


def _print_paths(paths, prefix):
    for path in paths:
        print(f"    {prefix} {path}")


def _print_groups(paths):
    for directory, count in group_by_directory(paths):
        print(f"    {count:>6}  {directory}")


def report_skills(section, full):
    print(f"### {SKILLS_PATH}")
    if section["missing"]:
        print(f"  MISSING here, present upstream: {len(section['missing'])}")
        _print_paths(section["missing"], "-")
        print("    (a skill only loads when its directory name equals the task name;")
        print("     regenerate the generated ones with: uv run ensure_agent_fallback_skills.py)")
    else:
        print("  missing: none")

    if section["modified"]:
        print(f"  content differs: {len(section['modified'])}")
        _print_paths(section["modified"], "~")
    else:
        print("  content differs: none")

    if section["fork_only"]:
        generated, handwritten = section["generated"], section["handwritten"]
        print(
            f"  fork-only: {len(section['fork_only'])} file(s) - "
            f"{len(generated)} auto-generated, {len(handwritten)} hand-written"
        )
        if full:
            _print_paths(section["fork_only"], "+")
    else:
        print("  fork-only: none")
    print()


def report_yaml(section, full):
    print(f"### {YAML_GLOB}")
    if section["missing"]:
        print(f"  MISSING here, present upstream: {len(section['missing'])}")
        _print_groups(section["missing"])
        _print_paths(section["missing"], "-")
        print("    (adding one is a decision, not a repair: an artifact with no declaring")
        print("     find-task is dropped at pack time as undeclared)")
    else:
        print("  missing: none")

    if section["modified"]:
        print(f"  content differs: {len(section['modified'])}")
        _print_groups(section["modified"])
        if full:
            _print_paths(section["modified"], "~")
        else:
            print("    (-full lists them)")
    else:
        print("  content differs: none")

    if section["fork_only"]:
        print(f"  fork-only: {len(section['fork_only'])}")
        _print_groups(section["fork_only"])
        if full:
            _print_paths(section["fork_only"], "+")
    else:
        print("  fork-only: none")

    if section["untracked"]:
        print(f"  untracked here (not part of any comparison): {len(section['untracked'])}")
        _print_groups(section["untracked"])
    print()


def build_report(ref, repo_root=None, want_skills=True, want_yaml=True):
    """Collect every section without printing, so -json and the text report agree."""
    report = {"ref": ref, "sections": {}}
    if want_skills:
        skills = collect_section(ref, SKILLS_PATH, repo_root=repo_root)
        generated, handwritten = split_generated(skills["fork_only"], repo_root=repo_root)
        skills["generated"] = generated
        skills["handwritten"] = handwritten
        report["sections"]["skills"] = skills
    if want_yaml:
        yamls = collect_section(ref, YAML_GLOB, repo_root=repo_root)
        yamls["untracked"] = untracked_paths(YAML_GLOB, repo_root=repo_root)
        report["sections"]["yaml"] = yamls
    report["missing_total"] = sum(len(section["missing"]) for section in report["sections"].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-ref", default="upstream/main", help="what to compare against (default: upstream/main)")
    parser.add_argument("-fetch", action="store_true", help="git fetch upstream before comparing")
    parser.add_argument("-full", action="store_true", help="list every path, not just per-directory counts")
    parser.add_argument("-skills", action="store_true", help="only the .claude/skills section")
    parser.add_argument("-yaml", action="store_true", help="only the *.yaml section")
    parser.add_argument("-json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.abspath(__file__))

    want_skills = args.skills or not args.yaml
    want_yaml = args.yaml or not args.skills

    try:
        run_git(["rev-parse", "--git-dir"], repo_root=repo_root)
        if args.fetch:
            if not args.json:
                print("==> fetching upstream...")
            run_git(["fetch", "upstream", "--quiet"], repo_root=repo_root)
        run_git(["rev-parse", "--verify", "--quiet", args.ref], repo_root=repo_root)
    except GitError as error:
        print(
            f"{error}\n(ref '{args.ref}' unusable - add the remote, or pass -fetch, or -ref <ref>)",
            file=sys.stderr,
        )
        return 2

    report = build_report(args.ref, repo_root=repo_root, want_skills=want_skills, want_yaml=want_yaml)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["missing_total"] else 0

    described = run_git(["log", "-1", "--format=%h %ad", "--date=short", args.ref], repo_root=repo_root).strip()
    print(f"==> comparing working tree against {args.ref} ({described})")
    print()
    if want_skills:
        report_skills(report["sections"]["skills"], args.full)
    if want_yaml:
        report_yaml(report["sections"]["yaml"], args.full)

    if report["missing_total"]:
        print(f"==> {report['missing_total']} file(s) exist upstream and not here.")
        return 1
    print("==> nothing upstream is missing here.")
    return 0


if __name__ == "__main__":
    # Reports get piped into head/grep, and the default Python handler turns that closed
    # pipe into a BrokenPipeError traceback on a run that actually succeeded.
    try:
        import signal

        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass
    sys.exit(main())
