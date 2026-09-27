#!/usr/bin/env python3
"""Write binary_locks/<GAMEVER>.json from the analysed binaries in bin/<GAMEVER>/.

The locks bind a game version to its depot manifests (download.yaml) and to a hash
per module and platform. They stopped at 14181: nothing in the per-build flow wrote
one, and bump_download_candidate.py - the only writer - is the release workflow's
enrollment path, which this fork's autopilot does not take. Anything that resolves
a build through the locks then silently lost every build after 14181; the
cs2-signatures tracker ran without its reference snapshot from 14182 on.

    uv run write_binary_lock.py -gamever 14185          # write (refuses to overwrite)
    uv run write_binary_lock.py -gamever 14185 -check   # compare against the committed lock
    uv run write_binary_lock.py -gamever 14185 -force   # rewrite an existing lock

The binaries are hashed where the run left them (bin/<GAMEVER>/<module>/), which are
the files copy_depot_bin.py took from the download of exactly those manifests.
"""

import argparse
import json
import sys
from pathlib import Path

from binary_lock import BinaryLockError, build_binary_lock_from_root, write_binary_lock
from gamesymbol_snapshot_lib.config import load_contract


def build(gamever: str, root: Path) -> dict:
    contract = load_contract(
        root / "configs" / f"{gamever}.yaml",
        gamever,
        root / "bin",
        artifactdir=root / "bin_artifacts",
    )
    return build_binary_lock_from_root(
        game_version=gamever,
        download_payload=(root / "download.yaml").read_bytes(),
        binary_targets=contract.binary_targets,
        binary_root=root / "bin" / gamever,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-gamever", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-check", action="store_true", help="compare with the committed lock, write nothing")
    mode.add_argument("-force", action="store_true", help="overwrite an existing lock")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    lock_path = root / "binary_locks" / f"{args.gamever}.json"
    try:
        document = build(args.gamever, root)
    except (BinaryLockError, OSError) as exc:
        print(f"binary lock {args.gamever}: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if not lock_path.is_file():
            print(f"binary lock {args.gamever}: missing ({lock_path.relative_to(root)})")
            return 1
        if json.loads(lock_path.read_text()) != document:
            print(f"binary lock {args.gamever}: differs from bin/{args.gamever}/ - the binaries or download.yaml moved")
            return 1
        print(f"binary lock {args.gamever}: matches")
        return 0

    if lock_path.exists() and not args.force:
        print(f"binary lock {args.gamever}: already exists, use -check or -force", file=sys.stderr)
        return 1
    write_binary_lock(lock_path, document)
    modules = sum(len(platforms) for platforms in document["binaries"].values())
    print(f"binary lock {args.gamever}: wrote {lock_path.relative_to(root)} ({modules} binaries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
