#!/usr/bin/env python3
"""Accurate missing-analysis report per module and platform.

Reads each task's ACTUAL expected_output list from the gamever config (not
synthesized filenames), checks bin/ + bin_artifacts/ for each expected file,
and groups the gaps per module with the IDB to hunt in. Seed symbols (the
local gamedata consumers) are starred; upstream's long tail is counted.

Config-declared SYMBOLS count as expected artifacts too, not only find-tasks.
A symbol declared without a task is never hunted, so it used to be invisible
here while gamedata generation still asked for it and logged missing_yaml -
that gap hid 28 symbols on 14181. Those rows are marked "ingen find-task" and
are PRINTED ONLY: they stay out of missing_<plat>_<ver>.txt, because auto_hunt
reads that file and a commented-out find-task means the symbol was disabled on
purpose, not forgotten.

Usage:
  uv run missing_report.py -gamever 14178b              # begge platforme, SEED-fokus
  uv run missing_report.py -gamever 14178b -all         # alt i detaljer
  uv run missing_report.py -gamever 14178b -platform windows
"""
import argparse
import glob
import json
import os

import yaml

SEEDS = [
    "gamedata-generators/weaponpaints/gamedata/weaponpaints.json",
    "gamedata-generators/matchzy/gamedata/matchzy.json",
    "gamedata-generators/bot-controller/gamedata/bot-controller.json",
    "gamedata-generators/bot-hider/gamedata/bot-hider.json",
    "gamedata-generators/css-extras/gamedata/css-extras.json",
]
BINARIES = {"linux": "libserver.so / libengine2.so", "windows": "server.dll / engine2.dll"}


