#!/usr/bin/env python3
"""Add func_sig to virtualFunction artifacts that lack one.

623 of 1354 vfunc records in a gamever snapshot carry no byte pattern, so signature
trackers cannot compare against them even though the index/offset is correct. The
vfunc schema allows func_sig (FUNC_YAML_ORDER), and each record already carries the
resolved func_va — so the sig is derivable offline: read the function head bytes in
the platform binary and grow a literal pattern until it is module-unique.

Idempotent: artifacts that already carry func_sig are untouched.

Volatile operand bytes (a relative branch/call target, a RIP-relative
displacement) are emitted as ?? — they encode a distance that moves whenever
anything around the function moves, so pinning them ships a signature that
breaks on the next build even when the function is identical.

ALWAYS run validate_artifacts.py afterwards and drop any func_sig it reports as
matching more than one place. Wildcarding a displacement can make a tiny stub
collide with an adjacent twin that differs only in those bytes; three did on
14181. A non-unique signature is worse than none, because a plugin resolving it
silently picks the wrong function.

Usage:
  uv run enrich_vfunc_sigs.py -gamever 14178b                 # begge platforme
  uv run enrich_vfunc_sigs.py -gamever 14178b -platform linux
"""

import argparse
import glob
import os
import re
import struct

BIN_LINUX = {"server": "libserver.so", "engine": "libengine2.so", "client": "libclient.so",
             "SDL3": "libSDL3.so.0", "scenesystem": "libscenesystem.so",
             "networksystem": "libnetworksystem.so", "matchmaking": "libmatchmaking.so",
             "vphysics2": "libvphysics2.so"}
BIN_WIN = {k: v.replace("lib", "").replace(".so", "").replace(".so.0", ".dll").replace("SDL3.dll", "SDL3.dll") for k, v in BIN_LINUX.items()}
BIN_WIN = {"server": "server.dll", "engine": "engine2.dll", "client": "client.dll",
           "SDL3": "SDL3.dll", "scenesystem": "scenesystem.dll",
           "networksystem": "networksystem.dll", "matchmaking": "matchmaking.dll",
           "vphysics2": "vphysics2.dll"}

MIN_SIG, MAX_SIG = 16, 96
# A head sig is shipped to plugins, so it must survive a rebuild that does not
# touch the function. Two byte classes do not: a relative branch/call target and
# a RIP-relative displacement both encode a distance that moves when anything
# around the function moves. Both are wildcarded instead of being pinned.
try:
    import capstone
    _MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    _MD.detail = True
except Exception:  # capstone missing: fall back to literal runs
    _MD = None


def elf_segs(blob):
    e_phoff = struct.unpack_from("<Q", blob, 32)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", blob, 54)
    out = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", blob, off)[0]
        p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<QQQQ", blob, off + 8)
        if p_type == 1:
            out.append((p_offset, p_vaddr, p_filesz))
    return out


def pe_segs(blob):
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    nsec = struct.unpack_from("<H", blob, e_lfanew + 6)[0]
    size_opt = struct.unpack_from("<H", blob, e_lfanew + 20)[0]
    opt = e_lfanew + 24
    image_base = struct.unpack_from("<Q", blob, opt + 24)[0]
    out = []
    for i in range(nsec):
        off = opt + size_opt + i * 40
        vaddr, rawsize, rawptr = struct.unpack_from("<III", blob, off + 12)
        out.append((rawptr, image_base + vaddr, rawsize))
    return out


def count_matches(blob, tokens):
    """tokens: list of ints, or None for a wildcard byte."""
    pattern = b"".join(b"." if t is None else re.escape(bytes([t])) for t in tokens)
    rx = re.compile(pattern, re.DOTALL)
    n = 0
    for _ in rx.finditer(blob):
        n += 1
        if n > 1:
            return n
    return n


