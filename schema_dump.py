#!/usr/bin/env python3
"""schema_dump.py - read Source 2's schema (classes, fields, offsets) straight from a binary.

No game server and no IDA: the class descriptors the schema system registers at start-up
(``SchemaClassInfoData_t`` in hl2sdk_cs2/public/schemasystem/schematypes.h) are static data in
libserver.so / server.dll, so they can be walked from the file like RTTI.

    uv run schema_dump.py dump   -gamever 14182 -module server -platform linux
    uv run schema_dump.py lookup -gamever 14182 -module server -platform linux -class CCSPlayerPawn -offset 0x980
    uv run schema_dump.py diff   -old 14181 -new 14182 -module server -platform linux [-class CBaseEntity]
    uv run schema_dump.py impact -old 14184 -new 14185 [-css /root/CounterStrikeSharp] [-plugins DIR ...] [-json]

`dump` writes schema/<gamever>/<module>.<platform>.json (gitignored, regenerated on demand).
`lookup` names the field at an offset, walking base classes (answers "what is 2432 on the pawn?").
`diff` lists fields that moved, appeared or disappeared between two builds. A field that vanished
while another appeared at the same offset with the same size is reported once, as a likely rename;
a vanished class whose size, bases and most (field, offset) pairs reappear under a new name likewise.
`impact` checks what CounterStrikeSharp (its generated SchemaMember properties and hand-written
string pairs) and each plugin .dll (property MemberRefs + ldstr "Class","m_field" pairs, read as
ECMA-335 metadata by schema_impact.py) actually uses, and exits 1 when a used field was removed or
renamed. Moves are reported but harmless: CounterStrikeSharp resolves offsets by name at runtime.

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
    if nbases and img.off(bases_ptr) is None and not (nfields and bases_ptr):
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
    unresolved = False
    for k in range(nbases):
        entry = bases_ptr + 0x10 * k
        base_desc = img.q(entry + 8) if img.off(entry) is not None else 0
        base_name = img.cstr(img.q(base_desc + 0x08)) if base_desc else None
        if not base_name:
            # Some base-class arrays live in .bss and are filled by a dynamic initializer
            # (CCSWeaponBaseVData and the other *VData classes on 14185): zero in the file. The
            # class itself is still real when its fields validated; drop only the base link.
            if not fields:
                return None
            unresolved = True
            continue
        bases.append({"name": base_name, "offset": img.i32(entry) or 0})
    info = {"name": name, "size": size, "bases": bases, "fields": fields, "va": hex(c)}
    if unresolved:
        info["bases_unresolved"] = True
    return info


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


# Bumped whenever dump_image's output changes, so a cached dump from an older reader is re-read
# instead of silently used (2: classes whose base array is filled at runtime are kept).
DUMP_FORMAT = 2


def load_or_dump(gamever, module, platform, bindir="bin"):
    path = schema_path(gamever, module, platform)
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.pop("__format__", None) == DUMP_FORMAT:
            return cached
    binary = REPO / bindir / str(gamever) / module / BINARY_NAMES[(module, platform)]
    classes = dump_image(binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"__format__": DUMP_FORMAT, **classes}, indent=1, sort_keys=True), encoding="utf-8")
    return classes


def field_offset(classes, cls, field):
    """(owner, absolute offset) of `field` in `cls` or its bases, or None."""
    chain, seen = [(cls, 0)], set()
    while chain:
        name, base = chain.pop(0)
        if name in seen or name not in classes:
            continue
        seen.add(name)
        for f in classes[name]["fields"]:
            if f["name"] == field:
                return name, base + f["offset"]
        chain += [(b["name"], base + b["offset"]) for b in classes[name]["bases"]]
    return None


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


def _field_extents(info):
    """{field: approximate size} - the gap to the next field at a higher offset, None for the last
    field. The static descriptors carry no type (m_pType is attached at runtime), so this gap is the
    only size there is; it includes padding, which is why it is only used for equality."""
    offs = sorted({f["offset"] for f in info["fields"]})
    out = {}
    for f in info["fields"]:
        nxt = next((o for o in offs if o > f["offset"]), None)
        # the last field runs to the end of the class, and that end moves whenever the class grows:
        # its size is not knowable, so it never vetoes a rename
        out[f["name"]] = nxt - f["offset"] if nxt is not None else None
    return out


def field_renames(a, b):
    """Likely renames inside one class: [(old, new, offset)] for every offset where exactly one field
    disappeared and exactly one appeared, with the same approximate size on both sides."""
    fa = {f["name"]: f["offset"] for f in a["fields"]}
    fb = {f["name"]: f["offset"] for f in b["fields"]}
    sa, sb = _field_extents(a), _field_extents(b)
    gone, came = {}, {}
    for n, o in fa.items():
        if n not in fb:
            gone.setdefault(o, []).append(n)
    for n, o in fb.items():
        if n not in fa:
            came.setdefault(o, []).append(n)
    out = []
    for off in sorted(set(gone) & set(came)):
        if len(gone[off]) == 1 and len(came[off]) == 1:
            old, new = gone[off][0], came[off][0]
            if sa[old] is None or sb[new] is None or sa[old] == sb[new]:
                out.append((old, new, off))
    return out


def class_renames(old, new):
    """{old_class: new_class} for classes that vanished while a class of the same size, the same base
    classes and mostly the same (field, offset) pairs appeared. Field-less classes are never matched:
    with nothing to compare, any two empty classes of one size would pair up."""
    gone = [n for n in old if n not in new and old[n]["fields"]]
    came = [n for n in new if n not in old and new[n]["fields"]]

    def pairs(c):
        return {(f["name"], f["offset"]) for f in c["fields"]}

    def bases(c):
        return [x["name"] for x in c["bases"]]

    scored = []
    for g in gone:
        pg = pairs(old[g])
        for c in came:
            if old[g]["size"] != new[c]["size"] or bases(old[g]) != bases(new[c]):
                continue
            pc = pairs(new[c])
            score = len(pg & pc) / max(len(pg), len(pc))
            if score >= 0.5:
                scored.append((score, g, c))
    out, used = {}, set()
    for score, g, c in sorted(scored, reverse=True):
        if g not in out and c not in used:
            out[g] = c
            used.add(c)
    return out


def diff_schemas(old, new, only=None):
    """Structured diff of two dumps. Renamed fields are reported once as a rename, never also as a
    removal plus an addition."""
    renamed_classes = class_renames(old, new)
    report = {
        "classes_removed": sorted(n for n in old if n not in new and n not in renamed_classes),
        "classes_added": sorted(n for n in new if n not in old and n not in renamed_classes.values()),
        "classes_renamed": renamed_classes,
        "classes": {},
    }
    names = [only] if only else sorted(set(old) | set(new))
    for cls in names:
        a = old.get(cls)
        b = new.get(cls) if cls not in renamed_classes else new.get(renamed_classes[cls])
        if a is None or b is None:
            continue
        renames = field_renames(a, b)
        rn_old = {r[0] for r in renames}
        rn_new = {r[1] for r in renames}
        fa = {f["name"]: f["offset"] for f in a["fields"]}
        fb = {f["name"]: f["offset"] for f in b["fields"]}
        entry = {
            "size": [a["size"], b["size"]],
            "moved": {n: [fa[n], fb[n]] for n in fa if n in fb and fa[n] != fb[n]},
            "added": {n: fb[n] for n in fb if n not in fa and n not in rn_new},
            "removed": {n: fa[n] for n in fa if n not in fb and n not in rn_old},
            "renamed": {old_n: {"to": new_n, "offset": off} for old_n, new_n, off in renames},
        }
        if cls in renamed_classes:
            entry["renamed_to"] = renamed_classes[cls]
        if any(entry[k] for k in ("moved", "added", "removed", "renamed")) or a["size"] != b["size"] \
                or cls in renamed_classes:
            report["classes"][cls] = entry
    return report


def impact(args):
    """Report used schema fields that a build removed, renamed or moved; exit 1 when one broke."""
    import schema_impact as SI

    for plugin_dir in args.plugins:
        if not Path(plugin_dir).is_dir():
            print(f"{plugin_dir}: not a directory", file=sys.stderr)
            return 2
    old = load_or_dump(args.old, args.module, args.platform, args.bindir)
    new = load_or_dump(args.new, args.module, args.platform, args.bindir)
    report = diff_schemas(old, new)
    classes, bases = SI.load_css_generated(args.css)
    known = {}
    for dump in (old, new):
        for name, info in dump.items():
            known.setdefault(name, set()).update(f["name"] for f in info["fields"])
    for props in classes.values():
        for cls, field in props.values():
            known.setdefault(cls, set()).add(field)

    groups = []
    api = {}
    for cls, props in classes.items():
        for prop, key in props.items():
            api.setdefault(key, set()).add(f"{cls}.{prop}")
    groups.append(("CounterStrikeSharp.API (generated)", "api", api))
    hand = {key: {"hand-written"} for key in SI.load_css_handwritten(args.css, known)}
    groups.append(("CounterStrikeSharp.API (hand-written)", "api", hand))
    silent, unreadable = [], []
    for plugin_dir in args.plugins:
        label = plugin_dir.rstrip("/") if len(args.plugins) > 1 else ""
        for rel, path in SI.plugin_assemblies(plugin_dir):
            name = f"{label}/{rel}" if label else str(rel)
            try:
                used = SI.scan_assembly(path, classes, bases, known)
            except (ValueError, struct.error, IndexError, UnicodeDecodeError) as exc:
                unreadable.append(f"{name}: {exc}")
                continue
            if used is None:
                continue
            if not used:
                silent.append(name)
                continue
            groups.append((name, "plugin", used))

    out = []
    for name, kind, used in groups:
        fields = []
        for cls, field in sorted(used):
            status, detail = SI.classify(old, new, report, cls, field)
            fields.append({"class": cls, "field": field, "status": status, "detail": detail,
                           "via": sorted(used[(cls, field)])})
        counts = {}
        for f in fields:
            counts[f["status"]] = counts.get(f["status"], 0) + 1
        out.append({"name": name, "kind": kind, "counts": counts, "fields": fields})
    broken_groups = [g for g in out if any(g["counts"].get(s) for s in SI.BREAKING)]
    plugins = [g for g in out if g["kind"] == "plugin"]
    summary = {
        "plugins_scanned": len(plugins) + len(silent),
        "plugins_using_schema": len(plugins),
        "plugins_broken": sum(1 for g in broken_groups if g["kind"] == "plugin"),
        "api_broken": any(g["kind"] == "api" for g in broken_groups),
    }
    for s in ("removed", "renamed", "moved"):
        summary[f"plugin_fields_{s}"] = len({(f["class"], f["field"]) for g in plugins for f in g["fields"]
                                             if f["status"] == s})
    note = ("moves are informational: CounterStrikeSharp resolves schema offsets by name at runtime; "
            "removed and renamed fields are what break plugins")
    if args.json:
        print(json.dumps({"old": args.old, "new": args.new, "module": args.module, "platform": args.platform,
                          "note": note, "summary": summary, "silent_assemblies": silent,
                          "unreadable_assemblies": unreadable, "groups": out},
                         indent=1))
        return 1 if broken_groups else 0

    print(f"schema impact {args.old} -> {args.new} ({args.module}/{args.platform})")
    print(f"note: {note}\n")
    order = {"removed": 0, "renamed": 1, "absent": 2, "inherited": 3, "added": 4, "moved": 5, "ok": 6}
    for g in out:
        counts = ", ".join(f"{g['counts'][s]} {s}" for s in sorted(g["counts"], key=order.get))
        print(f"[{g['name']}] {len(g['fields'])} fields: {counts or 'none'}")
        for f in sorted(g["fields"], key=lambda f: order[f["status"]]):
            quiet = f["status"] == "ok" or (g["kind"] == "api" and f["status"] in ("moved", "added", "inherited"))
            if quiet and not args.verbose:
                continue
            via = "" if f["via"] in (["string"], ["hand-written"]) else f"  via {', '.join(f['via'])}"
            print(f"   {f['status'].upper():8} {f['class']}::{f['field']}  ({f['detail']}){via}")
    if silent:
        print(f"\n{len(silent)} assemblies reference CounterStrikeSharp but touch no schema field")
    for line in unreadable:
        print(f"WARNING: could not read {line}")
    print(f"\nsummary: {summary['plugins_broken']} of {summary['plugins_using_schema']} schema-using plugin "
          f"assemblies broken; plugin fields: {summary['plugin_fields_removed']} removed, "
          f"{summary['plugin_fields_renamed']} likely renamed, {summary['plugin_fields_moved']} moved (harmless); "
          f"API {'BROKEN' if summary['api_broken'] else 'ok'}")
    return 1 if broken_groups else 0


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
    m = sub.add_parser("impact", help="which CounterStrikeSharp / plugin schema fields a new build breaks")
    m.add_argument("-old", required=True)
    m.add_argument("-new", required=True)
    m.add_argument("-module", default="server")
    m.add_argument("-platform", choices=("linux", "windows"), default="linux")
    m.add_argument("-bindir", default="bin")
    m.add_argument("-css", default="/root/CounterStrikeSharp", help="CounterStrikeSharp checkout (default: %(default)s)")
    m.add_argument("-plugins", action="append", default=[], help="plugins dir to scan for .dll files (repeatable)")
    m.add_argument("-json", action="store_true", help="machine-readable report on stdout")
    m.add_argument("-v", dest="verbose", action="store_true", help="list every used field, OK ones included")
    args = ap.parse_args()

    if args.cmd == "impact":
        try:
            return impact(args)
        except FileNotFoundError as exc:
            print(f"impact: {exc}", file=sys.stderr)
            return 2

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
            hit = field_offset(classes, args.cls, args.field)
            if hit is None:
                print(f"{args.field} not found in {args.cls} or its bases", file=sys.stderr)
                return 1
            owner, total = hit
            print(f"{owner}::{args.field} = {hex(total)} ({total})")
            return 0
        if args.offset is None:
            print("lookup needs -offset or -field", file=sys.stderr)
            return 2
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
    if args.cls and args.cls not in old and args.cls not in new:
        print(f"class {args.cls} not found in either build", file=sys.stderr)
        return 1
    report = diff_schemas(old, new, args.cls)
    if args.cls and args.cls not in report["classes"] and (args.cls not in old or args.cls not in new):
        print(f"{args.cls}: only in {'new' if args.cls not in old else 'old'}")
        return 0
    counts = dict.fromkeys(("moved", "added", "removed", "renamed"), 0)
    for cls, e in report["classes"].items():
        head = f"{cls}: size {hex(e['size'][0])} -> {hex(e['size'][1])}"
        if "renamed_to" in e:
            head += f"  (class likely renamed -> {e['renamed_to']})"
        rows = [(off, f"   - {n} (was {hex(off)})") for n, off in e["removed"].items()]
        rows += [(off, f"   + {n} {hex(off)}") for n, off in e["added"].items()]
        rows += [(o[1], f"   ~ {n} {hex(o[0])} -> {hex(o[1])}") for n, o in e["moved"].items()]
        rows += [(r["offset"], f"   > {n} -> {r['to']} {hex(r['offset'])} (likely renamed: same offset and size)")
                 for n, r in e["renamed"].items()]
        lines = [text for _off, text in sorted(rows)]
        for k in counts:
            counts[k] += len(e[k])
        print(head)
        if lines:
            print("\n".join(lines))
    if not args.cls:
        for g, c in sorted(report["classes_renamed"].items()):
            print(f"class {g} -> {c} (likely renamed: same size, bases and most fields)")
        for g in report["classes_removed"]:
            print(f"class {g} removed")
        for c in report["classes_added"]:
            print(f"class {c} added")
    print(f"\n{counts['moved']} moved, {counts['added']} added, {counts['removed']} removed, "
          f"{counts['renamed']} likely renamed; classes: {len(report['classes_removed'])} removed, "
          f"{len(report['classes_added'])} added, {len(report['classes_renamed'])} likely renamed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
