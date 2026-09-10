#!/usr/bin/env python3
"""Headless auto-hunt: find missing artifacts WITHOUT IDA GUI.

Runs the same 5 strategies as the IDA plugin (ida_auto_hunt.py) but uses pure
Python binary parsing (ELF/PE + regex scans + relocation tables) — no IDA
license, no GUI, no MCP server. Designed for the 9950X server.

Strategies per symbol (in order):
  1. RELOCATION   — baseline artifact's sig regex-scanned in the new binary
  2. VTABLE-WALK  — RTTI typeinfo → vtable → slot (ELF: .rela.dyn; PE: raw qwords)
  3. SEED-SIG     — community sigs from gamedata-generators/*/gamedata/*.json
  4. SIBLING      — solved same-class symbols → VA-delta → candidate
  5. STRING-ANCHOR— class/function name strings in binary → RIP-relative xrefs

Usage:
  uv run auto_hunt_headless.py -gamever 14180                    # both platforms
  uv run auto_hunt_headless.py -gamever 14180 -platform linux
  uv run auto_hunt_headless.py -gamever 14180 -module server      # specific module
"""

import argparse
import glob
import json
import os
import re
import struct

# =============================================================================
# Binary loading and VA mapping
# =============================================================================

def load_binary(path):
    blob = open(path, "rb").read()
    if blob[:4] == b"\x7fELF":
        return _load_elf(blob)
    elif blob[:2] == b"MZ":
        return _load_pe(blob)
    return None, None


def _load_elf(blob):
    e_phoff = struct.unpack_from("<Q", blob, 32)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", blob, 54)
    segs = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, p_flags = struct.unpack_from("<II", blob, o)
        p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<QQQQ", blob, o + 8)
        if p_type == 1:
            segs.append((p_offset, p_vaddr, p_filesz, p_flags))
    return blob, {"type": "elf", "segs": segs, "base": 0}


def _load_pe(blob):
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    nsec = struct.unpack_from("<H", blob, e_lfanew + 6)[0]
    size_opt = struct.unpack_from("<H", blob, e_lfanew + 20)[0]
    opt = e_lfanew + 24
    base = struct.unpack_from("<Q", blob, opt + 24)[0]
    segs = []
    for i in range(nsec):
        off = opt + size_opt + i * 40
        vaddr, rawsize, rawptr = struct.unpack_from("<III", blob, off + 12)
        characteristics = struct.unpack_from("<I", blob, off + 36)[0]
        # normalise to the ELF PF_X convention (bit 0) that scan_sig tests, so a
        # hardcoded 0x80000000 no longer makes every PE section non-executable
        flags = 0x1 if characteristics & 0x20000000 else 0x0
        segs.append((rawptr, base + vaddr, rawsize, flags))
    return blob, {"type": "pe", "segs": segs, "base": base}


def va_to_off(info, va):
    for fo, v, fs, _ in info["segs"]:
        if v <= va < v + fs:
            return fo + (va - v)
    return None


def off_to_va(info, off):
    for fo, v, fs, _ in info["segs"]:
        if fo <= off < fo + fs:
            return v + (off - fo)
    return None


# =============================================================================
# ELF relocations (vtable discovery)
# =============================================================================

def elf_relocations(blob):
    """Parse R_X86_64_RELATIVE relocations → {site_va: target_va}."""
    e_shoff = struct.unpack_from("<Q", blob, 40)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", blob, 58)
    def sh(i):
        o = e_shoff + i * e_shentsize
        return struct.unpack_from("<IIQQQQ", blob, o)
    shstr_off = sh(e_shstrndx)[4]
    rel = {}
    for i in range(e_shnum):
        nm, typ, flags, addr, off, size = sh(i)
        name = blob[shstr_off + nm:blob.index(b"\x00", shstr_off + nm)].decode()
        if typ == 4 and "rela" in name:
            for j in range(off, off + size, 24):
                r_offset, r_info, r_addend = struct.unpack_from("<QQq", blob, j)
                if r_info & 0xFFFFFFFF == 8:  # R_X86_64_RELATIVE
                    rel[r_offset] = r_addend
    return rel


# =============================================================================
# Signature scanning
# =============================================================================

