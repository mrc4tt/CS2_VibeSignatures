#!/usr/bin/env python3
"""ghidra_hunt.py - the baseline-facts hunter on Ghidra (PyGhidra), GUI-free and IDA-free.

    uv run --extra ghidra ghidra_hunt.py facts -gamever 14181 -module server -platform linux
    uv run --extra ghidra ghidra_hunt.py hunt  -gamever 14182 -module server -platform linux [-symbols A,B] [-outdir DIR] [-dry_run]
    uv run --extra ghidra ghidra_hunt.py emit  -gamever 14182 -module server -platform linux -symbol X -kind func -ea 0x...

Needs a Ghidra install (GHIDRA_INSTALL_DIR, or ~/ghidra_*_PUBLIC) and the
`ghidra` extra (pyghidra). The program is opened in a Ghidra project under
ghidra_projects/ (created and analysed on first use, reused afterwards; pass
-project_location/-project_name to reuse a project made with analyzeHeadless).
`facts` writes the same tool-neutral baseline_facts JSON the IDA extractor
writes; `hunt` runs hunt_core.Hunter with the Ghidra backend and emits through
hunt_core.emit_artifact; `emit` writes one artifact from an explicit address.
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
import hunt_core  # noqa: E402
from emit_artifact import BINARY_NAMES  # noqa: E402


def ghidra_install_dir():
    explicit = os.environ.get("GHIDRA_INSTALL_DIR")
    if explicit and os.path.isdir(explicit):
        return explicit
    candidates = sorted(glob.glob(os.path.expanduser("~/ghidra_*_PUBLIC")) + glob.glob("/opt/ghidra*"))
    if not candidates:
        raise SystemExit("Ghidra not found: set GHIDRA_INSTALL_DIR")
    return candidates[-1]


def open_program(args, binary):
    import pyghidra
    pyghidra.start(install_dir=Path(ghidra_install_dir()))
    location = args.project_location or str(REPO / "ghidra_projects")
    name = args.project_name or f"cs2_{args.gamever}_{args.module}_{args.platform}"
    os.makedirs(location, exist_ok=True)
    return pyghidra.open_program(str(binary), project_location=location, project_name=name, analyze=True,
                                 program_name=args.program_name)


def binary_for(args):
    binary = REPO / args.bindir / args.gamever / args.module / BINARY_NAMES[(args.module, args.platform)]
    if not binary.is_file():
        raise SystemExit(f"binary not found: {binary}")
    return binary


def cmd_facts(args):
    import ghidra_backend
    binary = binary_for(args)
    artifact_dir = REPO / args.artifactdir / args.gamever / args.module
    out = Path(args.out) if args.out else REPO / "baseline_facts" / args.gamever / f"{args.module}.{args.platform}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open_program(args, binary) as flat:
        backend = ghidra_backend.GhidraBackend(flat, str(binary))
        facts = hunt_core.extract_facts(backend, str(artifact_dir), args.platform, gamever=args.gamever, module=args.module)
    facts["backend"] = "ghidra"
    out.write_text(json.dumps(facts), encoding="utf-8")
    print(f"[facts] wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


def cmd_hunt(args):
    import ghidra_backend
    binary = binary_for(args)
    baseline, facts = hunt_core.load_baseline_facts(str(REPO), args.gamever, args.module, args.platform)
    if not facts:
        raise SystemExit(f"no baseline facts: run  ghidra_hunt.py facts -gamever <prev> -module {args.module} -platform {args.platform}")
    out_dir = Path(args.outdir) if args.outdir else REPO / "auto_hunt_out" / args.gamever / args.module
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir = REPO / "auto_hunt_reports" / args.gamever
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{args.module}.{args.platform}.ghidra.json"
    with open_program(args, binary) as flat:
        backend = ghidra_backend.GhidraBackend(flat, str(binary))
        hunter = hunt_core.Hunter(backend, args.gamever, args.module, args.platform, facts, str(out_dir), dry_run=args.dry_run, min_score=args.min_score)
        symbols = [s for s in (args.symbols or "").split(",") if s] or None
        report = hunter.run(symbols, baseline_artifact_dir=str(REPO / args.artifactdir / baseline / args.module),
                            existing_dirs=(str(REPO / args.artifactdir / args.gamever / args.module),))
    report.update({"gamever": args.gamever, "baseline": baseline, "module": args.module, "platform": args.platform, "backend": "ghidra"})
    hunt_core.print_report(report)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[hunt] report: {report_path}")
    return 0


def cmd_emit(args):
    import ghidra_backend
    binary = binary_for(args)
    out_dir = Path(args.outdir) if args.outdir else REPO / "auto_hunt_out" / args.gamever / args.module
    out_dir.mkdir(parents=True, exist_ok=True)
    rule = {"kind": args.kind}
    for key, value in (("ea", args.ea), ("class", args.cls), ("index", args.index), ("vtable_name", args.vtable_name),
                       ("struct_name", args.struct), ("member_name", args.member), ("size", args.size), ("patch_bytes", args.patch_bytes)):
        if value not in (None, ""):
            rule[key] = value
    with open_program(args, binary) as flat:
        backend = ghidra_backend.GhidraBackend(flat, str(binary))
        scan = hunt_core.Scan(backend.exec_regions())
        path = hunt_core.emit_artifact(backend, scan, args.symbol, rule, str(out_dir), args.platform, log=print)
    print(Path(path).read_text(encoding="utf-8"))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("facts", "hunt", "emit"):
        p = sub.add_parser(name)
        p.add_argument("-gamever", required=True); p.add_argument("-module", required=True)
        p.add_argument("-platform", required=True, choices=("linux", "windows"))
        p.add_argument("-bindir", default="bin"); p.add_argument("-artifactdir", default="bin_artifacts")
        p.add_argument("-project_location"); p.add_argument("-project_name"); p.add_argument("-program_name")
    sub.choices["facts"].add_argument("-out")
    h = sub.choices["hunt"]
    h.add_argument("-symbols"); h.add_argument("-outdir"); h.add_argument("-dry_run", action="store_true"); h.add_argument("-min_score", type=float, default=hunt_core.MIN_SCORE)
    e = sub.choices["emit"]
    e.add_argument("-symbol", required=True); e.add_argument("-kind", required=True, choices=("func", "vfunc", "structmember", "gv", "patch"))
    e.add_argument("-ea"); e.add_argument("-class", dest="cls"); e.add_argument("-index", type=int); e.add_argument("-vtable_name")
    e.add_argument("-struct"); e.add_argument("-member"); e.add_argument("-size", type=int); e.add_argument("-patch_bytes"); e.add_argument("-outdir")
    args = ap.parse_args()
    return {"facts": cmd_facts, "hunt": cmd_hunt, "emit": cmd_emit}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
