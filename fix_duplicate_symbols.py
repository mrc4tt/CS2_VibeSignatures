#!/usr/bin/env python3
"""Auto-fix: remove duplicate symbol declarations from analysis configs.

When our ensure-scripts inject symbols that upstream also declares (via
platform-restricted tasks), the config ends up with duplicate `- name: X`
entries that update_gamedata rejects ("duplicate symbol in module stage N").

This tool scans each config, finds duplicate symbol entries, and removes the
BARE copy (no alias) keeping the ALIAS-BEARING one (upstream's richer entry).
If both are bare or both have aliases, keeps the first occurrence.

Idempotent: clean configs pass through unchanged.

Usage:
  uv run fix_duplicate_symbols.py                    # newest config
  uv run fix_duplicate_symbols.py -config configs/14180.yaml
  uv run fix_duplicate_symbols.py -all               # every config
"""

import argparse
import glob
import re

import yaml


def _gamever_sort_key(path):
    # gamever first as a number, then the optional letter suffix - sorting on
    # path length instead makes 14178b (19 chars) outrank 14181 (18 chars)
    m = re.fullmatch(r"configs/(\d+)([a-z]?)\.yaml", path)
    return (int(m.group(1)), m.group(2))


def fix(path):
    lines = open(path).readlines()

    # index all symbol entries (6-space indent "      - name: X")
    occ = {}
    for i, l in enumerate(lines):
        m = re.match(r"      - name: (\S+)\n", l)
        if m:
            has_alias = False
            for j in range(i + 1, min(i + 8, len(lines))):
                if "alias:" in lines[j]:
                    has_alias = True
                if re.match(r"      - name: ", lines[j]) or re.match(r"    \w", lines[j]):
                    break
            occ.setdefault(m.group(1), []).append((i, has_alias))

    dups = {n: lst for n, lst in occ.items() if len(lst) > 1}
    if not dups:
        print(f"  {path}: clean")
        return 0

    remove = set()
    for n, lst in dups.items():
        aliased = [i for i, a in lst if a]
        keep = aliased[0] if aliased else lst[0][0]
        for i, a in lst:
            if i != keep:
                remove.add(i)

    out, skip = [], False
    for i, l in enumerate(lines):
        if i in remove:
            skip = True
            continue
        if skip:
            if re.match(r"      - name: ", l) or re.match(r"    \w", l) or re.match(r"  - name: ", l):
                skip = False
            else:
                continue
        out.append(l)

    open(path, "w").writelines(out)
    yaml.safe_load(open(path))
    print(f"  {path}: {len(remove)} duplicate entries removed ({len(dups)} names), yaml OK")
    return len(remove)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-config", help="specific config (default: newest)")
    ap.add_argument("-all", action="store_true", help="fix ALL configs")
    args = ap.parse_args()

    if args.all:
        total = 0
        for p in sorted(glob.glob("configs/*.yaml")):
            total += fix(p)
        print(f"total: {total} removed")
    elif args.config:
        fix(args.config)
    else:
        numeric = [c for c in glob.glob("configs/*.yaml") if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
        if numeric:
            fix(max(numeric, key=_gamever_sort_key))


if __name__ == "__main__":
    main()