def sig_to_regex(sig):
    toks = []
    for p in sig.split():
        if p in ("?", "??"):
            toks.append(b".")
        else:
            toks.append(re.escape(bytes([int(p, 16)])))
    return re.compile(b"".join(toks), re.DOTALL)


def scan_sig(blob, info, sig):
    """Scan executable segments; return list of VAs (max 2)."""
    rx = sig_to_regex(sig)
    hits = []
    for fo, v, fs, flags in info["segs"]:
        if not (flags & 0x1):  # PF_X or PE exec section
            continue
        chunk = blob[fo:fo + fs]
        pos = rx.search(chunk)
        while pos:
            hits.append(v + pos.start())
            if len(hits) > 1:
                return hits
            pos = rx.search(chunk, pos.start() + 1)
    return hits


def boundary_ok(blob, info, va):
    off = va_to_off(info, va)
    if off is None or off < 6:
        return False
    prev = blob[off - 6:off]
    return (b"\xcc" in prev or prev.endswith(b"\x90")
            or b"\x0f\x0b" in prev or prev.endswith(b"\xc3"))


def head_sig(blob, info, va, max_len=160):
    off = va_to_off(info, va)
    if off is None:
        return None
    for ln in range(16, max_len + 1, 8):
        raw = blob[off:off + ln]
        if len(raw) < ln:
            return None
        if len(scan_sig(blob, info, " ".join(f"{b:02X}" for b in raw))) <= 1:
            return " ".join(f"{b:02X}" for b in raw)
    return None


# =============================================================================
# Artifact I/O
# =============================================================================

def parse_yaml_fields(path):
    fields = {}
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"(\w+): '?([^'\n]*)'?", line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return fields


def baseline_artifact(repo, module, symbol, platform, gamever):
    cands = []
    for d in glob.glob(os.path.join(repo, "bin_artifacts", "*", module)):
        ver = os.path.basename(os.path.dirname(d))
        if ver == gamever:
            continue
        p = os.path.join(d, f"{symbol}.{platform}.yaml")
        if os.path.exists(p):
            cands.append((ver, p))
    if not cands:
        return None, None
    # gamever as a number plus the optional letter suffix - sorting on string
    # length instead makes 14178b (6 chars) outrank 14181 (5 chars)
    def sort_key(cand):
        m = re.fullmatch(r"(\d+)([a-z]?)", cand[0])
        return (int(m.group(1)), m.group(2)) if m else (-1, cand[0])

    cands.sort(key=sort_key)
    return cands[-1]


def emit(repo, gamever, module, symbol, platform, text):
    for root in ("bin", "bin_artifacts"):
        d = os.path.join(repo, root, gamever, module)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{symbol}.{platform}.yaml"), "w") as f:
            f.write(text)


# =============================================================================
# Strategies
# =============================================================================

def strat_relocation(repo, gamever, module, symbol, platform, blob, info):
    ver, path = baseline_artifact(repo, module, symbol, platform, gamever)
    if not path:
        return None, "ingen baseline"
    f = parse_yaml_fields(path)
    sig = f.get("func_sig") or f.get("offset_sig")
    if not sig:
        return None, f"baseline {ver} uden sig"
    hits = scan_sig(blob, info, sig)
    if len(hits) != 1:
        return None, f"baseline {ver}: {len(hits)} hits"
    va = hits[0]
    text = relocated_artifact_text(symbol, f, sig, va, blob, info)
    emit(repo, gamever, module, symbol, platform, text)
    return True, f"reloc {ver} @ {hex(va)}"


def _validated_func_size(blob, info, va, baseline_size):
    """Carry the baseline size only if it still lands on a function boundary.

    Sizes are stable across a gamever bump, but writing an unverified number is
    worse than writing none - so it is confirmed against the bytes at the new VA
    (last byte a ret/jmp tail, next byte padding or a fresh function head).
    """
    if not baseline_size:
        return "0x0"
    try:
        size = int(str(baseline_size), 16)
    except ValueError:
        return "0x0"
    off = va_to_off(info, va)
    if off is None or size <= 0 or off + size >= len(blob):
        return "0x0"
    last, nxt = blob[off + size - 1], blob[off + size]
    if nxt in (0xCC, 0x90) or last in (0xC3, 0xE9, 0xEB):
        return hex(size)
    return "0x0"


