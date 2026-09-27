#!/usr/bin/env python3
"""schema_impact.py - which CounterStrikeSharp schema fields (and which plugins) a new build breaks.

Backs `schema_dump.py impact`; not meant to be run on its own. Three sources of "used fields":

  * the CounterStrikeSharp API: every `[SchemaMember("Class", "m_field")]` in
    managed/CounterStrikeSharp.API/Generated/Schema/Classes/*.g.cs, plus the property it sits on
    (that property map is what turns a plugin's `get_Health` back into CBaseEntity::m_iHealth);
  * hand-written API code: `"Class", "m_field"` string pairs in the API's other .cs files;
  * plugin .dll files, read as ECMA-335 metadata (no reflection, no .NET runtime): MemberRefs to
    get_/set_ accessors of CounterStrikeSharp.API.Core types, and `ldstr "Class"; ldstr "m_field"`
    pairs in method bodies (Schema.GetSchemaValue / SetSchemaValue / GetRef / GetSchemaOffset ...).

Moves are informational: CounterStrikeSharp resolves every schema offset by name at runtime, so a
field that only moved keeps working. A removal or a rename is what breaks a plugin.
"""
import re
import struct
from pathlib import Path

API_ASSEMBLY = "CounterStrikeSharp.API"
API_NAMESPACE = "CounterStrikeSharp.API.Core"


# --------------------------------------------------------------------------- CounterStrikeSharp source

_CLASS_DECL = re.compile(r"^public\s+(?:partial\s+)?class\s+(\w+)\s*(?::\s*([\w.]+))?", re.M)
_MEMBER = re.compile(r'\[SchemaMember\("([^"]+)",\s*"([^"]+)"\)\]\s*\n\s*public\s+([^\n]*)')
_PAIR = re.compile(r'"([A-Za-z_][\w:]*)"\s*,\s*"([A-Za-z_]\w*)"')


def _property_name(decl):
    """`ref Int32 Health => ref ...` / `string ResponseContext` -> the property name."""
    decl = decl.split("=>", 1)[0].split("{", 1)[0].strip()
    return re.findall(r"\w+", decl)[-1]


def load_css_generated(css_root):
    """(classes, bases): classes = {class: {property: (schema_class, field)}}, bases = {class: base}."""
    root = Path(css_root) / "managed" / "CounterStrikeSharp.API" / "Generated" / "Schema" / "Classes"
    if not root.is_dir():
        raise FileNotFoundError(f"{root}: not a CounterStrikeSharp checkout")
    classes, bases = {}, {}
    for path in sorted(root.glob("*.g.cs")):
        text = path.read_text(encoding="utf-8")
        decl = _CLASS_DECL.search(text)
        if not decl:
            continue
        cls = decl.group(1)
        if decl.group(2):
            bases[cls] = decl.group(2).rsplit(".", 1)[-1]
        props = classes.setdefault(cls, {})
        for schema_cls, field, prop in _MEMBER.findall(text):
            props[_property_name(prop)] = (schema_cls, field)
    return classes, bases


def load_css_handwritten(css_root, known):
    """(class, field) string pairs in the API's hand-written .cs files (Core/Model and friends)."""
    api = Path(css_root) / "managed" / "CounterStrikeSharp.API"
    out = set()
    for path in api.rglob("*.cs"):
        if "Generated" in path.parts or "obj" in path.parts or "bin" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
        for cls, field in _PAIR.findall(code):
            if _looks_like_schema_pair(cls, field, known):
                out.add((cls, field))
    return out


def resolve_property(classes, bases, cls, prop):
    """(schema_class, field) behind `cls.prop`, walking the generated base-class chain."""
    seen = set()
    while cls and cls not in seen:
        seen.add(cls)
        hit = classes.get(cls, {}).get(prop)
        if hit:
            return hit
        cls = bases.get(cls)
    return None


def _looks_like_schema_pair(cls, field, known):
    """known = {class: set(fields)} over both builds and the API. The class must be a schema class;
    the field must be known for it, or at least look like a member (m_ prefix)."""
    if cls not in known:
        return False
    return field in known[cls] or field.startswith("m_")


# --------------------------------------------------------------------------- ECMA-335 metadata

