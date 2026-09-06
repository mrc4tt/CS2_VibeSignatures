#!/usr/bin/env python3
"""Ensure every weaponpaints.json entry is analyzable in an analysis config.

The WeaponPaints gamedata generator (gamedata-generators/weaponpaints/) can only
refresh entries that the per-gamever analysis actually produces symbol YAMLs for.
Configs (configs/<GAMEVER>.yaml) are hand-authored and do not inherit from
previous versions, so entries silently vanish in newer configs.

This script reads every entry from the weaponpaints.json seed and injects into the
server module of the given config:

  - a find-task (skills:)        name: find-<symbol>, expected_output <symbol>.{platform}.yaml
  - a symbol entry (symbols:)    category derived from the gamedata entry:
                                     signatures       -> func
                                     offsets + m_*    -> structmember (struct: <class>,
                                                         plus a struct entry for <class>
                                                         when absent)
                                     offsets + method -> vfunc
  - an alias for ::-style keys   so key names like CAttributeList::SetOrAddAttributeValueByName
                                 resolve to their underscore symbol names

Idempotent per symbol: symbols already present in the server module are skipped, so
newly added weaponpaints.json entries are picked up on the next run without
duplicating existing ones.

Usage:
  uv run ensure_weaponpaints_symbols.py -config configs/14178b.yaml
  uv run ensure_weaponpaints_symbols.py            # newest configs/<GAMEVER>.yaml
"""

import argparse
import glob
import json
import os
import re
import sys

SEED_GAMEDATA = "gamedata-generators/weaponpaints/gamedata/weaponpaints.json"


def newest_config():
    candidates = glob.glob("configs/*.yaml")
    numeric = [c for c in candidates if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
    if not numeric:
        return None
    return max(numeric, key=lambda p: (len(p), p))


def load_seed_specs():
    """Derive (symbol_name, category, struct, alias) for every weaponpaints.json entry."""
    if not os.path.exists(SEED_GAMEDATA):
        sys.exit(f"error: seed gamedata not found: {SEED_GAMEDATA}")
    with open(SEED_GAMEDATA, "r", encoding="utf-8") as f:
        gamedata = json.load(f)

    specs = []
    for key, entry in gamedata.items():
        symbol_name = key.replace("::", "_")
        alias = key if key != symbol_name else None
        if "signatures" in entry:
            specs.append((symbol_name, "func", None, alias))
            continue
        cls, _, method = key.partition("::")
        if method.startswith("m_"):
            specs.append((symbol_name, "structmember", cls, alias))
        else:
            specs.append((symbol_name, "vfunc", None, alias))
    return specs


def find_task_block(symbol_name):
    return (
        f"      - name: find-{symbol_name}\n"
        f"        expected_output:\n"
        f"          - {symbol_name}.{{platform}}.yaml\n"
    )


def symbol_entry_block(symbol_name, category, struct, alias):
    lines = [f"      - name: {symbol_name}", f"        category: {category}"]
    if category == "structmember":
        lines.append(f"        struct: {struct}")
        lines.append(f"        member: {symbol_name.rsplit('_', 1)[-1]}")
    if alias:
        lines.append("        alias:")
        lines.append(f"          - {alias}")
    return "".join(line + "\n" for line in lines)


def struct_entry_block(struct):
    return f"      - name: {struct}\n        category: struct\n"


def inject(text, config_path, specs):
    # Server module block: from "  - name: server" to the next module entry (same indent).
    module_match = re.search(r"^  - name: server$", text, re.M)
    if not module_match:
        sys.exit(f"error: {config_path}: no 'server' module found")
    next_module = re.search(r"^  - name: (?!server$)", text[module_match.start() + 1:], re.M)
    block_end = module_match.start() + 1 + next_module.start() if next_module else len(text)
    block = text[module_match.start():block_end]

    skills_match = re.search(r"^    skills:\n", block, re.M)
    symbols_match = re.search(r"^    symbols:\n", block, re.M)
    if not skills_match or not symbols_match:
        sys.exit(f"error: {config_path}: server module lacks skills:/symbols: sections")

    new_tasks = []
    new_symbols = []
    needed_structs = set()
    for symbol_name, category, struct, alias in specs:
        if f"- name: {symbol_name}\n" in block:
            continue
        new_tasks.append(find_task_block(symbol_name))
        new_symbols.append(symbol_entry_block(symbol_name, category, struct, alias))
        if struct and f"- name: {struct}\n" not in block:
            needed_structs.add(struct)

    if not new_tasks:
        print(f"  already present: {config_path}")
        return text

    # Struct entries first so members sit next to their class definition.
    struct_blocks = [struct_entry_block(s) for s in sorted(needed_structs)]
    patched = (
        block[: skills_match.end()]
        + "".join(new_tasks)
        + block[skills_match.end(): symbols_match.end()]
        + "".join(struct_blocks)
        + "".join(new_symbols)
        + block[symbols_match.end():]
    )
    return text[: module_match.start()] + patched + text[block_end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-config", help="analysis config path (default: newest configs/<GAMEVER>.yaml)")
    args = parser.parse_args()

    config_path = args.config or newest_config()
    if not config_path or not os.path.exists(config_path):
        print(f"  warning: no analysis config to patch ({config_path}); skipping")
        return

    specs = load_seed_specs()

    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()

    patched = inject(text, config_path, specs)
    if patched == text:
        return

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"  injected WeaponPaints symbols ({len(specs)} entries checked): {config_path}")


if __name__ == "__main__":
    main()