def relocated_artifact_text(symbol, f, sig, va, blob, info):
    """Render the relocated artifact in the SAME schema as its baseline.

    Emitting a func_* payload for a structmember baseline is what produced the
    corrupted BotProfile/CCSBot_Profile windows artifacts (func_name + func_size
    0x0 carrying an offset_sig), which canonical_symbol_yaml_bytes rejects.
    """
    if f.get("struct_name") and f.get("member_name"):
        text = (f"struct_name: {f['struct_name']}\nmember_name: {f['member_name']}\n"
                f"offset: '{f.get('offset')}'\n")
        if f.get("size") is not None:
            text += f"size: {f['size']}\n"
        text += f"offset_sig: {sig}\n"
        for extra in ("offset_sig_disp", "offset_sig_max_match", "offset_sig_allow_across_function_boundary"):
            if f.get(extra) is not None:
                text += f"{extra}: {f[extra]}\n"
        return text

    size = _validated_func_size(blob, info, va, f.get("func_size"))
    text = (f"func_name: {symbol}\nfunc_va: '{hex(va)}'\nfunc_rva: '{hex(va - info['base'])}'\n"
            f"func_size: '{size}'\nfunc_sig: {sig}\n")
    if f.get("vtable_name") and f.get("vfunc_index") is not None:
        idx = int(f["vfunc_index"])
        text += (f"vtable_name: {f['vtable_name']}\nvfunc_offset: '{hex(idx * 8)}'\n"
                 f"vfunc_index: {idx}\n")
    return text


def strat_vtable(repo, gamever, module, symbol, platform, blob, info, rel):
    ver, path = baseline_artifact(repo, module, symbol, platform, gamever)
    if not path:
        return None, "ingen baseline"
    f = parse_yaml_fields(path)
    vt_name = f.get("vtable_name")
    idx = f.get("vfunc_index")
    if not vt_name or idx is None:
        return None, "ikke vfunc"
    idx = int(idx)

    if info["type"] == "elf":
        fn = _vtable_slot_elf(blob, info, rel, vt_name, idx)
    else:
        fn = _vtable_slot_pe(blob, info, vt_name, idx)
    if not fn:
        return None, f"vtable {vt_name} slot {idx} ikke fundet"
    sig = head_sig(blob, info, fn)
    if not sig:
        return None, f"vtable {vt_name}[{idx}] @ {hex(fn)} — ikke unik"
    text = (f"func_name: {symbol}\nfunc_va: '{hex(fn)}'\nfunc_rva: '{hex(fn - info['base'])}'\n"
            f"func_size: '0x0'\nfunc_sig: {sig}\n"
            f"vtable_name: {vt_name}\nvfunc_offset: '{hex(idx * 8)}'\nvfunc_index: {idx}\n")
    emit(repo, gamever, module, symbol, platform, text)
    return True, f"vtable {vt_name}[{idx}] @ {hex(fn)}"


def _vtable_slot_elf(blob, info, rel, class_name, index):
    needle = f"{len(class_name)}{class_name}".encode()
    pos = blob.find(needle + b"\x00")
    if pos == -1:
        return None
    ts_va = off_to_va(info, pos)
    if ts_va is None:
        return None
    ztis = [o for o, a in rel.items() if a == ts_va]
    for zti in ztis:
        for site, a in rel.items():
            if a == zti:
                vt = site + 8
                fn = rel.get(vt + 8 * index)
                if fn and va_to_off(info, fn) is not None:
                    return fn
    return None


def _vtable_slot_pe(blob, info, class_name, index):
    mangled = f".?AV{class_name}@@".encode()
    pos = blob.find(mangled + b"\x00")
    if pos == -1:
        return None
    td_va = off_to_va(info, pos - 16)
    if td_va is None:
        return None
    td_rva = td_va - info["base"]
    needle_rva = struct.pack("<I", td_rva)
    p = blob.find(needle_rva)
    while p != -1:
        col_off = p - 12
        sig = struct.unpack_from("<I", blob, col_off)[0]
        if sig == 1:
            col_va = off_to_va(info, col_off)
            if col_va:
                needle_col = struct.pack("<Q", col_va)
                p2 = blob.find(needle_col)
                while p2 != -1:
                    vt_off = p2 + 8
                    for seg_fo, seg_va, seg_sz, _ in info["segs"]:
                        pass
                    fn = struct.unpack_from("<Q", blob, vt_off + 8 * index)[0]
                    if va_to_off(info, fn) is not None:
                        return fn
                    p2 = blob.find(needle_col, p2 + 1)
        p = blob.find(needle_rva, p + 1)
    return None


