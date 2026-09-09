#!/usr/bin/env python3
"""Add func_sig to virtualFunction artifacts that lack one.

623 of 1354 vfunc records in a gamever snapshot carry no byte pattern, so signature
trackers cannot compare against them even though the index/offset is correct. The
vfunc schema allows func_sig (FUNC_YAML_ORDER), and each record already carries the
resolved func_va — so the sig is derivable offline: read the function head bytes in
the platform binary and grow a literal pattern until it is module-unique.

Idempotent: artifacts that already carry func_sig are untouched.

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


def count_matches(blob, sig_bytes):
    rx = re.compile(re.escape(sig_bytes), re.DOTALL)
    n = 0
    for m in rx.finditer(blob):
        n += 1
        if n > 1:
            return n
    return n


def build_sig(blob, va_to_off, va):
    off = va_to_off(va)
    if off is None:
        return None
    for ln in range(MIN_SIG, MAX_SIG + 1, 8):
        sig = blob[off:off + ln]
        if len(sig) < ln:
            return None
        if count_matches(blob, sig) == 1:
            return " ".join(f"{b:02X}" for b in sig)
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