# Column kinds: "u2"/"u4" = fixed width, "s"/"g"/"b" = #Strings/#GUID/#Blob index, an int = simple
# index into that table, any other string = coded index (see _CODED).
_CODED = {
    "TypeDefOrRef": (2, (0x02, 0x01, 0x1B)),
    "HasConstant": (2, (0x04, 0x08, 0x17)),
    "HasCustomAttribute": (5, (0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17, 0x14, 0x11, 0x1A,
                               0x1B, 0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B)),
    "HasFieldMarshal": (1, (0x04, 0x08)),
    "HasDeclSecurity": (2, (0x02, 0x06, 0x20)),
    "MemberRefParent": (3, (0x02, 0x01, 0x1A, 0x06, 0x1B)),
    "HasSemantics": (1, (0x14, 0x17)),
    "MethodDefOrRef": (1, (0x06, 0x0A)),
    "MemberForwarded": (1, (0x04, 0x06)),
    "Implementation": (2, (0x26, 0x23, 0x27)),
    "CustomAttributeType": (3, (0x06, 0x0A)),  # tags 2 and 3; tags 0, 1, 4 are unused
    "ResolutionScope": (2, (0x00, 0x1A, 0x23, 0x01)),
    "TypeOrMethodDef": (1, (0x02, 0x06)),
}
_TABLES = {
    0x00: ("u2", "s", "g", "g", "g"),                                # Module
    0x01: ("ResolutionScope", "s", "s"),                             # TypeRef
    0x02: ("u4", "s", "s", "TypeDefOrRef", 0x04, 0x06),              # TypeDef
    0x03: (0x04,), 0x04: ("u2", "s", "b"),                           # FieldPtr, Field
    0x05: (0x06,), 0x06: ("u4", "u2", "u2", "s", "b", 0x08),         # MethodPtr, MethodDef
    0x07: (0x08,), 0x08: ("u2", "u2", "s"),                          # ParamPtr, Param
    0x09: (0x02, "TypeDefOrRef"),                                    # InterfaceImpl
    0x0A: ("MemberRefParent", "s", "b"),                             # MemberRef
    0x0B: ("u2", "HasConstant", "b"),                                # Constant (type + pad byte)
    0x0C: ("HasCustomAttribute", "CustomAttributeType", "b"),        # CustomAttribute
    0x0D: ("HasFieldMarshal", "b"), 0x0E: ("u2", "HasDeclSecurity", "b"),
    0x0F: ("u2", "u4", 0x02), 0x10: ("u4", 0x04), 0x11: ("b",),      # ClassLayout, FieldLayout, StandAloneSig
    0x12: (0x02, 0x14), 0x13: (0x14,), 0x14: ("u2", "s", "TypeDefOrRef"),  # EventMap, EventPtr, Event
    0x15: (0x02, 0x17), 0x16: (0x17,), 0x17: ("u2", "s", "b"),       # PropertyMap, PropertyPtr, Property
    0x18: ("u2", 0x06, "HasSemantics"), 0x19: (0x02, "MethodDefOrRef", "MethodDefOrRef"),
    0x1A: ("s",), 0x1B: ("b",), 0x1C: ("u2", "MemberForwarded", "s", 0x1A), 0x1D: ("u4", 0x04),
    0x1E: ("u4", "u4"), 0x1F: ("u4",),                               # EncLog, EncMap
    0x20: ("u4", "u2", "u2", "u2", "u2", "u4", "b", "s", "s"),       # Assembly
    0x21: ("u4",), 0x22: ("u4", "u4", "u4"),                         # AssemblyProcessor, AssemblyOS
    0x23: ("u2", "u2", "u2", "u2", "u4", "b", "s", "s", "b"),        # AssemblyRef
    0x24: ("u4", 0x23), 0x25: ("u4", "u4", "u4", 0x23),
    0x26: ("u4", "s", "b"), 0x27: ("u4", "u4", "s", "s", "Implementation"), 0x28: ("u4", "u4", "s", "Implementation"),
    0x29: (0x02, 0x02), 0x2A: ("u2", "u2", "TypeOrMethodDef", "s"),  # NestedClass, GenericParam
    0x2B: ("MethodDefOrRef", "b"), 0x2C: (0x2A, "TypeDefOrRef"),     # MethodSpec, GenericParamConstraint
}

