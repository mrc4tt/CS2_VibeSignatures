#!/usr/bin/env python3
"""baseline_facts.py - extract hunt facts from a baseline IDB, once per gamever/module/platform.

    uv run baseline_facts.py -gamever 14181 -module server -platform linux

Runs ida_baseline_facts.py headless on a TEMPORARY COPY of bin/<gamever>/<module>/<binary>.i64
and writes baseline_facts/<gamever>/<module>.<platform>.json. ida_auto_hunt.py (GUI hotkey
and auto_hunt_ida.py CLI) reads it when hunting the next gamever.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from emit_artifact import BINARY_NAMES, find_ida  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-module", required=True)
    ap.add_argument("-platform", required=True, choices=("linux", "windows"))
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-artifactdir", default="bin_artifacts")
    ap.add_argument("-ida")
    ap.add_argument("-timeout", type=int, default=1800)
    args = ap.parse_args()
    binary = REPO / args.bindir / args.gamever / args.module / BINARY_NAMES[(args.module, args.platform)]
    idb = Path(f"{binary}.i64")
    if not idb.is_file():
        raise SystemExit(f"no warm IDB: {idb}")
    artifact_dir = REPO / args.artifactdir / args.gamever / args.module
    out_dir = REPO / "baseline_facts" / args.gamever
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.module}.{args.platform}.json"
    ida = find_ida(args.ida)
    with tempfile.TemporaryDirectory(prefix="cs2_facts_") as scratch:
        work = Path(scratch)
        copy = work / idb.name
        shutil.copyfile(idb, copy)
        os.symlink(binary.resolve(), work / binary.name)
        script = REPO / "ida_baseline_facts.py"
        log = work / "ida.log"
        command = [ida, "-A", f"-L{log}", f'-S{script} {REPO} {artifact_dir} {args.platform} {out}', str(copy)]
        env = os.environ.copy()
        env.setdefault("TVHEADLESS", "1")
        proc = subprocess.run(command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=args.timeout, check=False)
        if not out.is_file():
            print(proc.stdout[-1500:])
            print(log.read_text(errors="replace")[-1500:] if log.is_file() else "")
            raise SystemExit(f"IDA exited {proc.returncode} without writing {out}")
    print(f"[facts] wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
