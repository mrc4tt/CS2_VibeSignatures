import argparse
import subprocess
import traceback
from pathlib import Path

from analysis_config import AnalysisConfigError, resolve_analysis_config
from gamesymbol_snapshot_lib.errors import SnapshotConfigError, SnapshotMismatchError
from gamesymbol_snapshot_lib.operations import load_snapshot_context
from gamesymbol_snapshot_lib.paths import ensure_real_tree, path_from_key
from gamesymbol_snapshot_lib.pr_validation import build_invalidation_plan


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Invalidate PR-affected game-symbol outputs")
    parser.add_argument("invalidate", nargs="?", default="invalidate")
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-baseconfigyaml", required=True)
    parser.add_argument("-basesnapshot", required=True)
    parser.add_argument(
        "-headconfigyaml",
        default=None,
        help="Head analysis config; defaults to configs/<GAMEVER>.yaml",
    )
    parser.add_argument("-headsnapshot")
    parser.add_argument("-baseref", default="HEAD^1")
    parser.add_argument("-headref", default="HEAD")
    parser.add_argument("-debug", action="store_true")
    return parser.parse_args(argv)


def _changed_files(base_ref: str, head_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref, head_ref, "--"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SnapshotConfigError(result.stderr.strip() or "git diff --name-only failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _delete_paths(contract, paths: frozenset[str]) -> int:
    ensure_real_tree(contract.game_root.parent, contract.game_root)
    deleted = 0
    for key in sorted(paths):
        target = path_from_key(contract.game_root, key)
        if target.is_file():
            target.unlink()
            deleted += 1
    return deleted


def _run(args) -> None:
    head_snapshot = args.headsnapshot or f"gamesymbols/{args.gamever}.yaml"
    args.headconfigyaml = str(resolve_analysis_config(args.gamever, args.headconfigyaml))
    print(f"Head analysis config: {args.headconfigyaml}")
    base = load_snapshot_context(args.basesnapshot, args.baseconfigyaml, args.gamever, args.bindir)
    head = load_snapshot_context(head_snapshot, args.headconfigyaml, args.gamever, args.bindir)
    plan = build_invalidation_plan(
        base.contract,
        head.contract,
        base.document,
        head.document,
        _changed_files(args.baseref, args.headref),
        Path.cwd(),
    )
    deleted = _delete_paths(head.contract, plan.paths)
    for reason in plan.reasons:
        print(f"  {reason}")
    for path in sorted(plan.paths):
        print(f"  invalidate: {path}")
    print(f"Invalidated {len(plan.paths)} path(s); deleted {deleted} existing YAML file(s)")


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        _run(args)
    except SnapshotMismatchError as exc:
        print(f"Error: {exc}")
        if args.debug:
            traceback.print_exc()
        return 1
    except (AnalysisConfigError, SnapshotConfigError) as exc:
        print(f"Error: {exc}")
        if args.debug:
            traceback.print_exc()
        return 2
    return 0
