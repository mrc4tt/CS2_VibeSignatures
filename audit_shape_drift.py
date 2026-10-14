#!/usr/bin/env python3
"""
Did a shipped function change what it DOES between two builds?

The address checks prove a key names the right function, and audit_arg_fingerprint sees a
changed parameter list. Neither sees "same place, same arguments, different meaning": a
function Valve rewrote behind an unchanged entry. This compares each shipped function's
shape with the previous build's:

  callees   the functions it calls directly, by the name this repo gives them
  strings   the string literals it loads
  consts    the struct displacements and immediates it uses (a layout fingerprint)
  size      its length

Addresses move every build, so only names and values are compared. A function is reported
when its shape moved far - few of its named callees, strings or constants survive, or its
size changed by more than half - which is a reason to look at the plugins that use it, not
proof of a defect. A relocation that merely shifted code stays quiet.

  uv run audit_shape_drift.py -gamever 14190            # against the previous build
  uv run audit_shape_drift.py -gamever 14190 -prev 14181 -v

Exit 0 no shipped function changed shape, 1 at least one did.
"""

import argparse
import json
import os
import sys

import audit_arg_fingerprint as A
import validate_artifacts as V
import verify_plugin_gamedata as P

try:
    import capstone
    from capstone import x86
except ImportError:  # pragma: no cover
    capstone = None

MAX_BODY = 0x4000
# A component counts only with enough of it to compare, and is "moved" below this overlap.
MIN_ITEMS = 3
MIN_OVERLAP = 0.5
SIZE_RATIO = (0.5, 2.0)


def _names_by_va(index, module, platform):
    out = {}
    for name, per_platform in index.items():
        record = per_platform.get(platform)
        if isinstance(record, dict) and (record.get("_module") or "server") == module and record.get("func_va"):
            out[V._hexint(record["func_va"])] = record.get("func_name") or name
    return out


def _string_at(blob, info, va):
    off = V.va_to_off(info, va)
    if off is None or V.is_exec(info, off):
        return None
    end = blob.find(b"\x00", off, off + 256)
    if end <= off:
        return None
    raw = blob[off:end]
    if len(raw) < 4 or any(b < 0x20 or b > 0x7E for b in raw):
        return None
    return raw.decode("ascii")


def body_end(blob, info, va, size):
    """End of the function: its recorded size, else the first padding run after a ret/jmp."""
    if size:
        return va + size
    off = V.va_to_off(info, va)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    last = va
    for ins in md.disasm(blob[off:off + MAX_BODY], va):
        last = ins.address + ins.size
        if ins.mnemonic in ("ret", "jmp", "int3") or ins.mnemonic.startswith("ret"):
            nxt = V.va_to_off(info, last)
            if nxt is not None and blob[nxt:nxt + 2] in (b"\xcc\xcc", b"\x90\x90"):
                break
    return last


def shape(blob, info, va, size, names):
    """{'callees', 'strings', 'consts', 'size'} of the function at va, or None."""
    if capstone is None or va is None:
        return None
    off = V.va_to_off(info, va)
    if off is None:
        return None
    end = body_end(blob, info, va, size)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    callees, strings, consts = set(), set(), []
    for ins in md.disasm(blob[off:off + min(end - va, MAX_BODY)], va):
        for op in ins.operands:
            if op.type == x86.X86_OP_IMM and ins.mnemonic in ("call", "jmp"):
                if op.imm in names and not (va <= op.imm < end):
                    callees.add(names[op.imm])
            elif op.type == x86.X86_OP_MEM:
                if op.mem.base == x86.X86_REG_RIP:
                    text = _string_at(blob, info, ins.address + ins.size + op.mem.disp)
                    if text:
                        strings.add(text)
                elif op.mem.base not in (x86.X86_REG_RSP, x86.X86_REG_RBP) and 0x10 <= op.mem.disp < 0x10000:
                    consts.append(op.mem.disp)
            elif op.type == x86.X86_OP_IMM and ins.mnemonic not in ("call", "jmp") and 0x10 <= op.imm < 0x10000 \
                    and not ins.mnemonic.startswith("j"):
                consts.append(op.imm)
    return {"callees": callees, "strings": strings, "consts": set(consts), "size": end - va}


