#!/usr/bin/env python3
"""emit_artifact.py - turn an address you already trust into a pipeline artifact.

The manual half of a hunt is finding the thing in IDA; the mechanical half is
writing the YAML the pipeline expects, with relocatable bytes wildcarded and the
pattern grown until it is unique. This tool does the mechanical half from the
command line, using the same code the Ctrl-Alt-E hotkey runs inside IDA
(ida_sig_maker.py), on a TEMPORARY COPY of the warm .i64 so an open IDA GUI is
never touched and no re-analysis happens.

    uv run emit_artifact.py -gamever 14182 -module server -platform linux \
        -symbol CCSPointScript_OnCustomHudClicked -kind func -ea 0xb27740
    uv run emit_artifact.py ... -symbol CBaseTrigger_EndTouch -kind vfunc -class CBaseTrigger -index 151
    uv run emit_artifact.py ... -symbol CGameEntitySystem_m_entityListeners -kind structmember \
        -ea 0x16f6bce -struct CGameEntitySystem -member m_entityListeners -size 8
    uv run emit_artifact.py ... -symbol IGameSystem_InitAllSystems_pFirst -kind gv -ea 0xf022a6
    uv run emit_artifact.py ... -symbol X_Patch -kind patch -ea 0x15dacf9 -patch_bytes "EB 7E"

The artifact lands in bin_artifacts/<gamever>/<module>/ (override with -outdir)
and is then checked with validate_artifacts.py for that module, so a wrong
identification or a non-unique pattern is reported before anything is committed.
A unique pattern proves placement, not identity (CLAUDE.md rule 12): the caller
vouches for the address.
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
SCRIPT = REPO / "ida_sig_maker.py"

BINARY_NAMES = {
    ("server", "linux"): "libserver.so", ("server", "windows"): "server.dll",
    ("engine", "linux"): "libengine2.so", ("engine", "windows"): "engine2.dll",
    ("client", "linux"): "libclient.so", ("client", "windows"): "client.dll",
    ("networksystem", "linux"): "libnetworksystem.so", ("networksystem", "windows"): "networksystem.dll",
    ("matchmaking", "linux"): "libmatchmaking.so", ("matchmaking", "windows"): "matchmaking.dll",
    ("vphysics2", "linux"): "libvphysics2.so", ("vphysics2", "windows"): "vphysics2.dll",
    ("scenesystem", "linux"): "libscenesystem.so", ("scenesystem", "windows"): "scenesystem.dll",
    ("worldrenderer", "linux"): "libworldrenderer.so", ("worldrenderer", "windows"): "worldrenderer.dll",
    ("SDL3", "linux"): "libSDL3.so.0", ("SDL3", "windows"): "SDL3.dll",
}


def find_ida(explicit):
    for candidate in (explicit, os.environ.get("IDA_EXE"), shutil.which("idat"),
                      os.path.expanduser("~/ida-pro-9.1/idat"), "/root/ida-pro-9.1/idat", "/opt/ida-pro/idat"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SystemExit("IDA not found: pass -ida or set IDA_EXE")


def build_rule(args):
    rule = {"kind": args.kind}
    if args.ea:
        rule["ea"] = args.ea
    if args.kind == "vfunc":
        if not args.cls or args.index is None:
            raise SystemExit("-kind vfunc needs -class and -index")
        rule.update({"class": args.cls, "index": args.index})
        if args.vtable_name:
            rule["vtable_name"] = args.vtable_name
    elif args.kind == "structmember":
        if not (args.ea and args.struct and args.member):
            raise SystemExit("-kind structmember needs -ea, -struct and -member")
        rule.update({"struct_name": args.struct, "member_name": args.member, "size": args.size or 4})
        if args.operand is not None:
            rule["operand"] = args.operand
    elif args.kind == "patch":
        if not (args.ea and args.patch_bytes):
            raise SystemExit("-kind patch needs -ea and -patch_bytes")
        rule["patch_bytes"] = args.patch_bytes
    elif args.kind in ("func", "gv"):
        if not args.ea:
            raise SystemExit(f"-kind {args.kind} needs -ea")
    return rule


def run(args):
    binary = Path(args.binary) if args.binary else REPO / args.bindir / args.gamever / args.module / BINARY_NAMES[(args.module, args.platform)]
    if not binary.is_file():
        raise SystemExit(f"binary not found: {binary}")
    idb = Path(f"{binary}.i64")
    outdir = Path(args.outdir) if args.outdir else REPO / "bin_artifacts" / args.gamever / args.module
    outdir.mkdir(parents=True, exist_ok=True)
    ida = find_ida(args.ida)
    rule = build_rule(args)
    with tempfile.TemporaryDirectory(prefix="cs2_emit_") as scratch:
        work = Path(scratch)
        # keep the binary's real name so detect_target() still sees bin/<gamever>/<module>/<name>
        stage = work / "bin" / args.gamever / args.module
        stage.mkdir(parents=True)
        staged_binary = stage / binary.name
        os.symlink(binary.resolve(), staged_binary)
        if idb.is_file():
            shutil.copyfile(idb, f"{staged_binary}.i64")  # the GUI may hold the original open
            target = f"{staged_binary}.i64"
            print(f"[emit] using a copy of the warm IDB {idb}")
        else:
            target = str(staged_binary)
            print("[emit] no .i64 next to the binary: IDA will analyse from scratch (slow)")
        job = {
            "queue": args.symbol,
            "rules": {args.symbol: rule},
            "module": args.module,
            "platform": args.platform,
            "output_dir": str(outdir),
            "report_path": str(work / "result.json"),
        }
        (work / "job.json").write_text(json.dumps(job), encoding="utf-8")
        shutil.copyfile(SCRIPT, work / "runner.py")
        env = os.environ.copy()
        env["CS2_SIG_MAKER_JOB"] = str(work / "job.json")
        env.setdefault("TVHEADLESS", "1")
        log = work / "ida.log"
        command = [ida, "-A", f"-L{log}", "-Srunner.py", target]
        print("[emit]", " ".join(command))
        proc = subprocess.run(command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout, check=False, text=True)
        report_path = work / "result.json"
        if not report_path.is_file():
            print(proc.stdout[-2000:])
            print(log.read_text(errors="replace")[-2000:] if log.is_file() else "")
            raise SystemExit(f"IDA exited {proc.returncode} without a report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
    for row in report["results"]:
        print(f"[emit] {row['symbol']}: {row['status']}" + (f" -> {row.get('output')}" if row.get("output") else f" ({row.get('reason')})"))
    if report["resolved"] != 1:
        return 1
    out = outdir / f"{args.symbol}.{args.platform}.yaml"
    print(out.read_text(encoding="utf-8"))
    if args.no_validate:
        return 0
    check = subprocess.run([sys.executable, str(REPO / "validate_artifacts.py"), "-gamever", args.gamever,
                            "-module", args.module, "-platform", args.platform, "-artifactdir", str(outdir.parent.parent)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO)
    lines = [l for l in check.stdout.splitlines() if args.symbol in l or l.startswith(("error", "warning")) and args.symbol in l or "artifacts checked" in l]
    print("\n".join(lines) if lines else check.stdout[-800:])
    return 0 if check.returncode == 0 else 2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-module", required=True)
    ap.add_argument("-platform", required=True, choices=("linux", "windows"))
    ap.add_argument("-symbol", required=True)
    ap.add_argument("-kind", required=True, choices=("func", "vfunc", "structmember", "gv", "patch"))
    ap.add_argument("-ea", help="hex address: function head / instruction (structmember, gv, patch)")
    ap.add_argument("-class", dest="cls", help="vfunc: RTTI class name owning the vtable")
    ap.add_argument("-index", type=int, help="vfunc: 0-based slot index on THIS platform")
    ap.add_argument("-vtable_name", help="vfunc: vtable_name field when it differs from -class")
    ap.add_argument("-struct"); ap.add_argument("-member"); ap.add_argument("-size", type=int); ap.add_argument("-operand", type=int)
    ap.add_argument("-patch_bytes")
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-binary", help="explicit binary path (its .i64 is used when present)")
    ap.add_argument("-outdir", help="default bin_artifacts/<gamever>/<module>")
    ap.add_argument("-ida", help="IDA executable (default: IDA_EXE, idat on PATH, ~/ida-pro-9.1/idat)")
    ap.add_argument("-timeout", type=int, default=900)
    ap.add_argument("-no_validate", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
