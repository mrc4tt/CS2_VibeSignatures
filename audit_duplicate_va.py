#!/usr/bin/env python3
"""Audit artifacts for duplicate func_va across DIFFERENT symbol names.

One bad agent/manual run can emit the same function under many names (the
0x20c2700 contamination class). Legit alias pairs (DropWeapon/vtidx_DropWeapon,
base/derived names sharing one function) share a VA by design — they carry the
same func_sig too. A shared VA with DIFFERENT func_sig (or >3 names) is suspect.

Usage: uv run audit_duplicate_va.py -gamever 14178b [-platform linux]
"""
import argparse, glob, os, re
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("-gamever", default="14178b")
ap.add_argument("-platform", default="linux", choices=("linux", "windows"))
ap.add_argument("-module", default="server")
a = ap.parse_args()

va_map = defaultdict(list)
for d in (f"bin/{a.gamever}", f"bin_artifacts/{a.gamever}"):
    for f in glob.glob(f"{d}/{a.module}/*.{a.platform}.yaml"):
        text = open(f).read()
        va = re.search(r"func_va: '?(0x[0-9a-f]+)'?", text)
        sig = re.search(r"func_sig: (.+)", text)
        size = re.search(r"func_size: '?(0x[0-9a-f]+)'?", text)
        if va:
            va_map[va.group(1)].append((os.path.basename(f).rsplit(".", 2)[0],
                                        " ".join(sig.group(1).split()) if sig else "",
                                        size.group(1) if size else ""))

suspects = 0
for va, entries in sorted(va_map.items()):
    names = list(dict.fromkeys(n for n, _, _ in entries))  # unique pr. navn
    if len(names) < 2:
        continue
    sigs = {s for _, s, _ in entries if s}
    sizes = {z for _, _, z in entries if z}
    same_function = len(sigs) <= 1 or (len(sizes) == 1 and len(names) <= 2)
    verdict = "OK (alias-par)" if same_function and len(names) <= 2 else "SUSPEKT"
    if verdict != "OK (alias-par)":
        suspects += 1
    print(f"{va} [{verdict}]: {names}")

print(f"\nsuspekte klynger: {suspects}")
