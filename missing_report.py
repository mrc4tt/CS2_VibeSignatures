#!/usr/bin/env python3
"""Clear-text missing-analysis report per module and platform.

For a gamever: lists every config find-task whose expected YAML is not yet produced,
grouped by module (binary), with seed-symbol stars and the IDB to hunt in.
Built for the manual IDA-GUI workflow: hunt locally, emit YAMLs with the
ida_sig_maker tools (Ctrl-Alt-S / Ctrl-Alt-M / Ctrl-Alt-V), then re-run the
platform script - it skips existing YAMLs and verifies the rest.

Usage:
  uv run missing_report.py -gamever 14178b              # begge platforme
  uv run missing_report.py -gamever 14178b -platform windows
"""

import argparse
import json
import os
import re

SEEDS = [
    "gamedata-generators/weaponpaints/gamedata/weaponpaints.json",
    "gamedata-generators/matchzy/gamedata/matchzy.json",
    "gamedata-generators/bot-controller/gamedata/bot-controller.json",
    "gamedata-generators/bot-hider/gamedata/bot-hider.json",
    "gamedata-generators/css-extras/gamedata/css-extras.json",
]
LIB_MODULE = {"server": "server", "engine2": "engine", "engine": "engine", "client": "client"}
ENGINE_CLASSES = ("CNetworkGameServerBase", "CNetworkGameServer", "CServerSideClient",
                  "CServerSideClientBase", "CGameEntitySystem")
BINARIES = {"linux": "libserver.so / libengine2.so", "windows": "server.dll / engine2.dll"}


def module_blocks(text):
    mm = list(re.finditer(r"^  - name: (\w+)", text, re.M))
    out = {}
    for i, m in enumerate(mm):
        end = mm[i + 1].start() if i + 1 < len(mm) else len(text)
        out[m.group(1)] = text[m.start():end]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-gamever", default="14178b")
    ap.add_argument("-platform", choices=("linux", "windows"))
    args = ap.parse_args()
    gamever = args.gamever
    platforms = [args.platform] if args.platform else ["linux", "windows"]

    text = open("configs/14178b.yaml").read()
    blocks = module_blocks(text)

    # tasks pr. modul + library/categorisation
    per_module = {}
    for mod, block in blocks.items():
        tasks = [s[len("find-"):] for s in re.findall(r"^      - name: (find-\S+)$", block, re.M)]
        if tasks:
            per_module[mod] = sorted(tasks)

    seed_names = set()
    for seed in SEEDS:
        if os.path.exists(seed):
            seed_names |= {k.replace("::", "_") for k in json.load(open(seed))}

    for platform in platforms:
        print(f"\n{'=' * 70}\n{platform.upper()}  —  jagt-IDB: {BINARIES[platform]}   (gamever {gamever})\n{'=' * 70}")
        grand = 0
        entries = []   # (modul, symbol) - samme filtrerede liste som printet
        for mod in sorted(per_module):
            have = set()
            for d in (f"bin/{gamever}/{mod}", f"bin_artifacts/{gamever}/{mod}"):
                if os.path.isdir(d):
                    for f in os.listdir(d):
                        if f.endswith(f".{platform}.yaml"):
                            have.add(f[:-len(f".{platform}.yaml")])
            missing = sorted(t for t in per_module[mod] if t not in have
                             and not t.endswith("-decompiles")
                             and not (t.endswith("-windows") and platform == "linux")
                             and not (t.endswith("-linux") and platform == "windows"))

            # inlined/noinline-par: taell kun base hvis begge mangler
            bases = {}
            for t in list(missing):
                base = re.sub(r"-(inlined|noinline)$", "", t)
                bases.setdefault(base, []).append(t)
            for base, variants in bases.items():
                if len(variants) == 2 and base in missing:
                    missing.remove(variants[0])
                    missing.remove(variants[1])
                    missing.append(base)

            if not missing:
                print(f"\n[{mod}]  komplett ✓")
                continue
            print(f"\n[{mod}]  {len(missing)} manglende  →  emit: .{platform}.yaml")
            for t in missing:
                star = "  ★SEED" if t in seed_names else ""
                print(f"    {t}{star}")
                entries.append((mod, t))
            grand += len(missing)
        print(f"\n--- {platform} ialt: {grand} manglende")
        outfile = f"missing_{platform}_{gamever}.txt"
        open(outfile, "w").write("\n".join(f"{m}/{t}" for m, t in sorted(entries)) + "\n")
        print(f"liste gemt: {outfile}")


if __name__ == "__main__":
    main()
