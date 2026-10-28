#!/usr/bin/env python3
"""ghidra_verify.py - a second opinion from Ghidra on what the IDA run left open.

    uv run --extra ghidra ghidra_verify.py -gamever 14193 -oldgamever 14192 -platform linux

Reads manual_todo/<gamever>/<module>.<platform>.txt (the symbols neither the hunter nor
an agent could prove), hunts exactly those with the Ghidra backend and compares each
answer with IDA's best candidate:

    agree       Ghidra proved the address IDA only had as a candidate
    ghidra-only Ghidra proved an address where IDA had no candidate
    disagree    Ghidra proved a different address than IDA's candidate
    same-guess  neither proved it, but both lean towards the same address
    open        neither has an answer worth reporting

Nothing is written into bin/ or bin_artifacts/: Ghidra's evidence rules are not IDA's, so
its answer is a hint for the person (review_issue.py shows it), never an artifact. Its
baseline facts live in ghidra_facts/ (IDA's hunt reads baseline_facts/), its emitted
YAMLs and the result in ghidra_verify/<gamever>/. Each module runs in its own process,
since a JVM is started once per process.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from review_issue import read_todo  # noqa: E402

FACTS_DIR = "ghidra_facts"


def result_path(gamever, module, platform, root=REPO):
    return Path(root) / "ghidra_verify" / str(gamever) / f"{module}.{platform}.json"


def _norm(va):
    return int(va, 16) if va else None


def compare(row, report):
    """Verdict for one manual_todo row against Ghidra's hunt report."""
    symbol, ida = row["symbol"], _norm(row.get("candidate"))
    solved = {r["symbol"]: r for r in report.get("solved", [])}
    if symbol in solved:
        va = _norm(solved[symbol]["va"])
        verdict = "ghidra-only" if ida is None else ("agree" if va == ida else "disagree")
        return {"symbol": symbol, "verdict": verdict, "ghidra": hex(va), "ida": row.get("candidate"),
                "how": solved[symbol].get("how", "")}
    unresolved = {r["symbol"]: r for r in report.get("unresolved", [])}
    top = (unresolved.get(symbol, {}).get("candidates") or [None])[0]
    va = _norm(top["va"]) if top else None
    verdict = "same-guess" if va is not None and va == ida else "open"
    return {"symbol": symbol, "verdict": verdict, "ghidra": hex(va) if va is not None else None,
            "ida": row.get("candidate"), "how": unresolved.get(symbol, {}).get("why", "not hunted")}


def _ghidra_hunt(*args, log):
    cmd = [sys.executable, str(REPO / "ghidra_hunt.py"), *args, "-facts_dir", FACTS_DIR]
    log("    $ " + " ".join(cmd[1:]))
    return subprocess.run(cmd, cwd=REPO).returncode == 0


def verify_module(gamever, oldgamever, module, platform, rows, log=print):
    facts = REPO / FACTS_DIR / str(oldgamever) / f"{module}.{platform}.json"
    if not facts.is_file():
        log(f"==> [ghidra] facts for {oldgamever} {module}.{platform} (first use analyses the binary, slow)")
        if not _ghidra_hunt("facts", "-gamever", str(oldgamever), "-module", module, "-platform", platform, log=log):
            return None
    out = result_path(gamever, module, platform)
    report_path = out.with_suffix(".hunt.json")
    log(f"==> [ghidra] hunting {len(rows)} open symbol(s) in {gamever} {module}.{platform}")
    ok = _ghidra_hunt("hunt", "-gamever", str(gamever), "-module", module, "-platform", platform,
                      "-symbols", ",".join(r["symbol"] for r in rows),
                      "-outdir", str(out.parent / module), "-report", str(report_path), log=log)
    if not ok or not report_path.is_file():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = [compare(row, report) for row in rows]
    out.write_text(json.dumps({"gamever": str(gamever), "baseline": report.get("baseline"),
                               "module": module, "platform": platform, "results": results}, indent=2),
                   encoding="utf-8")
    return results


def load_results(gamever, root=REPO):
    """{(module, platform, symbol): result} from earlier ghidra_verify runs."""
    found = {}
    folder = Path(root) / "ghidra_verify" / str(gamever)
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else ():
        if path.name.endswith(".hunt.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in data.get("results", []):
            found[(data["module"], data["platform"], r["symbol"])] = r
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-oldgamever", required=True)
    ap.add_argument("-platform", required=True, choices=("linux", "windows"))
    args = ap.parse_args()

    groups = {}
    for row in read_todo(args.gamever, platform=args.platform):
        groups.setdefault(row["module"], []).append(row)
    if not groups:
        print(f"==> [ghidra] nothing open for {args.gamever} {args.platform}")
        return 0
    failed = 0
    for module, rows in sorted(groups.items()):
        results = verify_module(args.gamever, args.oldgamever, module, args.platform, rows)
        if results is None:
            print(f"    [ghidra] {module}.{args.platform}: hunt failed, no second opinion")
            failed += 1
            continue
        for r in results:
            print(f"    {r['verdict']:11} {r['symbol']:55} ghidra {r['ghidra'] or '-':12} ida {r['ida'] or '-'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