def _overlap(a, b, near=None):
    """Share of the smaller set that the other keeps; None when there is too little to judge.
    `near(x, y)` widens "keeps" from equality, for constants that only moved a little."""
    if min(len(a), len(b)) < MIN_ITEMS and max(len(a), len(b)) < MIN_ITEMS:
        return None
    if not a or not b:
        return 0.0
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    if near is None:
        kept = len(small & large)
    else:
        kept = sum(1 for x in small if x in large or any(near(x, y) for y in large))
    return kept / len(small)


def _layout_shift(x, y):
    """A struct offset in a big class that moved a little: Valve inserted a field before it.
    That is a layout change the schema already tracks, not a change of what the code does
    (CCSPlayerController_Respawn 2016 -> 2024, PostThink 1336 -> 1352 over 14181 -> 14190)."""
    return x >= 0x100 and y >= 0x100 and abs(x - y) <= max(0x40, x // 8)


def compare_shapes(old, new):
    """[(component, detail)] for every component that moved far."""
    moved = []
    for part in ("callees", "strings", "consts"):
        score = _overlap(old[part], new[part], _layout_shift if part == "consts" else None)
        if score is not None and score < MIN_OVERLAP:
            lost = sorted(old[part] - new[part])[:4]
            gained = sorted(new[part] - old[part])[:4]
            moved.append((part, f"{score:.0%} kept; lost {lost}, new {gained}"))
    # Size only supports another component: func_size is internal metadata that is often
    # unknown or mis-measured (CLAUDE.md rule 14), so on its own it says little.
    if moved and old["size"] and new["size"]:
        ratio = new["size"] / old["size"]
        if not SIZE_RATIO[0] <= ratio <= SIZE_RATIO[1]:
            moved.append(("size", f"{hex(old['size'])} -> {hex(new['size'])}"))
    return moved


def compare(gamever, prev):
    new_index = P.load_snapshot_index(os.path.join("gamesymbols", f"{gamever}.yaml"))
    old_index = P.load_snapshot_index(os.path.join("gamesymbols", f"{prev}.yaml"))
    new_bins, old_bins = P.Binaries("bin", gamever), P.Binaries("bin", prev)
    names_cache, rows, checked = {}, [], 0
    for symbol, keys in sorted(A.shipped_symbols().items()):
        module, name = symbol.split("/", 1)
        for platform in ("linux", "windows"):
            new = (new_index.get(P.fold(name)) or {}).get(platform)
            old = (old_index.get(P.fold(name)) or {}).get(platform)
            if not new or not old or not new.get("func_va") or not old.get("func_va"):
                continue
            nb, ni, _ = new_bins.get(module, platform)
            ob, oi, _ = old_bins.get(module, platform)
            if nb is None or ob is None:
                continue
            for key, index in (((gamever, module, platform), new_index), ((prev, module, platform), old_index)):
                if key not in names_cache:
                    names_cache[key] = _names_by_va(index, module, platform)
            a = shape(ob, oi, V._hexint(old["func_va"]), V._hexint(old.get("func_size")) or 0,
                      names_cache[(prev, module, platform)])
            b = shape(nb, ni, V._hexint(new["func_va"]), V._hexint(new.get("func_size")) or 0,
                      names_cache[(gamever, module, platform)])
            if not a or not b:
                continue
            checked += 1
            moved = compare_shapes(a, b)
            if moved:
                rows.append({"symbol": symbol, "platform": platform, "keys": keys, "moved": moved})
    return checked, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-prev", default=None, help="default: the newest older build under bin/")
    parser.add_argument("-json", action="store_true")
    parser.add_argument("-v", action="store_true", help="print what moved for each reported function")
    args = parser.parse_args()
    if capstone is None:
        print("audit_shape_drift: capstone is required", file=sys.stderr)
        return 2
    prev = args.prev or A._previous(args.gamever)
    if not prev:
        print(f"audit_shape_drift: no previous build under bin/ for {args.gamever}")
        return 0
    checked, rows = compare(args.gamever, prev)
    if args.json:
        print(json.dumps({"gamever": args.gamever, "prev": prev, "checked": checked,
                          "changed": [dict(r, moved=[list(m) for m in r["moved"]]) for r in rows]}, indent=1))
    else:
        for row in rows:
            print(f"SHAPE CHANGED {row['symbol']}.{row['platform']} ({', '.join(row['keys'])}): "
                  f"{', '.join(part for part, _ in row['moved'])}")
            if args.v:
                for part, detail in row["moved"]:
                    print(f"    {part}: {detail}")
        print(f"audit_shape_drift {args.gamever} vs {prev}: {checked} shipped function(s) compared, "
              f"{len(rows)} changed shape")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
