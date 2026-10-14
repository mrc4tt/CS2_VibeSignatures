#!/usr/bin/env python3
"""
Did a shipped function's arguments change between two builds?

Every other check proves an address names the right function. None can see that Valve
added, dropped or retyped a parameter: the address is still right, the plugin still calls
it the old way, and the server crashes. This fingerprints each shipped function from its
entry up to its first call, return or jump - which argument registers it reads before
writing them, and which stack arguments - and compares the fingerprint with the previous
build's.

  linux (SysV)    rdi rsi rdx rcx r8 r9, xmm0-7, stack from [rsp+8]
  windows (x64)   rcx rdx r8 r9, xmm0-3, stack from [rsp+0x28]

It is a lower bound on the arguments read (an unused one is invisible, and the window
ends at the first call), so it reports only CHANGES, and only for functions whose entry
code is otherwise comparable. A change is a reason to look at the plugin that calls it,
not proof of a crash; the fix is in plugin code, so autopilot reports it rather than
holding gamedata that would be just as wrong without it.

  uv run audit_arg_fingerprint.py -gamever 14190            # against the previous build
  uv run audit_arg_fingerprint.py -gamever 14190 -prev 14189 -json

Exit 0 no change, 1 at least one shipped function changed its arguments.
"""

import argparse
import json
import os
import sys

import validate_artifacts as V
import verify_plugin_gamedata as P

try:
    import capstone
    from capstone import x86
except ImportError:  # pragma: no cover - the validators need it too
    capstone = None

INT_ARGS = {"linux": ("rdi", "rsi", "rdx", "rcx", "r8", "r9"), "windows": ("rcx", "rdx", "r8", "r9")}
FLOAT_ARGS = {"linux": tuple(f"xmm{i}" for i in range(8)), "windows": tuple(f"xmm{i}" for i in range(4))}
STACK_BASE = {"linux": 0x8, "windows": 0x28}
WINDOW = 96          # instructions at most


def _parent(name):
    """The 64-bit register a sub-register belongs to (edi/di/dil -> rdi, r8d -> r8)."""
    table = {"di": "rdi", "si": "rsi", "dx": "rdx", "cx": "rcx", "ax": "rax", "bx": "rbx",
             "bp": "rbp", "sp": "rsp"}
    if name.startswith("xmm") or name.startswith("ymm") or name.startswith("zmm"):
        return "xmm" + name[3:]
    if name.startswith("r") and name[1:2].isdigit():
        return "r" + "".join(ch for ch in name[1:] if ch.isdigit())
    core = name.lstrip("er")
    core = core[:-1] if core.endswith("l") and core[:-1] in table else core
    core = core[:-1] if core.endswith("h") and core[:-1] in table else core
    return table.get(core, name)