# IL operand sizes for the opcodes that have one; everything else takes none. 0x45 (switch) is
# variable and handled inline.
_OPERAND1 = {0x0E: 1, 0x0F: 1, 0x10: 1, 0x11: 1, 0x12: 1, 0x13: 1, 0x1F: 1, 0x20: 4, 0x21: 8, 0x22: 4, 0x23: 8,
             0x27: 4, 0x28: 4, 0x29: 4, 0x6F: 4, 0x70: 4, 0x71: 4, 0x72: 4, 0x73: 4, 0x74: 4, 0x75: 4, 0x79: 4,
             0x7B: 4, 0x7C: 4, 0x7D: 4, 0x7E: 4, 0x7F: 4, 0x80: 4, 0x81: 4, 0x8C: 4, 0x8D: 4, 0x8F: 4, 0xA3: 4,
             0xA4: 4, 0xA5: 4, 0xC2: 4, 0xC6: 4, 0xD0: 4, 0xDD: 4, 0xDE: 1}
_OPERAND1.update({op: 1 for op in range(0x2B, 0x38)})   # short branches
_OPERAND1.update({op: 4 for op in range(0x38, 0x45)})   # long branches
_OPERAND2 = {0x06: 4, 0x07: 4, 0x09: 2, 0x0A: 2, 0x0B: 2, 0x0C: 2, 0x0D: 2, 0x0E: 2, 0x12: 1, 0x15: 4, 0x16: 4,
             0x19: 1, 0x1C: 4}


class NotDotnet(ValueError):
    pass