def _volatile_offsets(ins):
    """Byte offsets inside one instruction that encode a distance, not an opcode."""
    out = set()
    if _MD is None:
        return out
    # relative branch or call: the whole immediate is the distance
    if ins.group(capstone.x86.X86_GRP_JUMP) or ins.group(capstone.x86.X86_GRP_CALL):
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_IMM:
                width = 1 if ins.size <= 2 else 4
                out.update(range(ins.size - width, ins.size))
    # RIP-relative memory operand: disp32 sits immediately before any immediate
    for op in ins.operands:
        if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
            imm_width = 0
            for other in ins.operands:
                if other.type == capstone.x86.X86_OP_IMM:
                    imm_width = other.size
            end = ins.size - imm_width
            out.update(range(max(0, end - 4), end))
    return out


def _tokens_for(blob, off, length):
    """Byte tokens for blob[off:off+length], wildcarding volatile operand bytes."""
    raw = blob[off:off + length]
    tokens = list(raw)
    if _MD is None:
        return tokens
    pos = 0
    for ins in _MD.disasm(raw, 0):
        if pos + ins.size > length:
            break
        for rel in _volatile_offsets(ins):
            tokens[pos + rel] = None
        pos += ins.size
    return tokens


def _instruction_ends(blob, off, limit):
    """Lengths at which a sig would end on an instruction boundary."""
    if _MD is None:
        return list(range(MIN_SIG, limit + 1, 8))
    ends, total = [], 0
    for ins in _MD.disasm(blob[off:off + limit], 0):
        total += ins.size
        if total > limit:
            break
        if total >= MIN_SIG:
            ends.append(total)
    return ends or list(range(MIN_SIG, limit + 1, 8))


def build_sig(blob, va_to_off, va):
    off = va_to_off(va)
    if off is None or off + MAX_SIG > len(blob):
        return None
    for ln in _instruction_ends(blob, off, MAX_SIG):
        tokens = _tokens_for(blob, off, ln)
        if len(tokens) < ln:
            return None
        # An all-wildcard tail carries no information; require real bytes.
        if sum(1 for t in tokens if t is not None) < MIN_SIG // 2:
            continue
        if count_matches(blob, tokens) == 1:
            return " ".join("??" if t is None else f"{t:02X}" for t in tokens)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-gamever", default="14178b")
    ap.add_argument("-platform", choices=("linux", "windows"))
    ap.add_argument("-bindir", default="bin")
    args = ap.parse_args()
    platforms = [args.platform] if args.platform else ["linux", "windows"]

    for plat in platforms:
        bins = BIN_LINUX if plat == "linux" else BIN_WIN
        enriched = skipped = failed = 0
        for mod, binname in sorted(bins.items()):
            binpath = f"{args.bindir}/{args.gamever}/{mod}/{binname}"
            if not os.path.exists(binpath):
                continue
            blob = open(binpath, "rb").read()
            segs = elf_segs(blob) if plat == "linux" else pe_segs(blob)
            def va_to_off(va):
                for fo, v, fs in segs:
                    if v <= va < v + fs:
                        return fo + (va - v)
                return None
            for path in sorted(glob.glob(f"bin_artifacts/{args.gamever}/{mod}/*.{plat}.yaml")):
                text = open(path).read()
                if "vfunc_index" not in text or "func_sig:" in text:
                    if "vfunc_index" in text and "func_sig:" in text:
                        skipped += 1
                    continue
                mva = re.search(r"func_va: '?(0x[0-9a-fA-F]+)'?", text)
                if not mva:
                    failed += 1
                    continue
                va = int(mva.group(1), 16)
                sig = build_sig(blob, va_to_off, va)
                if not sig:
                    failed += 1
                    continue
                # indsæt func_sig efter func_size (FUNC_YAML_ORDER)
                if "func_size:" in text:
                    text = re.sub(r"(func_size: .*\n)", r"\1func_sig: " + sig + "\n", text, count=1)
                else:
                    text = text.replace("func_va:", f"func_sig: {sig}\nfunc_va:", 1)
                open(path, "w").write(text)
                enriched += 1
        print(f"[{plat}] beriget: {enriched} | havde allerede: {skipped} | fejlede: {failed}")


if __name__ == "__main__":
    main()
