#!/usr/bin/env python3
"""
rehunt_queue.py - re-run only the tasks a tracker says went stale.

A new game build is not the only reason to re-analyse. The tracker at
git.miksen.me/mikkel/cs2-signatures compares what plugins ship against what this
repo publishes, and it knows something this box does not: WHICH symbols stopped
resolving. Re-running the whole pipeline for three symbols is hours; re-running
the three tasks that produce them is minutes.

The queue is a small JSON file the tracker writes:

    {"gamever": "14181", "symbols": ["CBaseTrigger_EndTouch", "ClientPrint"]}

A symbol is mapped to its producing task by searching every task's
`expected_output`, never by guessing `find-<Symbol>`: tasks are named after their
anchor and one task emits several symbols (CLAUDE.md).

    uv run rehunt_queue.py -queue https://git.miksen.me/mikkel/cs2-signatures/raw/branch/main/rehunt.json
    uv run rehunt_queue.py -queue .autopilot/rehunt.json -run
    uv run rehunt_queue.py -gamever 14181 -symbols ClientPrint -run

The queue stays in the tracker's own repository and is read over HTTPS, so the
tracker never needs write access to this one.

Planning touches nothing. `-run` analyses into a scratch directory, so
`bin_artifacts/` and `bin/` are left alone and you compare before adopting.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import yaml


def load_config(gamever: str) -> dict:
    path = os.path.join("configs", f"{gamever}.yaml")
    if not os.path.exists(path):
        raise SystemExit(f"no config for {gamever}")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def tasks_for_symbol(config: dict, symbol: str) -> list[dict]:
    """Every task whose expected_output or optional_output mentions this symbol."""
    wanted = {f"{symbol}.{{platform}}.yaml", f"{symbol}.linux.yaml", f"{symbol}.windows.yaml"}
    found = []
    for module in config.get("modules", []) or []:
        for task in module.get("skills", []) or []:
            outputs = []
            for field in ("expected_output", "optional_output"):
                value = task.get(field)
                if isinstance(value, str):
                    outputs.append(value)
                elif isinstance(value, list):
                    outputs.extend(v for v in value if isinstance(v, str))
            if wanted & set(outputs):
                found.append({
                    "module": module.get("name"),
                    "task": task.get("name"),
                    "platform": task.get("platform"),
                    "outputs": outputs,
                })
    return found


def previous_gamever(gamever: str) -> str | None:
    def sort_key(tag: str) -> tuple[int, str]:
        match = re.fullmatch(r"(\d+)([a-z]?)", tag)
        return (int(match.group(1)), match.group(2)) if match else (0, tag)

    tags = [t for t in os.listdir("bin_artifacts") if re.fullmatch(r"\d+[a-z]?", t)] \
        if os.path.isdir("bin_artifacts") else []
    earlier = sorted((t for t in tags if sort_key(t) < sort_key(gamever)), key=sort_key)
    return earlier[-1] if earlier else None


def seed_inputs(scratch: str, gamever: str, module: str) -> None:
    """A task is skipped when its outputs already exist, and its expected_input has
    to be present in the same directory. Seed the module's baseline, minus the
    artifacts this run is meant to replace."""
    source = os.path.join("bin_artifacts", gamever, module)
    target = os.path.join(scratch, gamever, module)
    os.makedirs(target, exist_ok=True)
    if os.path.isdir(source):
        for name in os.listdir(source):
            if name.endswith(".yaml"):
                shutil.copy2(os.path.join(source, name), os.path.join(target, name))


def run_task(entry: dict, gamever: str, old_gamever: str, scratch: str) -> dict:
    module, task = entry["module"], entry["task"]
    platforms = [entry["platform"]] if entry["platform"] else ["linux", "windows"]
    results = []
    for platform in platforms:
        seed_inputs(scratch, gamever, module)
        # Drop the outputs this task owns, or the driver reports it as already done.
        for spec in entry["outputs"]:
            candidate = os.path.join(scratch, gamever, module, spec.replace("{platform}", platform))
            if os.path.exists(candidate):
                os.remove(candidate)
        command = [
            "uv", "run", "ida_analyze_bin.py",
            "-gamever", gamever, "-oldgamever", old_gamever,
            "-platform", platform, "-modules", module, "-skill", task,
            "-require_warm_idb",
            "-artifactdir", scratch, "-oldartifactdir", "bin_artifacts",
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        produced = [
            spec.replace("{platform}", platform)
            for spec in entry["outputs"]
            if os.path.exists(os.path.join(scratch, gamever, module, spec.replace("{platform}", platform)))
        ]
        results.append({
            "platform": platform,
            "exit": completed.returncode,
            "produced": produced,
            "tail": completed.stdout.strip().splitlines()[-3:] if completed.stdout else [],
        })
    return {"task": task, "module": module, "runs": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-queue", help="JSON file or https URL written by the tracker")
    parser.add_argument("-gamever", help="build to re-hunt in (default: the queue's)")
    parser.add_argument("-symbols", nargs="*", default=[], help="symbols instead of a queue file")
    parser.add_argument("-run", action="store_true", help="actually analyse; without it this only plans")
    parser.add_argument("-scratch", help="where to write (default: a temporary directory)")
    parser.add_argument("-json", action="store_true", help="machine-readable result")
    args = parser.parse_args()

    symbols = list(args.symbols)
    gamever = args.gamever
    if args.queue:
        if args.queue.startswith(("http://", "https://")):
            if not args.queue.startswith("https://"):
                raise SystemExit("refusing to read a queue over plain http")
            with urllib.request.urlopen(args.queue, timeout=20) as response:
                payload = response.read(1_000_000)          # a queue is a few hundred bytes
            queue = json.loads(payload.decode("utf-8"))
        else:
            with open(args.queue, encoding="utf-8") as handle:
                queue = json.load(handle)
        if not isinstance(queue, dict):
            raise SystemExit("queue must be a JSON object")
        gamever = gamever or queue.get("gamever")
        symbols += [s for s in queue.get("symbols", []) if isinstance(s, str)]
    if not gamever:
        return parser.error("need -gamever or a queue file that names one")
    if not symbols:
        print("queue is empty; nothing to re-hunt")
        return 0

    config = load_config(gamever)
    plan: list[dict] = []
    unmapped: list[str] = []
    for symbol in dict.fromkeys(symbols):
        entries = tasks_for_symbol(config, symbol)
        if not entries:
            unmapped.append(symbol)
            continue
        for entry in entries:
            if entry not in plan:
                plan.append(entry)

    if not args.json:
        print(f"{len(symbols)} symbol(s) map to {len(plan)} task(s) in {gamever}")
        for entry in plan:
            print(f"  {entry['module']}/{entry['task']} "
                  f"[{entry['platform'] or 'both'}] -> {', '.join(entry['outputs'])}")
        for symbol in unmapped:
            print(f"  no task produces {symbol}; it needs a config entry before it can be re-hunted")

    if not args.run:
        if args.json:
            print(json.dumps({"gamever": gamever, "plan": plan, "unmapped": unmapped}, indent=1))
        else:
            print("\nplan only. add -run to analyse.")
        return 0

    old_gamever = previous_gamever(gamever)
    if not old_gamever:
        print(f"no earlier build to relocate from; cannot re-hunt {gamever}", file=sys.stderr)
        return 1
    scratch = args.scratch or tempfile.mkdtemp(prefix="rehunt-")
    os.makedirs(scratch, exist_ok=True)
    print(f"\nanalysing into {scratch} (bin_artifacts is untouched), baseline {old_gamever}")
    results = [run_task(entry, gamever, old_gamever, scratch) for entry in plan]
    failures = [r for r in results if any(run["exit"] != 0 or not run["produced"] for run in r["runs"])]

    if args.json:
        print(json.dumps({"gamever": gamever, "scratch": scratch, "results": results,
                          "unmapped": unmapped}, indent=1))
    else:
        for result in results:
            for run in result["runs"]:
                state = "ok" if run["exit"] == 0 and run["produced"] else "FAILED"
                print(f"  {state:>6}  {result['task']} [{run['platform']}] "
                      f"{', '.join(run['produced']) or 'no output'}")
                for line in run["tail"] if state == "FAILED" else []:
                    print(f"          {line}")
        print(f"\ncompare {scratch}/{gamever}/<module>/ against bin_artifacts/{gamever}/<module>/ "
              "before adopting anything")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
