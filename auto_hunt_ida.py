#!/usr/bin/env python3
"""auto_hunt_ida.py - run the automatic hunter headless on a copy of the warm IDB.

    uv run auto_hunt_ida.py -gamever 14182 -module server -platform linux [-symbols A,B] [-dry_run] [-outdir DIR]

Needs baseline facts for the previous gamever (baseline_facts.py). Writes the
artifacts to bin_artifacts/<gamever>/<module>/ (or -outdir), a JSON report to
auto_hunt_reports/<gamever>/<module>.<platform>.json, and runs validate_artifacts
for the module unless -no_validate.
"""
import argparse
import json
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
    ap.add_argument("-symbols", help="comma-separated subset")
    ap.add_argument("-dry_run", action="store_true")
    ap.add_argument("-outdir")
    ap.add_argument("-min_score", type=float, default=0.55)
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-ida")
    ap.add_argument("-timeout", type=int, default=3600)
    ap.add_argument("-no_validate", action="store_true")
    args = ap.parse_args()
    binary = REPO / args.bindir / args.gamever / args.module / BINARY_NAMES[(args.module, args.platform)]
    idb = Path(f"{binary}.i64")
    if not idb.is_file():
        raise SystemExit(f"no warm IDB: {idb}")
    outdir = Path(args.outdir) if args.outdir else REPO / "bin_artifacts" / args.gamever / args.module
    outdir.mkdir(parents=True, exist_ok=True)
    report_dir = REPO / "auto_hunt_reports" / args.gamever
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{args.module}.{args.platform}.json"
    ida = find_ida(args.ida)
    with tempfile.TemporaryDirectory(prefix="cs2_hunt_") as scratch:
        work = Path(scratch)
        stage = work / "bin" / args.gamever / args.module
        stage.mkdir(parents=True)
        staged = stage / binary.name
        os.symlink(binary.resolve(), staged)
        shutil.copyfile(idb, f"{staged}.i64")
        job = {"symbols": [s for s in (args.symbols or "").split(",") if s] or None, "dry_run": args.dry_run,
               "out_dir": str(outdir), "report_path": str(report_path), "min_score": args.min_score}
        (work / "job.json").write_text(json.dumps(job), encoding="utf-8")
        shutil.copyfile(REPO / "ida_auto_hunt.py", work / "runner.py")
        env = os.environ.copy()
        env["CS2_AUTO_HUNT_JOB"] = str(work / "job.json")
        env.setdefault("CS2VIBE_REPO", str(REPO))
        env.setdefault("TVHEADLESS", "1")
        log = work / "ida.log"
        command = [ida, "-A", f"-L{log}", "-Srunner.py", f"{staged}.i64"]
        proc = subprocess.run(command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=args.timeout, check=False)
        if not report_path.is_file():
            print(proc.stdout[-2000:]); print(log.read_text(errors="replace")[-3000:] if log.is_file() else "")
            raise SystemExit(f"IDA exited {proc.returncode} without a report")
        text = log.read_text(errors="replace") if log.is_file() else ""
        for line in text.splitlines():
            if line.startswith(("  OK ", "  ?? ", "  CHG", "[auto_hunt]", "[sig_maker]")) or line.startswith("="):
                print(line)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(f"[auto_hunt] report: {report_path}")
    if args.no_validate or args.dry_run or not report["solved"]:
        return 0
    check = subprocess.run([sys.executable, str(REPO / "validate_artifacts.py"), "-gamever", args.gamever, "-module", args.module,
                            "-platform", args.platform, "-artifactdir", str(outdir.parent.parent)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO)
    print("\n".join(l for l in check.stdout.splitlines() if l.startswith(("error", "warning")) or "artifacts checked" in l))
    return 0 if check.returncode == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
