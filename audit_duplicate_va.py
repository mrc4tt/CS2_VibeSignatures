#!/usr/bin/env python3
"""Audit artifacts for duplicate func_va across DIFFERENT symbol names.

One bad agent/manual run can emit the same function under many names (the
0x20c2700 contamination class). Legit alias pairs (DropWeapon/vtidx_DropWeapon,
base/derived names sharing one function) share a VA by design — they carry the
same func_sig too. A shared VA with DIFFERENT func_sig (or >3 names) is suspect.

The SNAPSHOT is audited too, not just the artifacts. Repairing an artifact does
not update the packed snapshot, so a contaminated batch can sit in the published
snapshot long after bin_artifacts/ is clean - on 14178b eleven unrelated windows
symbols shared func_va 0x1815575bc there while every artifact on disk was already
correct, and WeaponPaints shipped one identical signature for five of them.

Usage: uv run audit_duplicate_va.py -gamever 14178b [-platform linux]
       uv run audit_duplicate_va.py -gamever 14178b -snapshot gamesymbols/14178b.yaml
"""
import argparse, glob, os
from collections import defaultdict

import yaml

# Pairs verified by hand to be one function under two names, where the sigs
# legitimately differ in KIND (one func_sig, one vfunc_sig) so the sig-equality
# heuristic below cannot recognise them on its own.
DECLARED_ALIAS_PAIRS = {
    # 14178b: GiveNamedItem2 == CCSPlayer_ItemServices vtable slot 25 (commit
    # 1539fc1fd) - same func_va, one artifact carries func_sig, the other vfunc_sig.
    frozenset(("GiveNamedItem2", "CCSPlayer_ItemServices_GiveNamedItemBool")),
}

ap = argparse.ArgumentParser()
ap.add_argument("-gamever", default="14178b")
ap.add_argument("-platform", default="linux", choices=("linux", "windows"))
ap.add_argument("-module", default="server")
ap.add_argument("-snapshot", help="also audit this packed snapshot "
                                  "(default: gamesymbols/<gamever>.yaml when present)")
ap.add_argument("-artifacts-only", action="store_true",
                help="skip the snapshot and audit only bin/ and bin_artifacts/")
a = ap.parse_args()


def sig_compatible(a, b):
    # sigs are anchored at the same func_va, so a shorter one is just a prefix of
    # the longer - compare over the overlap only
    ta, tb = a.split(), b.split()
    return all(x == y or "??" in (x, y) for x, y in zip(ta, tb))


def sigs_compatible(sigs):
    return all(sig_compatible(sigs[0], other) for other in sigs[1:])


def record(va_map, name, doc):
    va = doc.get("func_va")
    if not va:
        return
    sig = doc.get("func_sig") or ""
    va_map[str(va)].append((name, " ".join(str(sig).split()),
                            str(doc.get("func_size") or "")))


def _snapshot_entries(path):
    """{'<module>/<symbol>.<platform>.yaml': payload} from a packed snapshot."""
    with open(path) as fh:
        doc = yaml.safe_load(fh) or {}

    def find(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.endswith(".yaml") and isinstance(v, dict):
                    return node
                found = find(v)
                if found:
                    return found
        return None

    return find(doc) or {}


va_map = defaultdict(list)
for d in (f"bin/{a.gamever}", f"bin_artifacts/{a.gamever}"):
    for f in glob.glob(f"{d}/{a.module}/*.{a.platform}.yaml"):
        # parsed, not regex-scanned: "func_sig: (.+)" also matches the vfunc_sig
        # line, which made every func/vfunc alias pair look like two conflicting
        # sigs, and it truncated line-wrapped sig values to their first line
        with open(f) as fh:
            doc = yaml.safe_load(fh) or {}
        record(va_map, os.path.basename(f).rsplit(".", 2)[0], doc or {})

snapshot = a.snapshot or f"gamesymbols/{a.gamever}.yaml"
if not getattr(a, "artifacts_only", False) and os.path.exists(snapshot):
    n = 0
    for key, payload in _snapshot_entries(snapshot).items():
        parts = key.split("/")
        if len(parts) != 2 or parts[0] != a.module:
            continue
        base = parts[1]
        if base.count(".") < 2:
            continue
        name, platform, _ = base.rsplit(".", 2)
        if platform != a.platform or not isinstance(payload, dict):
            continue
        record(va_map, name, payload)
        n += 1
    print(f"(inkl. {n} poster fra {snapshot})\n")

suspects = 0
for va, entries in sorted(va_map.items()):
    names = list(dict.fromkeys(n for n, _, _ in entries))  # unique pr. navn
    if len(names) < 2:
        continue
    sigs = [s for _, s, _ in entries if s]
    # func_size '0x0' is the "size unknown" convention, not a real size - comparing
    # a known size against an unknown one is not a disagreement
    sizes = {z for _, _, z in entries if z and int(str(z), 16) != 0}
    # alias pairs are generated independently, so the same function often comes
    # out with different wildcarding ("48 83 EC ??" vs "48 83 EC 50"). Compare
    # wildcard-tolerantly; a differing concrete byte is a real disagreement.
    same_function = (len(names) <= 2
                     and sigs_compatible(sigs)
                     and len(sizes) <= 1)
    if frozenset(names) in DECLARED_ALIAS_PAIRS:
        verdict = "OK (erklaeret alias-par)"
    elif same_function and len(names) <= 2:
        verdict = "OK (alias-par)"
    else:
        verdict = "SUSPEKT"
        suspects += 1
    print(f"{va} [{verdict}]: {names}")

print(f"\nsuspekte klynger: {suspects}")
