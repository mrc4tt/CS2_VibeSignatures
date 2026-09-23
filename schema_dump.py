#!/usr/bin/env python3
"""schema_dump.py - read Source 2's schema (classes, fields, offsets) straight from a binary.

No game server and no IDA: the class descriptors the schema system registers at start-up
(``SchemaClassInfoData_t`` in hl2sdk_cs2/public/schemasystem/schematypes.h) are static data in
libserver.so / server.dll, so they can be walked from the file like RTTI.

    uv run schema_dump.py dump   -gamever 14182 -module server -platform linux
    uv run schema_dump.py lookup -gamever 14182 -module server -platform linux -class CCSPlayerPawn -offset 0x980
    uv run schema_dump.py diff   -old 14181 -new 14182 -module server -platform linux [-class CBaseEntity]

`dump` writes schema/<gamever>/<module>.<platform>.json (gitignored, regenerated on demand).
`lookup` names the field at an offset, walking base classes (answers "what is 2432 on the pawn?").
`diff` lists fields that moved, appeared or disappeared between two builds.

Layout used (x64, both platforms):
    SchemaClassInfoData_t  +0x08 name  +0x20 size  +0x24 field count  +0x29 base count
                           +0x30 fields  +0x38 base classes
    SchemaClassFieldData_t (0x20)  +0x00 name  +0x10 offset  +0x14 metadata count  +0x18 metadata
    SchemaBaseClassInfoData_t (0x10)  +0x00 offset  +0x08 class
    SchemaMetadataEntryData_t (0x10)  +0x00 name  +0x08 data
The networked flag is not in the static data on 14182 (it is attached at runtime), so it is not
reported; field metadata names that are static (MKV3TransferSaveOpsForField, ...) are.
"""
import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
BINARY_NAMES = {
    ("server", "linux"): "libserver.so", ("server", "windows"): "server.dll",
    ("client", "linux"): "libclient.so", ("client", "windows"): "client.dll",
    ("engine", "linux"): "libengine2.so", ("engine", "windows"): "engine2.dll",
}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_:<>, *]*$")