def is_needed(module, filename, notask, platform, config_path):
    """Required by a task and not waived, or read by an enabled plugin or another task."""
    import ida_analyze_bin as I

    path = os.path.join("bin_artifacts", "x", module, filename)
    if I.artifact_has_consumer(path, platform, config_path):
        return True
    if notask:
        return False
    return not I.artifact_only_disabled_consumers(path, platform, config_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-gamever", default="14178b")
    ap.add_argument("-platform", choices=("linux", "windows"))
    ap.add_argument("-all", action="store_true", help="detaljer for alle (default: kun ★SEED)")
    args = ap.parse_args()

    cfg_path = f"configs/{args.gamever}.yaml"
    if not os.path.exists(cfg_path):
        raise SystemExit(f"❌ config mangler: {cfg_path}")
    cfg = yaml.safe_load(open(cfg_path))

    seed_names = set()
    for seed in SEEDS:
        if os.path.exists(seed):
            seed_names |= {k.replace("::", "_") for k in json.load(open(seed))}

    # expected filer pr. modul pr. platform + task-kilde
    expected = {}  # platform -> module -> [(task, filename, seed?)]
    for module in cfg.get("modules", []):
        mod = module.get("name", "?")
        for task in module.get("skills", []):
            name = task.get("name", "")
            if not name.startswith("find-"):
                continue
            short = name[len("find-"):]
            outs = task.get("expected_output") or []
            task_platforms = [task["platform"]] if task.get("platform") in ("linux", "windows") else ["linux", "windows"]
            for plat in task_platforms:
                for out in outs:
                    if not isinstance(out, str):
                        continue
                    fname = out.replace("{platform}", plat)
                    expected.setdefault(plat, {}).setdefault(mod, []).append(
                        (short, fname, short in seed_names, False))

    # symbols without a find-task: declared, never hunted, still demanded by
    # the gamedata generators
    for module in cfg.get("modules", []):
        mod = module.get("name", "?")
        for sym in module.get("symbols", []):
            if not isinstance(sym, dict):
                continue
            name = sym.get("name")
            if not isinstance(name, str) or not name.strip() or sym.get("category") == "struct":
                continue
            sym_platforms = ([sym["platform"]] if sym.get("platform") in ("linux", "windows")
                             else ["linux", "windows"])
            for plat in sym_platforms:
                fname = f"{name}.{plat}.yaml"
                bucket = expected.setdefault(plat, {}).setdefault(mod, [])
                if any(existing == fname for _, existing, _, _ in bucket):
                    continue
                bucket.append((name, fname, name in seed_names, True))

    for platform in ([args.platform] if args.platform else ["linux", "windows"]):
        print(f"\n{'=' * 70}\n{platform.upper()}  —  jagt-IDB: {BINARIES[platform]}   (gamever {args.gamever})\n{'=' * 70}")
        have = set()
        for d in (f"bin/{args.gamever}", f"bin_artifacts/{args.gamever}"):
            for f in glob.glob(f"{d}/*/*.{platform}.yaml") + glob.glob(f"{d}/*.{platform}.yaml"):
                rel = os.path.relpath(f, d)
                have.add(f"{os.path.dirname(rel)}/{os.path.basename(rel)}")
        entries = expected.get(platform, {})
        grand = grand_seed = grand_notask = grand_unneeded = 0
        needed_rows = {}
        for mod in sorted(entries):
            missing = [r for r in entries[mod] if f"{mod}/{r[1]}" not in have]
            # Missing on disk is not the same as missing: an output only switched-off plugins
            # read is waived (pack does not insist on it), and one no task requires and
            # nothing reads is not wanted at all. Only the rest is worth anyone's time.
            unneeded = [r for r in missing if not is_needed(mod, r[1], r[3], platform, cfg_path)]
            rows = [r for r in missing if r not in unneeded]
            needed_rows[mod] = rows
            grand_unneeded += len(unneeded)
            if not rows:
                extra = f"  ({len(unneeded)} not needed: {', '.join(r[0] for r in unneeded)})" if unneeded else ""
                print(f"\n[{mod}]  komplett ✓{extra}")
                continue
            seed_rows = [r for r in rows if r[2]]
            notask_rows = [r for r in rows if r[3]]
            grand += len(rows); grand_seed += len(seed_rows); grand_notask += len(notask_rows)
            if args.all:
                print(f"\n[{mod}]  {len(rows)} manglende:")
                for t, fn, sd, notask in rows:
                    mark = "  ★SEED" if sd else ""
                    mark += "  [ingen find-task]" if notask else ""
                    note = "" if fn.startswith(t + ".") else f"   (fil: {fn})"
                    print(f"    {t}{mark}{note}")
            else:
                print(f"\n[{mod}]  {len(rows)} manglende  ({len(seed_rows)} ★SEED, "
                      f"{len(notask_rows)} uden find-task, {len(rows) - len(seed_rows)} upstream)")
                for t, fn, sd, notask in seed_rows:
                    note = "" if fn.startswith(t + ".") else f"   (fil: {fn})"
                    print(f"    {t}  ★SEED{'  [ingen find-task]' if notask else ''}{note}")
        print(f"\n--- {platform}: {grand} manglende i alt ({grand_seed} ★SEED, "
              f"{grand_notask} uden find-task)" + (f"; {grand_unneeded} not needed (no reader, or read only by "
                                                    f"switched-off plugins) left out" if grand_unneeded else ""))
        outfile = f"missing_{platform}_{args.gamever}.txt"
        if not grand:
            # nothing to hunt: no list, and no stale one from an earlier run either
            if os.path.exists(outfile):
                os.remove(outfile)
            print(f"no list: nothing is missing ({outfile} {'removed' if not os.path.exists(outfile) else 'kept'})")
            continue
        with open(outfile, "w") as f:
            for mod in sorted(entries):
                for t, fn, sd, notask in needed_rows.get(mod, []):
                    # Symbol-derived rows are REPORTED but never written here.
                    # auto_hunt consumes this file, and a symbol whose find-task
                    # is commented out is deliberately disabled ("We don't need
                    # it anymore") - feeding it to the hunter recreates
                    # artifacts the project dropped on purpose.
                    if notask:
                        continue
                    if f"{mod}/{fn}" not in have:
                        f.write(f"{mod}/{t} -> {fn}\n")
        print(f"liste gemt: {outfile}")


if __name__ == "__main__":
    main()