def fingerprint(blob, info, va, platform):
    """{'int': [...], 'float': [...], 'stack': n, 'end': mnemonic} or None."""
    if capstone is None or va is None:
        return None
    off = V.va_to_off(info, va)
    if off is None:
        return None
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    written, read_int, read_float, stack = set(), set(), set(), set()
    delta, end, count = 0, None, 0
    int_args, float_args = INT_ARGS[platform], FLOAT_ARGS[platform]
    # A thunk (an entry that only jumps, after at most a few register moves) is followed
    # into its body: CCSPlayer_ItemServices_GiveNamedItem.linux is "jmp <body>", which
    # would otherwise fingerprint as reading nothing.
    hops = 0
    while hops < 2:
        first = next(md.disasm(blob[off:off + 16], va), None)
        if first is None or first.mnemonic != "jmp" or first.operands[0].type != x86.X86_OP_IMM:
            break
        target = first.operands[0].imm
        target_off = V.va_to_off(info, target)
        if target_off is None:
            break
        va, off, hops = target, target_off, hops + 1
    for ins in md.disasm(blob[off:off + 0x400], va):
        count += 1
        try:
            regs_read, regs_write = ins.regs_access()
        except capstone.CsError:
            break
        reads = {_parent(ins.reg_name(r)) for r in regs_read}
        # "xor eax, eax" / "xorps xmm0, xmm0" read nothing - they zero the register
        if ins.mnemonic in ("xor", "xorps", "pxor", "sub") and len(ins.operands) == 2 \
                and ins.operands[0].type == x86.X86_OP_REG and ins.operands[1].type == x86.X86_OP_REG \
                and ins.operands[0].reg == ins.operands[1].reg:
            reads = set()
        for reg in reads - written:
            if reg in int_args:
                read_int.add(reg)
            elif reg in float_args:
                read_float.add(reg)
        for op in ins.operands:
            if op.type == x86.X86_OP_MEM and op.mem.base == x86.X86_REG_RSP and op.access & capstone.CS_AC_READ:
                slot = op.mem.disp - delta - STACK_BASE[platform]
                if slot >= 0 and slot % 8 == 0 and slot < 0x100:
                    stack.add(slot // 8)
        written |= {_parent(ins.reg_name(r)) for r in regs_write}
        if ins.mnemonic == "push":
            delta += 8
        elif ins.mnemonic == "pop":
            delta -= 8
        elif ins.mnemonic in ("sub", "add") and ins.operands[0].type == x86.X86_OP_REG \
                and ins.operands[0].reg == x86.X86_REG_RSP and ins.operands[1].type == x86.X86_OP_IMM:
            delta += ins.operands[1].imm if ins.mnemonic == "sub" else -ins.operands[1].imm
        if ins.mnemonic in ("call", "ret", "jmp") or ins.mnemonic.startswith("ret") or count >= WINDOW:
            end = ins.mnemonic
            break
    # Pass-through: at the call or tail jump that ends the window, an argument register
    # BELOW the lowest one this code set up for its callee was handed on untouched - a
    # parameter. GiveNamedItem.linux zeroes rdx/rcx/r8/r9 and jumps, passing rdi/rsi on.
    if end in ("call", "jmp"):
        set_up = [i for i, reg in enumerate(int_args) if reg in written]
        if set_up:
            read_int |= {reg for reg in int_args[:min(set_up)] if reg not in written}
    return {"int": [r for r in int_args if r in read_int],
            "float": [r for r in float_args if r in read_float],
            "stack": len(stack), "end": end}


def arity(fp):
    """The highest argument position read: a lower bound on the parameter count."""
    return max([0] + [i + 1 for i, reg in enumerate(INT_ARGS["linux"] + INT_ARGS["windows"])
                      if reg in fp["int"]])


def shipped_symbols(history_path=os.path.join("gamedata", "history.json")):
    """{'module/Symbol': [plugin keys]} for every key an enabled plugin ships."""
    with open(history_path, encoding="utf-8") as handle:
        history = json.load(handle)
    out = {}
    for composite, symbol in history.get("keyToSymbol", {}).items():
        relative, key = composite.split("|", 1)
        if key.endswith(".vtable"):
            continue
        out.setdefault(symbol, []).append(f"{relative.split('/')[0]}:{key}")
    return out


def _previous(gamever):
    builds = sorted((d for d in os.listdir("bin") if d[:1].isdigit() and d != gamever),
                    key=lambda t: (int("".join(c for c in t if c.isdigit())), t))
    older = [b for b in builds if (int("".join(c for c in b if c.isdigit())), b) < (int("".join(c for c in gamever if c.isdigit())), gamever)]
    return older[-1] if older else None


def compare(gamever, prev):
    new_index = P.load_snapshot_index(os.path.join("gamesymbols", f"{gamever}.yaml"))
    old_index = P.load_snapshot_index(os.path.join("gamesymbols", f"{prev}.yaml"))
    new_bins, old_bins = P.Binaries("bin", gamever), P.Binaries("bin", prev)
    changed, checked = [], 0
    for symbol, keys in sorted(shipped_symbols().items()):
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
            a = fingerprint(ob, oi, V._hexint(old["func_va"]), platform)
            b = fingerprint(nb, ni, V._hexint(new["func_va"]), platform)
            if not a or not b:
                continue
            checked += 1
            if (a["int"], a["float"], a["stack"]) != (b["int"], b["float"], b["stack"]):
                changed.append({"symbol": symbol, "platform": platform, "keys": keys,
                                "before": a, "after": b,
                                "arity": [arity(a), arity(b)]})
    return checked, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-prev", default=None, help="default: the newest older build under bin/")
    parser.add_argument("-json", action="store_true")
    args = parser.parse_args()
    if capstone is None:
        print("audit_arg_fingerprint: capstone is required", file=sys.stderr)
        return 2
    prev = args.prev or _previous(args.gamever)
    if not prev:
        print(f"audit_arg_fingerprint: no previous build under bin/ for {args.gamever}")
        return 0
    checked, changed = compare(args.gamever, prev)
    if args.json:
        print(json.dumps({"gamever": args.gamever, "prev": prev, "checked": checked, "changed": changed}, indent=1))
    else:
        for row in changed:
            before, after = row["before"], row["after"]
            print(f"ARGS CHANGED {row['symbol']}.{row['platform']} ({', '.join(row['keys'])}): "
                  f"{'+'.join(before['int'] + before['float']) or '-'}{' +%d stack' % before['stack'] if before['stack'] else ''}"
                  f" -> {'+'.join(after['int'] + after['float']) or '-'}{' +%d stack' % after['stack'] if after['stack'] else ''}")
        print(f"audit_arg_fingerprint {args.gamever} vs {prev}: {checked} shipped function(s) compared, "
              f"{len(changed)} changed their arguments")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