class Image:
    """Read-only view of an ELF64 or PE32+ image by virtual address."""

    def __init__(self, path):
        self.b = Path(path).read_bytes()
        self.rel = {}
        if self.b[:4] == b"\x7fELF":
            self._elf()
        elif self.b[:2] == b"MZ":
            self._pe()
        else:
            raise ValueError(f"{path}: neither ELF nor PE")

    def _elf(self):
        b = self.b
        phoff, = struct.unpack_from("<Q", b, 0x20)
        pe, pn = struct.unpack_from("<HH", b, 0x36)
        self.maps = []
        for i in range(pn):
            t, fl, off, va, pa, fs, ms, al = struct.unpack_from("<IIQQQQQQ", b, phoff + i * pe)
            if t == 1:
                self.maps.append((va, off, fs, bool(fl & 1)))
        shoff, = struct.unpack_from("<Q", b, 0x28)
        se, sn = struct.unpack_from("<HH", b, 0x3A)
        for i in range(sn):
            _nm, ty, _fl, _ad, off, size, _ln, _inf, _al, _es = struct.unpack_from("<IIQQQQIIQQ", b, shoff + i * se)
            if ty == 4:  # SHT_RELA: R_X86_64_RELATIVE fills pointers at load time
                for j in range(size // 24):
                    where, info, addend = struct.unpack_from("<QQq", b, off + j * 24)
                    if info & 0xFFFFFFFF == 8:
                        self.rel[where] = addend
        self.candidates = sorted(self.rel)

    def _pe(self):
        b = self.b
        o, = struct.unpack_from("<I", b, 0x3C)
        n, = struct.unpack_from("<H", b, o + 6)
        opt, = struct.unpack_from("<H", b, o + 20)
        base, = struct.unpack_from("<Q", b, o + 48)
        self.maps = []
        data = []
        for i in range(n):
            name, vsize, va, rsize, rptr = struct.unpack_from("<8sIIII", b, o + 24 + opt + i * 40)
            chars, = struct.unpack_from("<I", b, o + 24 + opt + i * 40 + 36)
            self.maps.append((base + va, rptr, rsize, bool(chars & 0x20000000)))
            if not chars & 0x20000000 and rsize:
                data.append((base + va, rptr, rsize))
        # absolute pointers already hold the preferred-base VA in the file
        self.candidates = [va + k for va, off, size in data for k in range(0, size - 0x70, 8)]

    def off(self, va):
        for start, off, size, _x in self.maps:
            if start <= va < start + size:
                return off + (va - start)
        return None

    def q(self, va):
        if va in self.rel:
            return self.rel[va]
        f = self.off(va)
        return struct.unpack_from("<Q", self.b, f)[0] if f is not None and f + 8 <= len(self.b) else 0

    def i32(self, va):
        f = self.off(va)
        return struct.unpack_from("<i", self.b, f)[0] if f is not None else None

    def u16(self, va):
        f = self.off(va)
        return struct.unpack_from("<H", self.b, f)[0] if f is not None else None

    def u8(self, va):
        f = self.off(va)
        return self.b[f] if f is not None else None

    def cstr(self, va, limit=160):
        f = self.off(va) if va else None
        if f is None:
            return None
        raw = self.b[f:f + limit].split(b"\0", 1)[0]
        if not raw or not all(32 <= c < 127 for c in raw):
            return None
        return raw.decode("ascii")


def _class_at(img, c):
    """A validated class descriptor at c, or None."""
    name = img.cstr(img.q(c + 0x08))
    if not name or not _IDENT.match(name) or " " in re.sub(r"<.*>", "", name):
        return None
    size = img.i32(c + 0x20)
    nfields = img.u16(c + 0x24)
    nbases = img.u8(c + 0x29)
    if size is None or not (0 < size < 0x1000000) or nfields is None or nfields > 4000 or nbases is None or nbases > 16:
        return None
    fields_ptr = img.q(c + 0x30)
    bases_ptr = img.q(c + 0x38)
    if nfields and img.off(fields_ptr) is None:
        return None
    if nbases and img.off(bases_ptr) is None:
        return None
    fields = []
    for i in range(nfields):
        x = fields_ptr + 0x20 * i
        fname = img.cstr(img.q(x))
        offset = img.i32(x + 0x10)
        if not fname or offset is None or not (0 <= offset <= size):
            return None
        meta = []
        count = img.i32(x + 0x14) or 0
        mptr = img.q(x + 0x18)
        for k in range(min(max(count, 0), 32)):
            mname = img.cstr(img.q(mptr + 0x10 * k))
            if mname:
                meta.append(mname)
        fields.append({"name": fname, "offset": offset, "metadata": meta})
    bases = []
    for k in range(nbases):
        entry = bases_ptr + 0x10 * k
        base_desc = img.q(entry + 8)
        base_name = img.cstr(img.q(base_desc + 0x08)) if base_desc else None
        if not base_name:
            return None
        bases.append({"name": base_name, "offset": img.i32(entry) or 0})
    return {"name": name, "size": size, "bases": bases, "fields": fields, "va": hex(c)}


def dump_image(path):
    img = Image(path)
    classes = {}
    for va in img.candidates:
        c = va - 0x08  # candidates are pointer slots; the name pointer sits at +0x08
        info = _class_at(img, c)
        if info is None:
            continue
        prev = classes.get(info["name"])
        # a class name is also pointed at by other tables; keep the descriptor with the most fields
        if prev is None or len(info["fields"]) > len(prev["fields"]):
            classes[info["name"]] = info
    # A descriptor with no fields and no bases is usually some other table whose +0x08
    # happens to point at a string ("Add Money Player"); keep it only when a real class
    # names it as a base, which is what a genuinely empty base class looks like.
    named_as_base = {b["name"] for c in classes.values() for b in c["bases"]}
    return {
        name: info for name, info in classes.items()
        if info["fields"] or info["bases"] or name in named_as_base
    }


def schema_path(gamever, module, platform):
    return REPO / "schema" / str(gamever) / f"{module}.{platform}.json"


def load_or_dump(gamever, module, platform, bindir="bin"):
    path = schema_path(gamever, module, platform)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    binary = REPO / bindir / str(gamever) / module / BINARY_NAMES[(module, platform)]
    classes = dump_image(binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(classes, indent=1, sort_keys=True), encoding="utf-8")
    return classes


def field_at(classes, cls, offset, base_offset=0):
    """(owner, field, field_offset) covering `offset` inside `cls`, searching base classes."""
    info = classes.get(cls)
    if info is None:
        return None
    best = None
    for f in info["fields"]:
        start = base_offset + f["offset"]
        if start <= offset and (best is None or start > best[2]):
            best = (cls, f["name"], start)
    for b in info["bases"]:
        hit = field_at(classes, b["name"], offset, base_offset + b["offset"])
        if hit and (best is None or hit[2] > best[2]):
            best = hit
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("dump", "lookup"):
        p = sub.add_parser(name)
        p.add_argument("-gamever", required=True)
        p.add_argument("-module", default="server")
        p.add_argument("-platform", choices=("linux", "windows"), default="linux")
        p.add_argument("-bindir", default="bin")
        p.add_argument("-force", action="store_true", help="re-read the binary even if a dump exists")
        if name == "lookup":
            p.add_argument("-class", dest="cls", required=True)
            p.add_argument("-offset", help="hex or decimal offset to name")
            p.add_argument("-field", help="print this field's offset instead")
    d = sub.add_parser("diff")
    d.add_argument("-old", required=True)
    d.add_argument("-new", required=True)
    d.add_argument("-module", default="server")
    d.add_argument("-platform", choices=("linux", "windows"), default="linux")
    d.add_argument("-class", dest="cls")
    d.add_argument("-bindir", default="bin")
    args = ap.parse_args()

    if args.cmd in ("dump", "lookup") and args.force:
        schema_path(args.gamever, args.module, args.platform).unlink(missing_ok=True)

    if args.cmd == "dump":
        classes = load_or_dump(args.gamever, args.module, args.platform, args.bindir)
        nfields = sum(len(c["fields"]) for c in classes.values())
        print(f"{len(classes)} classes, {nfields} fields -> {schema_path(args.gamever, args.module, args.platform)}")
        return 0

    if args.cmd == "lookup":
        classes = load_or_dump(args.gamever, args.module, args.platform, args.bindir)
        if args.cls not in classes:
            print(f"class {args.cls} not found", file=sys.stderr)
            return 1
        if args.field:
            chain, seen = [(args.cls, 0)], set()
            while chain:
                cls, base = chain.pop(0)
                if cls in seen or cls not in classes:
                    continue
                seen.add(cls)
                for f in classes[cls]["fields"]:
                    if f["name"] == args.field:
                        total = base + f["offset"]
                        print(f"{cls}::{f['name']} = {hex(total)} ({total})")
                        return 0
                chain += [(b["name"], base + b["offset"]) for b in classes[cls]["bases"]]
            print(f"{args.field} not found in {args.cls} or its bases", file=sys.stderr)
            return 1
        offset = int(args.offset, 0)
        hit = field_at(classes, args.cls, offset)
        if hit is None:
            print(f"nothing at {hex(offset)} in {args.cls}")
            return 1
        owner, name, start = hit
        inside = f" + {hex(offset - start)}" if offset != start else ""
        print(f"{args.cls} +{hex(offset)} ({offset}) = {owner}::{name}{inside}  (field starts at {hex(start)})")
        return 0

    old = load_or_dump(args.old, args.module, args.platform, args.bindir)
    new = load_or_dump(args.new, args.module, args.platform, args.bindir)
    names = [args.cls] if args.cls else sorted(set(old) | set(new))
    moved = added = removed = 0
    for cls in names:
        a, b = old.get(cls), new.get(cls)
        if a is None or b is None:
            if not args.cls:
                continue
            print(f"{cls}: only in {'new' if a is None else 'old'}")
            continue
        fa = {f["name"]: f["offset"] for f in a["fields"]}
        fb = {f["name"]: f["offset"] for f in b["fields"]}
        lines = []
        for name in sorted(set(fa) | set(fb), key=lambda n: fb.get(n, fa.get(n))):
            if name not in fb:
                lines.append(f"   - {name} (was {hex(fa[name])})"); removed += 1
            elif name not in fa:
                lines.append(f"   + {name} {hex(fb[name])}"); added += 1
            elif fa[name] != fb[name]:
                lines.append(f"   ~ {name} {hex(fa[name])} -> {hex(fb[name])}"); moved += 1
        if lines or a["size"] != b["size"]:
            print(f"{cls}: size {hex(a['size'])} -> {hex(b['size'])}")
            print("\n".join(lines))
    print(f"\n{moved} moved, {added} added, {removed} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
