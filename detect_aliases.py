#!/usr/bin/env python3
"""Detect old-named gamedata keys that reference already-analyzed functions.

For each seed gamedata entry with a stored signature that is NOT covered by the
current snapshot, scan the platform's binary for matches and check whether a match
lands exactly on an already-analyzed function's VA. If so, the old key is an
old-named reference to the canonical symbol -> alias candidate.

Usage:
  uv run detect_aliases.py -gamever 14178b -platform linux   # libserver.so
  uv run detect_aliases.py -gamever 14178b -platform windows # server.dll
"""
import argparse
import glob
import json
import os
import re
import struct

SEEDS = [
    "matchzy",
    "bot-controller",
    "bot-hider",
    "weaponpaints",
]

SNAPSHOT = "gamesymbols/{gamever}.yaml"


def covered_names(gamever):
    import yaml
    snap = yaml.safe_load(open(SNAPSHOT.format(gamever=gamever)))
    return {e["func_name"] for e in (snap.get("files") or {}).values()
            if isinstance(e, dict) and "func_name" in e}


def analyzed_index(artifactdir, platform):
    ext = "windows" if platform == "windows" else "linux"
    index = {}
    for path in glob.glob(f"{artifactdir}/server/*.{ext}.yaml"):
        text = open(path).read()
        name = re.search(r"func_name: (\S+)", text)
        va = re.search(r"func_va: '?0x([0-9a-fA-F]+)'?", text)
        sig = re.search(r"func_sig: (.+)", text)
        if name and va and sig:
            index[name.group(1)] = {"va": int(va.group(1), 16), "sig": " ".join(sig.group(1).split())}
    return index


def load_binary(path):
    return open(path, "rb").read()


def elf_off_to_va_map(blob):
    e_phoff = struct.unpack_from("<Q", blob, 32)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", blob, 54)
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", blob, off)[0]
        p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<QQQQ", blob, off + 8)
        if p_type == 1:
            segs.append((p_offset, p_vaddr, p_filesz))
    return segs


def pe_off_to_va_map(blob):
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    assert blob[e_lfanew:e_lfanew + 4] == b"PE\0\0"
    machine, nsec = struct.unpack_from("<HH", blob, e_lfanew + 6)
    size_opt = struct.unpack_from("<H", blob, e_lfanew + 20)[0]
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", blob, opt)[0]
    assert magic == 0x20B, "PE32+ expected"
    image_base = struct.unpack_from("<Q", blob, opt + 24)[0]
    sec_off = opt + size_opt
    segs = []
    for i in range(nsec):
        off = sec_off + i * 40
        vaddr, rawsize, rawptr = struct.unpack_from("<II I".replace(" ", ""), blob, off + 12)
        segs.append((rawptr, image_base + vaddr, rawsize))
    return segs


def off_to_va(segs, off):
    for raw, va, size in segs:
        if raw <= off < raw + size:
            return va + (off - raw)
    return None


def sig_to_regex(sig):
    toks = []
    for p in sig.split():
        toks.append(b"." if p in ("?", "??") else re.escape(bytes([int(p, 16)])))
    return re.compile(b"".join(toks), re.DOTALL)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-platform", required=True, choices=("windows", "linux"))
    ap.add_argument("-artifactdir", default="bin_artifacts")
    args = ap.parse_args()

    ext = "windows" if args.platform == "windows" else "linux"
    binname = "server.dll" if args.platform == "windows" else "libserver.so"
    binary_path = f"bin/{args.gamever}/server/{binname}"

    covered = covered_names(args.gamever)
    index = analyzed_index(args.artifactdir, args.platform)
    blob = load_binary(binary_path)
    segs = pe_off_to_va_map(blob) if args.platform == "windows" else elf_off_to_va_map(blob)

    aliases, ambiguous, nofind = [], [], []
    for seed in SEEDS:
        seed_path = f"gamedata-generators/{seed}/gamedata/{seed}.json"
        if not os.path.exists(seed_path):
            continue
        d = json.load(open(seed_path))
        for key, entry in d.items():
            norm = key.replace("::", "_")
            if norm in covered:
                continue
            sig = entry.get("signatures", {}).get(args.platform)
            if not sig:
                continue
            matches = [m.start() for m in sig_to_regex(" ".join(sig.split())).finditer(blob)]
            vas = [off_to_va(segs, o) for o in matches]
            evidence = [(f, i) for f, i in index.items() if i["va"] in vas]
            if len(evidence) == 1:
                fname = evidence[0][0]
                if fname != norm:
                    print(f"ALIAS: {key}  ->  {fname}  (VA {hex(evidence[0][1]['va'])})")
                    aliases.append({"seed": seed, "key": key, "from": norm, "canonical": fname})
                else:
                    print(f"SAME-NAME: {key} (normaliseret navn = analyseret; ingen alias nodvendig)")
            elif len(evidence) > 1:
                ambiguous.append((key, [e[0] for e in evidence]))
            else:
                nofind.append((key, len(matches)))

    print()
    print(f"alias-kandidater : {len(aliases)}")
    for a in aliases:
        print(f"    {a['key']}  ->  {a['canonical']}")
    print(f"tvetydige        : {len(ambiguous)}")
    for k, c in ambiguous:
        print(f"    {k}: {c}")
    print(f"intet fund       : {len(nofind)}  (sig stadig gyldig i binaeren, mangler kun analyse-data)")
    for k, n in nofind:
        print(f"    {k} ({n} match(es))")

    out = f"alias_candidates_{args.gamever}_{args.platform}.json"
    json.dump({"aliases": aliases, "ambiguous": ambiguous, "no_analysis": nofind},
              open(out, "w"), indent=1)
    print(f"resultat: {out}")


if __name__ == "__main__":
    main()