class Assembly:
    """The parts of a .NET assembly's metadata this tool needs: TypeRefs, MemberRefs, AssemblyRefs,
    and the ldstr sequence of every method body."""

    def __init__(self, path):
        self.path = Path(path)
        self.b = self.path.read_bytes()
        self._pe()
        self._metadata()

    # --- PE
    def _pe(self):
        b = self.b
        if b[:2] != b"MZ":
            raise NotDotnet(f"{self.path}: not a PE file")
        o, = struct.unpack_from("<I", b, 0x3C)
        if b[o:o + 4] != b"PE\0\0":
            raise NotDotnet(f"{self.path}: bad PE signature")
        nsec, = struct.unpack_from("<H", b, o + 6)
        optsize, = struct.unpack_from("<H", b, o + 20)
        opt = o + 24
        magic, = struct.unpack_from("<H", b, opt)
        dirs = opt + (96 if magic == 0x10B else 112)
        ndirs, = struct.unpack_from("<I", b, dirs - 4)
        if ndirs <= 14:
            raise NotDotnet(f"{self.path}: no CLI header")
        cli_rva, cli_size = struct.unpack_from("<II", b, dirs + 14 * 8)
        if not cli_rva:
            raise NotDotnet(f"{self.path}: native image (no CLI header)")
        self.sections = []
        for i in range(nsec):
            s = opt + optsize + i * 40
            vsize, va, rsize, rptr = struct.unpack_from("<IIII", b, s + 8)
            self.sections.append((va, max(vsize, rsize), rptr))
        cli = self.rva(cli_rva)
        self.md_rva, self.md_size = struct.unpack_from("<II", b, cli + 8)

    def rva(self, rva):
        for va, size, ptr in self.sections:
            if va <= rva < va + size:
                return ptr + rva - va
        raise ValueError(f"{self.path}: RVA {rva:#x} outside every section")

    # --- metadata root, streams, tables
    def _metadata(self):
        b = self.b
        root = self.rva(self.md_rva)
        if struct.unpack_from("<I", b, root)[0] != 0x424A5342:
            raise NotDotnet(f"{self.path}: bad metadata signature")
        vlen, = struct.unpack_from("<I", b, root + 12)
        p = root + 16 + vlen
        nstreams, = struct.unpack_from("<H", b, p + 2)
        p += 4
        self.streams = {}
        for _ in range(nstreams):
            off, size = struct.unpack_from("<II", b, p)
            end = b.index(b"\0", p + 8)
            name = b[p + 8:end].decode("ascii")
            p = (end + 4) & ~3
            self.streams[name] = (root + off, size)
        tables = self.streams.get("#~") or self.streams.get("#-")
        if tables is None:
            raise NotDotnet(f"{self.path}: no metadata table stream")
        t = tables[0]
        heap_sizes = b[t + 6]
        valid, = struct.unpack_from("<Q", b, t + 8)
        present = [i for i in range(64) if valid >> i & 1]
        if any(i not in _TABLES for i in present):
            raise NotDotnet(f"{self.path}: unknown metadata table in {present}")
        p = t + 24
        self.rows = dict.fromkeys(range(0x2D), 0)
        for i in present:
            self.rows[i], = struct.unpack_from("<I", b, p)
            p += 4
        if heap_sizes & 0x40:  # "extra data" flag some obfuscators and ENC images set
            p += 4
        widths = {"s": 4 if heap_sizes & 1 else 2, "g": 4 if heap_sizes & 2 else 2,
                  "b": 4 if heap_sizes & 4 else 2}
        self.table_at, self.layout = {}, {}
        for i in present:
            cols = [self._col_width(c, widths) for c in _TABLES[i]]
            self.layout[i] = cols
            self.table_at[i] = p
            p += sum(cols) * self.rows[i]

    def _col_width(self, col, widths):
        if col in ("u2", "u4"):
            return int(col[1])
        if isinstance(col, str) and col in widths:
            return widths[col]
        if isinstance(col, str):
            bits, targets = _CODED[col]
            return 2 if max(self.rows[x] for x in targets) < 1 << (16 - bits) else 4
        return 2 if self.rows[col] < 0x10000 else 4

    def row(self, table, index):
        """Row `index` (1-based, as tokens count) of `table`, as a tuple of raw column values."""
        cols = self.layout[table]
        p = self.table_at[table] + (index - 1) * sum(cols)
        out = []
        for w in cols:
            out.append(struct.unpack_from("<H" if w == 2 else "<I", self.b, p)[0])
            p += w
        return tuple(out)

    def string(self, index):
        start = self.streams["#Strings"][0] + index
        return self.b[start:self.b.index(b"\0", start)].decode("utf-8", "replace")

    def user_string(self, index):
        start, size = self.streams["#US"]
        p = start + index
        first = self.b[p]
        if first & 0x80 == 0:
            n, p = first, p + 1
        elif first & 0xC0 == 0x80:
            n, p = ((first & 0x3F) << 8) | self.b[p + 1], p + 2
        else:
            n = ((first & 0x1F) << 24) | (self.b[p + 1] << 16) | (self.b[p + 2] << 8) | self.b[p + 3]
            p += 4
        return self.b[p:p + n - 1 if n else p].decode("utf-16-le", "replace")  # last byte is a flag

    # --- the views the impact report uses
    def assembly_refs(self):
        return [self.string(self.row(0x23, i)[6]) for i in range(1, self.rows[0x23] + 1)]

    def type_refs(self):
        """{typeref row: (assembly or None, namespace, name)}; nested TypeRefs inherit their outer
        type's assembly and are named Outer/Inner."""
        refs = self.assembly_refs()
        out = {}

        def resolve(i, depth=0):
            if i in out:
                return out[i]
            scope, name, ns = self.row(0x01, i)
            name, ns = self.string(name), self.string(ns)
            tag, idx = scope & 3, scope >> 2
            asm = None
            if tag == 2 and 0 < idx <= len(refs):
                asm = refs[idx - 1]
            elif tag == 3 and idx and depth < 16:
                oasm, ons, oname = resolve(idx, depth + 1)
                asm, ns, name = oasm, ons, f"{oname}/{name}"
            out[i] = (asm, ns, name)
            return out[i]

        for i in range(1, self.rows[0x01] + 1):
            resolve(i)
        return out

    def member_refs(self):
        """[(assembly, namespace, type, member)] for every MemberRef whose parent is a TypeRef."""
        types = self.type_refs()
        out = []
        for i in range(1, self.rows[0x0A] + 1):
            parent, name, _sig = self.row(0x0A, i)
            if parent & 7 == 1:  # MemberRefParent tag 1 = TypeRef
                asm, ns, tname = types.get(parent >> 3, (None, "", ""))
                out.append((asm, ns, tname, self.string(name)))
        return out

    def method_strings(self):
        """Yield (method name, [ldstr literals in IL order]) for every method with a body."""
        for i in range(1, self.rows[0x06] + 1):
            rva, _impl, _flags, name, _sig, _params = self.row(0x06, i)
            if not rva:
                continue
            strings = self._ldstrs(self.rva(rva))
            if strings:
                yield self.string(name), strings

    def _ldstrs(self, body):
        b = self.b
        head = b[body]
        if head & 3 == 2:  # tiny header
            code, size = body + 1, head >> 2
        else:
            flags_size, = struct.unpack_from("<H", b, body)
            size, = struct.unpack_from("<I", b, body + 4)
            code = body + (flags_size >> 12) * 4
        p, end, out = code, code + size, []
        while p < end:
            op = b[p]
            p += 1
            if op == 0xFE:
                p += 1 + _OPERAND2.get(b[p], 0)
            elif op == 0x45:
                n, = struct.unpack_from("<I", b, p)
                p += 4 + 4 * n
            elif op == 0x72:
                tok, = struct.unpack_from("<I", b, p)
                p += 4
                if tok >> 24 == 0x70:
                    out.append(self.user_string(tok & 0xFFFFFF))
            else:
                p += _OPERAND1.get(op, 0)
        return out