def strat_seed_sig(repo, gamever, module, symbol, platform, blob, info):
    for jp in glob.glob(os.path.join(repo, "gamedata-generators", "*", "gamedata", "*.json")):
        try:
            d = json.load(open(jp))
        except (OSError, json.JSONDecodeError):
            continue
        for key, entry in d.items():
            if key.replace("::", "_") != symbol:
                continue
            sig = entry.get("signatures", {}).get(platform) if isinstance(entry.get("signatures"), dict) else None
            if not sig:
                continue
            hits = scan_sig(blob, info, sig)
            if len(hits) == 1:
                va = hits[0]
                fresh = head_sig(blob, info, va, 96) or sig
                text = (f"func_name: {symbol}\nfunc_va: '{hex(va)}'\nfunc_rva: '{hex(va - info['base'])}'\n"
                        f"func_size: '0x0'\nfunc_sig: {fresh}\n")
                emit(repo, gamever, module, symbol, platform, text)
                return True, f"seed-sig @ {hex(va)}"
    return None, "ingen seed-sig"


def strat_sibling(repo, gamever, module, symbol, platform, blob, info):
    parts = symbol.rsplit("_", 1)
    if len(parts) < 2:
        return None, "intet praefiks"
    prefix = parts[0]

    ver, path = baseline_artifact(repo, module, symbol, platform, gamever)
    if not path:
        return None, "ingen baseline"
    f = parse_yaml_fields(path)
    my_va = f.get("func_va")
    if not my_va:
        return None, "baseline uden VA"
    my_va = int(my_va, 16)

    for gp in glob.glob(os.path.join(repo, "bin_artifacts", gamever, module, f"{prefix}_*.{platform}.yaml")):
        sib = os.path.basename(gp).rsplit(".", 2)[0]
        if sib == symbol:
            continue
        sf = parse_yaml_fields(gp)
        sib_new_va = sf.get("func_va")
        if not sib_new_va:
            continue
        sib_new_va = int(sib_new_va, 16)
        _, sib_base_path = baseline_artifact(repo, module, sib, platform, gamever)
        if not sib_base_path:
            continue
        sib_bf = parse_yaml_fields(sib_base_path)
        sib_old_va = sib_bf.get("func_va")
        if not sib_old_va:
            continue
        sib_old_va = int(sib_old_va, 16)
        delta = my_va - sib_old_va
        candidate = sib_new_va + delta
        if boundary_ok(blob, info, candidate):
            sig = head_sig(blob, info, candidate)
            if sig:
                text = (f"func_name: {symbol}\nfunc_va: '{hex(candidate)}'\nfunc_rva: '{hex(candidate - info['base'])}'\n"
                        f"func_size: '0x0'\nfunc_sig: {sig}\n")
                emit(repo, gamever, module, symbol, platform, text)
                return True, f"sibling {sib} Δ{hex(delta)} → {hex(candidate)}"
    return None, "intet sibling-hit"


def strat_string_anchor(repo, gamever, module, symbol, platform, blob, info):
    class_part = symbol.rsplit("_", 1)[0] if "_" in symbol else symbol
    func_part = symbol.rsplit("_", 1)[-1] if "_" in symbol else symbol
    terms = [f"{class_part}::{func_part}", func_part]

    for term in terms[:1]:  # kun Class::Func-formatet er paalideligt
        tbytes = term.encode()
        pos = blob.find(tbytes + b"\x00")
        while pos != -1:
            sva = off_to_va(info, pos)
            if sva is None:
                pos = blob.find(tbytes + b"\x00", pos + 1)
                continue
            # find RIP-relative lea til denne streng
            for fo, v, fs, flags in info["segs"]:
                if not (flags & 0x1):
                    continue
                chunk = blob[fo:fo + fs]
                for m in re.finditer(rb"[\x48\x4C]\x8D[\x05\x0D\x15\x1D\x25\x2D\x35\x3D]", chunk):
                    i = m.start()
                    disp = struct.unpack_from("<i", chunk, i + 3)[0]
                    if (v + i + 7 + disp) == sva:
                        # ga tilbage til funktionstart
                        ho = fo + i
                        while ho > 0 and blob[ho - 1] != 0xCC:
                            ho -= 1
                        fva = off_to_va(info, ho)
                        if fva and boundary_ok(blob, info, fva):
                            sig = head_sig(blob, info, fva)
                            if sig:
                                text = (f"func_name: {symbol}\nfunc_va: '{hex(fva)}'\nfunc_rva: '{hex(fva - info['base'])}'\n"
                                        f"func_size: '0x0'\nfunc_sig: {sig}\n")
                                emit(repo, gamever, module, symbol, platform, text)
                                return True, f"string '{term[:25]}' → {hex(fva)}"
            pos = blob.find(tbytes + b"\x00", pos + 1)
    return None, "intet string-anchor-hit"


