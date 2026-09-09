#!/usr/bin/env python3
"""Create base find-tasks for reference targets that only have -decompiles tasks.

Upstream ships LLM_DECOMPILE reference tasks for some functions but never created
the base hunt-tasks producing their artifacts — so the artifacts (and therefore
the references) can never materialize. This tool derives symbol+module from the
missing reference paths (references/<module>/<symbol>.{platform}.yaml) and
injects a base find-task + func symbol entry into that module, making them
huntable. Run ensure_agent_fallback_skills afterwards to give them skills.

Usage:
  uv run ensure_reference_base_tasks.py -config configs/14178b.yaml
"""

import argparse
import glob
import os
import re


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-config", default="configs/14178b.yaml")
    args = ap.parse_args()
    cfg_path = args.config
    text = open(cfg_path).read()

    # 1. manglende referencer -> (symbol, modul)
    missing = set()
    for script in glob.glob("ida_preprocessor_scripts/find-*-decompiles.py"):
        src = open(script).read()
        for m in re.finditer(r"references/(\w+)/(\S+?)\.\{platform\}\.yaml", src):
            mod, sym = m.groups()
            for plat in ("linux", "windows"):
                if not os.path.exists(f"ida_preprocessor_scripts/references/{mod}/{sym}.{plat}.yaml"):
                    missing.add((sym, mod))

    # 2. filter: kun dem uden eksisterende base-task
    # spring over hvis baade task OG symbol allerede deklareret (upstream erklærer ofte
    # symbolet via en platform-begraenset task — da skal vi kun evt. tilføje tasken,
    # aldrig et nyt symbol-entry)
    todo = [(s, m) for s, m in sorted(missing)
            if f"- name: find-{s}\n" not in text or f"- name: {s}\n" not in text]
    if not todo:
        print("  ingen taskloese reference-maal — alt dækket")
        return
    print(f"  {len(todo)} base-task(s) skal oprettes: {[f'{s} ({m})' for s, m in todo]}")

    # 3. injicér pr. modul (foerste blok af modulet)
    mm = list(re.finditer(r"^  - name: (\w+)", text, re.M))
    blocks = []
    for i, m in enumerate(mm):
        end = mm[i + 1].start() if i + 1 < len(mm) else len(text)
        blocks.append((m.group(1), m.start(), end))

    for sym, mod in todo:
        cand = [b for b in blocks if b[0] == mod]
        if not cand:
            print(f"  advarsel: modul '{mod}' findes ikke — springer {sym} over")
            continue
        _, start, end = cand[0]
        block = text[start:end]
        task = f"      - name: find-{sym}\n        expected_output:\n          - {sym}.{{platform}}.yaml\n"
        symbol = f"      - name: {sym}\n        category: func\n"
        sk = re.search(r"^    skills:\n", block, re.M)
        sy = re.search(r"^    symbols:\n", block, re.M)
        if not sk or not sy:
            print(f"  advarsel: {mod} mangler skills:/symbols: — springer {sym} over")
            continue
        block = block[:sk.end()] + task + block[sk.end():sy.end()] + symbol + block[sy.end():]
        text = text[:start] + block + text[end:]
        # blok-offsets er skudt — genindlaes
        mm = list(re.finditer(r"^  - name: (\w+)", text, re.M))
        blocks = []
        for i, m in enumerate(mm):
            end2 = mm[i + 1].start() if i + 1 < len(mm) else len(text)
            blocks.append((m.group(1), m.start(), end2))
        print(f"  + find-{sym} -> {mod}")

    open(cfg_path, "w").write(text)
    import yaml
    yaml.safe_load(text)
    print(f"  opdateret: {cfg_path} (yaml OK)")


if __name__ == "__main__":
    main()