def scan_assembly(path, classes, bases, known):
    """Schema fields one assembly uses: {(class, field): set(how)}. None when it is not a .NET
    assembly or never touches CounterStrikeSharp. A malformed .NET image raises (ValueError,
    struct.error, IndexError) so the caller can report it instead of calling the plugin clean."""
    try:
        asm = Assembly(path)
    except NotDotnet:
        return None  # native library shipped next to a plugin
    used = {}
    refs_api = API_ASSEMBLY in asm.assembly_refs()
    if refs_api:
        for aname, ns, tname, member in asm.member_refs():
            if aname != API_ASSEMBLY or ns != API_NAMESPACE or member[:4] not in ("get_", "set_"):
                continue
            hit = resolve_property(classes, bases, tname, member[4:])
            if hit:
                used.setdefault(hit, set()).add(f"{tname}.{member[4:]}")
    for _method, strings in asm.method_strings():
        for cls, field in zip(strings, strings[1:]):
            if _looks_like_schema_pair(cls, field, known):
                used.setdefault((cls, field), set()).add("string")
    if not refs_api and not used:
        return None
    return used


def plugin_assemblies(plugin_dir):
    """Every .dll under a plugins dir except CounterStrikeSharp's own, skipping a `disabled/` folder at
    the root the same way the plugin loader does."""
    root = Path(plugin_dir)
    for path in sorted(root.rglob("*.dll")):
        rel = path.relative_to(root)
        if rel.parts[0] == "disabled" or path.name == f"{API_ASSEMBLY}.dll":
            continue
        yield rel, path


# --------------------------------------------------------------------------- classification

def classify(old, new, report, cls, field):
    """(status, detail) for one used (class, field). status: ok, moved, removed, renamed, added
    (only in the new build), inherited (declared on a base class of the named one), absent (in
    neither build)."""
    renamed_cls = report["classes_renamed"].get(cls)
    a = old.get(cls)
    b = new.get(cls) or (new.get(renamed_cls) if renamed_cls else None)
    fa = {f["name"]: f["offset"] for f in a["fields"]} if a else {}
    fb = {f["name"]: f["offset"] for f in b["fields"]} if b else {}
    if a is None and b is None:
        return "absent", "class not in either build's static schema for this module"
    if field not in fa:
        if field in fb:
            return "added", f"new at {hex(fb[field])}"
        owner = _declared_on_base(new if b else old, renamed_cls or cls if b else cls, field)
        if owner:
            # CounterStrikeSharp's schema::GetOffset walks base classes since the fork's
            # "resolve schema fields declared on base classes" fix; older builds only searched
            # the named class and silently returned offset 0. The field itself is judged on the
            # class that declares it.
            status, detail = classify(old, new, report, owner, field)
            if status in ("ok", "moved"):
                return "inherited", (f"declared on base {owner} ({detail}); resolved through the base. In "
                                     f"SetStateChanged(entity, \"{cls}\", ...) a component class notifies the "
                                     f"entity at a component-relative offset: mark the entity's pointer field instead")
            return status, f"declared on base {owner}: {detail}"
        return "absent", "field in neither build"
    if b is None:
        return "removed", f"class {cls} removed (was {hex(fa[field])})"
    entry = report["classes"].get(cls, {})
    if field in entry.get("renamed", {}):
        r = entry["renamed"][field]
        target = f"{renamed_cls}::{r['to']}" if renamed_cls else r["to"]
        return "renamed", f"likely renamed to {target} at {hex(r['offset'])}"
    if field not in fb:
        return "removed", f"was {hex(fa[field])}"
    if renamed_cls:
        return "renamed", f"class likely renamed to {renamed_cls}; field at {hex(fb[field])}"
    if fa[field] != fb[field]:
        return "moved", f"{hex(fa[field])} -> {hex(fb[field])}"
    return "ok", hex(fb[field])


def _declared_on_base(dump, cls, field):
    seen, todo = set(), [b["name"] for b in dump.get(cls, {}).get("bases", [])]
    while todo:
        c = todo.pop(0)
        if c in seen or c not in dump:
            continue
        seen.add(c)
        if any(f["name"] == field for f in dump[c]["fields"]):
            return c
        todo += [b["name"] for b in dump[c]["bases"]]
    return None


BREAKING = ("removed", "renamed")