# =============================================================================
# Main
# =============================================================================

BIN_LINUX = {"SDL3": "libSDL3.so.0", "client": "libclient.so", "engine": "libengine2.so",
             "matchmaking": "libmatchmaking.so", "networksystem": "libnetworksystem.so",
             "scenesystem": "libscenesystem.so", "server": "libserver.so", "vphysics2": "libvphysics2.so"}
BIN_WIN = {"SDL3": "SDL3.dll", "client": "client.dll", "engine": "engine2.dll",
           "matchmaking": "matchmaking.dll", "networksystem": "networksystem.dll",
           "scenesystem": "scenesystem.dll", "server": "server.dll", "vphysics2": "vphysics2.dll"}

STRATEGIES = [
    ("reloc", strat_relocation),
    ("vtable", strat_vtable),
    ("seed", strat_seed_sig),
    ("sibling", strat_sibling),
    ("string", strat_string_anchor),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-platform", choices=("linux", "windows"))
    ap.add_argument("-module", help="specific module only")
    ap.add_argument("-repo", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    repo = args.repo
    platforms = [args.platform] if args.platform else ["linux", "windows"]

    grand_solved = grand_queue = 0

    for platform in platforms:
        bins = BIN_LINUX if platform == "linux" else BIN_WIN
        listfile = os.path.join(repo, f"missing_{platform}_{args.gamever}.txt")
        if not os.path.exists(listfile):
            print(f"[{platform}] missing-list findes ikke — kør missing_report.py foerst")
            continue

        targets = {}
        for line in open(listfile):
            line = line.strip()
            if not line or "/" not in line:
                continue
            mod, rest = line.split("/", 1)
            sym = rest.split(" ->")[0].split(" ")[0]
            if args.module and mod != args.module:
                continue
            targets.setdefault(mod, []).append(sym)

        for mod in sorted(targets):
            binpath = os.path.join(repo, "bin", args.gamever, mod, bins.get(mod, ""))
            if not os.path.exists(binpath):
                print(f"[{platform}/{mod}] binær mangler: {binpath}")
                continue
            blob, info = load_binary(binpath)
            if blob is None:
                print(f"[{platform}/{mod}] kan ikke laese: {binpath}")
                continue
            rel = elf_relocations(blob) if info["type"] == "elf" else {}

            solved, queue = [], []
            for symbol in targets[mod]:
                for name, fn in STRATEGIES:
                    try:
                        if name == "vtable":
                            ok, how = fn(repo, args.gamever, mod, symbol, platform, blob, info, rel)
                        else:
                            ok, how = fn(repo, args.gamever, mod, symbol, platform, blob, info)
                    except Exception as e:
                        ok, how = None, f"{name}-fejl: {e}"
                    if ok:
                        solved.append((symbol, f"[{name}] {how}"))
                        break
                else:
                    queue.append(symbol)

            print(f"\n[{platform}/{mod}] {len(targets[mod])} manglende → {len(solved)} LØST, {len(queue)} KØ")
            for s, how in solved:
                print(f"  ✓ {s} {how}")
            for s in queue:
                print(f"  ✗ {s}")

            grand_solved += len(solved)
            grand_queue += len(queue)

    print(f"\n{'=' * 60}")
    print(f"IALT: {grand_solved} løst, {grand_queue} til manual jagt")
    if grand_solved:
        print(f"git add bin_artifacts/{args.gamever} && git commit -m 'auto-hunt' && git push")


if __name__ == "__main__":
    main()
