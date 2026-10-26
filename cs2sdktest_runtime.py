#!/usr/bin/env python3
"""Helpers for runtime_smoke.sh: CS2SDKTest gamedata and result baselines.

  gamedata CSS_JSON IN_TOML OUT_TOML
      Rewrite CS2SDKTest's configs/gamedata.toml with the values from our
      CounterStrikeSharp gamedata.json. Only the windows/linux/value lines of
      sections CSS knows change; comments and keys CSS lacks are kept and listed.

  compare RESULT_DIR BASELINE [--accept]
      Compare results.json(l) of an autorun with the baseline. A call that was OK
      and no longer is, a new FAILED/CRASHED/SUSPECT, or a run that never
      completed is a regression. --accept writes the run as the new baseline.

Exit: 0 fine, 1 regressions, 2 unusable input.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# toml key -> CSS gamedata.json key, where the names differ
CSS_ALIASES = {
    "ISource2GameEntities_CheckTransmit": "ISource2GameEntities::CheckTransmit",
}
BAD_OUTCOMES = {"FAILED", "CRASHED", "SUSPECT"}

SECTION_RE = re.compile(r"^\[(signatures|vtables|offsets)\.(\w+)\]\s*$")
VALUE_RE = re.compile(r"^(windows|linux|value)(\s*=\s*)(.*?)\s*$")


def css_values(css, kind, key):
    """Return {"windows": ..., "linux": ...} for a toml section, or None."""
    entry = css.get(CSS_ALIASES.get(key, key))
    if not isinstance(entry, dict):
        return None
    values = entry.get("signatures" if kind == "signatures" else "offsets")
    if not isinstance(values, dict):
        return None
    return {p: values[p] for p in ("windows", "linux") if values.get(p) is not None}


def toml_literal(kind, value):
    if kind == "signatures":
        return json.dumps(str(value))
    return str(int(value))


def convert_gamedata(css_path, in_path, out_path):
    try:
        css = json.loads(Path(css_path).read_text(encoding="utf-8"))
        lines = Path(in_path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as e:
        print(f"gamedata: {e}", file=sys.stderr)
        return 2

    out = []
    kind = key = values = None
    changed, missing = [], []
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            kind, key = m.groups()
            values = css_values(css, kind, key)
            if values is None:
                missing.append(f"{kind}.{key}")
            out.append(line)
            continue
        m = VALUE_RE.match(line)
        if not m or not values:
            out.append(line)
            continue
        field, sep, old = m.groups()
        if field == "value":
            win, lin = values.get("windows"), values.get("linux")
            if win is not None and lin is not None and win != lin:
                new_lines = [f"windows = {toml_literal(kind, win)}",
                             f"linux   = {toml_literal(kind, lin)}"]
            else:
                shared = win if win is not None else lin
                new_lines = [f"value{sep}{toml_literal(kind, shared)}"]
        elif field in values:
            new_lines = [f"{field}{sep}{toml_literal(kind, values[field])}"]
        else:
            new_lines = [line]
        if new_lines != [line]:
            changed.append(f"{kind}.{key}.{field}: {old} -> {' / '.join(new_lines)}")
        out.extend(new_lines)

    Path(out_path).write_text("\n".join(out) + "\n", encoding="utf-8")
    for c in changed:
        print(f"gamedata: {c}")
    for k in missing:
        print(f"gamedata: {k} not in CSS gamedata, kept upstream value")
    return 0


def load_results(result_dir):
    """Return (header, [(key, outcome, detail)], unfinished call or None)."""
    result_dir = Path(result_dir)
    header, results = {}, []
    json_path = result_dir / "results.json"
    if json_path.is_file():
        try:
            header = json.loads(json_path.read_text(encoding="utf-8"))
            results = header.pop("results", [])
        except ValueError:
            header, results = {}, []

    unfinished = None
    jsonl_path = result_dir / "results.jsonl"
    if jsonl_path.is_file():
        open_calls = {}
        streamed = []
        for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            call = (ev.get("suite"), ev.get("call"))
            if ev.get("ev") == "begin":
                open_calls[call] = True
            elif ev.get("ev") == "result":
                open_calls.pop(call, None)
                streamed.append(ev)
        if open_calls:
            unfinished = "{}: {}".format(*next(reversed(open_calls)))
        if not results:
            results = streamed

    seen = Counter()
    keyed = []
    for r in results:
        base = f"{r['suite']}\t{r['call']}"
        seen[base] += 1
        key = base if seen[base] == 1 else f"{base}#{seen[base]}"
        keyed.append((key, r["outcome"], r.get("detail", "")))
    return header, keyed, unfinished


def compare_results(result_dir, baseline_path, accept):
    header, results, unfinished = load_results(result_dir)
    if not results and unfinished is None:
        print(f"compare: no results in {result_dir}", file=sys.stderr)
        return 2
    completed = bool(header.get("completed"))
    summary = header.get("summary", {})
    print(f"compare: {header.get('s2sdk', '?')} completed={completed} {summary}")

    baseline_path = Path(baseline_path)
    if accept:
        if not completed:
            print("compare: run did not complete, not accepting it", file=sys.stderr)
            return 1
        lines = [f"{outcome}\t{key}" for key, outcome, _ in results]
        baseline_path.write_text(
            "# CS2SDKTest outcomes accepted by runtime_smoke.sh --accept: outcome<TAB>suite<TAB>call\n"
            + "\n".join(sorted(lines)) + "\n", encoding="utf-8")
        print(f"compare: wrote {len(lines)} outcomes to {baseline_path}")
        return 0

    baseline = {}
    if baseline_path.is_file():
        for line in baseline_path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                outcome, key = line.split("\t", 1)
                baseline[key] = outcome
    else:
        print(f"compare: no baseline {baseline_path}, every bad outcome counts")

    regressions, fixed = [], []
    current = {}
    for key, outcome, detail in results:
        current[key] = outcome
        was = baseline.get(key)
        call = key.replace("\t", ": ")
        if was == "OK" and outcome != "OK":
            regressions.append(f"{call}: OK -> {outcome} {detail}".rstrip())
        elif outcome in BAD_OUTCOMES and was != outcome:
            regressions.append(f"{call}: {was or 'new'} -> {outcome} {detail}".rstrip())
        elif was is not None and was != "OK" and outcome == "OK":
            fixed.append(f"{call}: {was} -> OK")
    if completed:
        for key, was in baseline.items():
            if was == "OK" and key not in current:
                regressions.append(f"{key.replace(chr(9), ': ')}: OK -> gone")
    else:
        regressions.append(f"run did not complete, last call started: {unfinished or 'unknown'}")

    for f in fixed:
        print(f"fixed: {f}")
    for r in regressions:
        print(f"REGRESSION: {r}")
    return 1 if regressions else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gamedata")
    g.add_argument("css_json")
    g.add_argument("in_toml")
    g.add_argument("out_toml")
    c = sub.add_parser("compare")
    c.add_argument("result_dir")
    c.add_argument("baseline")
    c.add_argument("--accept", action="store_true")
    args = parser.parse_args()
    if args.cmd == "gamedata":
        return convert_gamedata(args.css_json, args.in_toml, args.out_toml)
    return compare_results(args.result_dir, args.baseline, args.accept)


if __name__ == "__main__":
    sys.exit(main())
