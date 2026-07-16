import argparse
import traceback

from analysis_config import AnalysisConfigError, resolve_analysis_config
from gamesymbol_snapshot_lib.errors import SnapshotConfigError, SnapshotMismatchError
from gamesymbol_snapshot_lib.operations import pack_snapshot, restore_snapshot, verify_snapshot


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-gamever", required=True, help="Game version to snapshot")
    parser.add_argument("-bindir", default="bin", help="Binary workspace root")
    parser.add_argument(
        "-configyaml",
        default=None,
        help="Analysis config path; defaults to configs/<GAMEVER>.yaml",
    )
    parser.add_argument("-snapshot", help="Snapshot path; defaults to gamesymbols/<GAMEVER>.yaml")
    parser.add_argument("-debug", action="store_true", help="Print tracebacks on errors")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Pack, restore, or verify game-symbol snapshots")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("pack", "restore", "verify"):
        subparser = commands.add_parser(command)
        _add_common_arguments(subparser)
        if command == "restore":
            subparser.add_argument("-replace", action="store_true", help="Replace only YAML files under the game root")
    return parser.parse_args(argv)


def _run(args) -> None:
    args.configyaml = str(resolve_analysis_config(args.gamever, args.configyaml))
    print(f"Analysis config: {args.configyaml}")
    common = (args.gamever, args.bindir, args.configyaml, args.snapshot)
    if args.command == "pack":
        data = pack_snapshot(*common)
        print(f"Packed {args.snapshot or f'gamesymbols/{args.gamever}.yaml'} ({len(data)} bytes)")
    elif args.command == "restore":
        restore_snapshot(*common, replace=args.replace)
        print(f"Restored game-symbol snapshot for {args.gamever}")
    else:
        verify_snapshot(*common)
        print(f"Verified game-symbol snapshot for {args.gamever}")


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
