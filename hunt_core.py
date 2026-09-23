"""hunt_core.py - backend-agnostic baseline facts and automatic hunting.

Everything here talks to a disassembler through the small Backend protocol
below, so the same facts format and the same strategies run inside IDA
(ida_backend.py), inside Ghidra via PyGhidra (ghidra_backend.py) or anywhere
else that can answer these questions about a binary. Nothing in this file
imports a disassembler.

Backend protocol (all addresses are ints):
    exec_regions() -> [(start, bytes)]            executable segments
    data_regions() -> [(start, bytes)]            non-executable segments
    is_code(ea) -> bool
    qword(ea) -> int | None
    read(ea, n) -> bytes | None
    get_func(ea) -> (start, end) | None          function containing ea
    next_func(ea) -> start | None                first function starting after ea
    func_items(start) -> [ea]                    instruction heads in order
    insn(ea) -> Insn | None                      decoded instruction, see Insn
    string_at(ea) -> str | None                  C string literal at ea, if any
    data_refs_from(ea) -> [ea]                   data references from an instruction
    code_refs_to(ea) -> [from_ea]                call/jump sites targeting ea
    xrefs_to(ea) -> [from_ea]                    any reference to ea (strings)
    imagebase() -> int
    input_path() -> str                          path of the loaded binary
    write_artifact(out_dir, symbol, platform, data: dict) -> path   (optional; default render)

Insn: an object with .ea .size .mnem .raw (bytes) and .ops, a list of Operand
with .kind in {"reg","imm","mem","displ","near","far","other"}, .offb (byte
offset of the operand's encoded value, -1 if none), .value (imm), .addr
(displacement / target), .rip (True for RIP-relative memory).
"""
import difflib
import struct
import json
import os
import re

MASK_KINDS = {"displ", "mem", "near", "far", "imm"}
HEAD_BYTES = 48
MNEM_COUNT = 40
MIN_SCORE = 0.55
MAX_SIG_BYTES = 128
MIN_SIG_BYTES = 24
GENERIC_STRINGS = {"%s", "%d", "true", "false", "undefined", "count", "slot%d"}


# ----------------------------------------------------------------------------- small helpers

def to_int(value):
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text, 0)


def parse_yaml(path):
    """Flat key: value reader for artifact files (no PyYAML inside IDA/Ghidra).

    A long signature is folded onto indented continuation lines; those belong to the value
    above. Reading only the first line cut 487 of 14181's signatures short - usually still
    unique, but not ILoopModeFactory_Shutdown's, which then matched twice."""
    data, last = {}, None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            if line.startswith((" ", "\t")):
                # "  0: '0x...'" is a nested mapping (vtable_entries), not a folded value
                if last is not None and not re.match(r"\s+[^\s:]+:(\s|$)", line):
                    data[last] = f"{data[last]} {line.strip()}".strip()
                continue
            if ":" in line and not line.startswith((" ", "\t")):
                key, _, value = line.partition(":")
                last = key.strip()
                data[last] = value.strip()
    return {key: value.strip("'\"") for key, value in data.items()}


def category_of(rec):
    if "patch_name" in rec:
        return "patch"
    if "gv_name" in rec:
        return "gv"
    if "struct_name" in rec:
        return "structmember"
    if "vtable_class" in rec and "func_va" not in rec:
        return "vtable"
    if "vfunc_index" in rec:
        return "vfunc"
    return "func"


def version_key(name):
    m = re.match(r"^(\d+)([a-z]*)$", name)
    return (int(m.group(1)), m.group(2)) if m else (0, name)


def token_match(a, b):
    """Fraction of compared positions that agree, '??' matching anything."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    ok = sum(1 for x, y in zip(a[:n], b[:n]) if x == "??" or y == "??" or x == y)
    return ok / n


def render_yaml(data):
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        elif key.endswith("_sig"):
            lines.append(f'{key}: "{value}"')
        elif isinstance(value, str) and value.startswith("0x"):
            lines.append(f"{key}: '{value}'")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def rtti_class(name):
    return name[: -len("_vtable")] if name and name.endswith("_vtable") else name


# ----------------------------------------------------------------------------- scanning

class Scan:
    """Wildcard pattern search over executable regions, pure Python."""

    def __init__(self, regions):
        self.regions = list(regions)

    @staticmethod
    def compile_pattern(sig):
        parts = str(sig).split()
        if not parts or all("?" in p for p in parts):
            raise ValueError(f"unusable pattern: {sig!r}")
        return re.compile(b"".join(b"." if "?" in p else re.escape(bytes([int(p, 16)])) for p in parts), re.DOTALL)

    def matches(self, sig, limit=None):
        rx = self.compile_pattern(sig)
        out = []
        for base, blob in self.regions:
            pos = rx.search(blob)
            while pos:
                out.append(base + pos.start())
                if limit is not None and len(out) >= limit:
                    return out
                pos = rx.search(blob, pos.start() + 1)
        return out


def vcall_disp_variants(sig):
    """The pattern with its leading call's displacement wildcarded, same size and (for a
    disp8 that may have outgrown a byte) disp32: FF 50 xx / FF 90 xx xx xx xx."""
    tokens = str(sig).split()
    if len(tokens) < 3 or tokens[0] != "FF" or "?" in tokens[1]:
        return []
    modrm = int(tokens[1], 16)
    mod, reg, rm = modrm >> 6, (modrm >> 3) & 7, modrm & 7
    if reg != 2 or mod not in (1, 2):
        return []
    head = 2 + (1 if rm == 4 else 0)
    size = 1 if mod == 1 else 4
    rest = tokens[head + size:]
    out = [" ".join(tokens[:head] + ["??"] * size + rest)]
    if mod == 1:
        wide = f"{(2 << 6) | (reg << 3) | rm:02X}"
        out.append(" ".join([tokens[0], wide] + tokens[2:head] + ["??"] * 4 + rest))
    return out


def find_qword_holders(value, regions):
    needle = int(value).to_bytes(8, "little", signed=False)
    hits = []
    for base, blob in regions:
        pos = blob.find(needle)
        while pos != -1:
            hits.append(base + pos)
            pos = blob.find(needle, pos + 1)
    return hits


def _is_pe(backend):
    path = (backend.input_path() or "").lower()
    return path.endswith((".dll", ".exe"))


def msvc_rtti_vtables(backend, class_name, regions):
    """[(address_point, offset)] for an MSVC x64 binary, primary (offset 0) first.

    TypeDescriptor = {pVFTable, spare, ".?AV<name>@@"}; a Complete Object Locator is
    {signature=1, offset, cdOffset, TypeDescriptor RVA, ClassHierarchy RVA, self RVA}
    and the qword right before a vtable's first slot points at its COL. `offset` is the
    subobject's place in the complete object, the analogue of Itanium's offset-to-top.
    """
    imagebase = backend.imagebase()
    out = []
    for prefix in (b".?AV", b".?AU"):
        name = prefix + class_name.encode() + b"@@\x00"
        for base, blob in regions:
            pos = blob.find(name)
            while pos != -1:
                td_rva = base + pos - 0x10 - imagebase
                needle = struct.pack("<I", td_rva & 0xFFFFFFFF)
                for cbase, cblob in regions:
                    hit = cblob.find(needle)
                    while hit != -1:
                        col_off = hit - 12
                        if col_off >= 0 and struct.unpack_from("<I", cblob, col_off)[0] == 1:
                            col = cbase + col_off
                            self_rva = struct.unpack_from("<I", cblob, col_off + 20)[0] if col_off + 24 <= len(cblob) else None
                            if self_rva in (None, col - imagebase):
                                offset = struct.unpack_from("<I", cblob, col_off + 4)[0]
                                for holder in find_qword_holders(col, regions):
                                    address_point = holder + 8
                                    first = backend.qword(address_point)
                                    if first and backend.is_code(first):
                                        out.append((address_point, offset))
                        hit = cblob.find(needle, hit + 1)
                pos = blob.find(name, pos + 1)
    out = sorted(set(out), key=lambda item: (item[1] != 0, item[0]))
    return out


def rtti_vtables(backend, class_name, regions=None):
    """[(address_point, offset_to_top)] via typeinfo-name -> typeinfo -> vtable, primary first."""
    regions = regions if regions is not None else backend.data_regions()
    if _is_pe(backend):
        return msvc_rtti_vtables(backend, class_name, regions)
    mangled = f"{len(class_name)}{class_name}".encode()
    name_eas = []
    for base, blob in regions:
        pos = blob.find(b"\x00" + mangled + b"\x00")
        while pos != -1:
            name_eas.append(base + pos + 1)
            pos = blob.find(b"\x00" + mangled + b"\x00", pos + 1)
    out = []
    for name_ea in name_eas:
        for holder in find_qword_holders(name_ea, regions):
            typeinfo = holder - 8
            for vt_holder in find_qword_holders(typeinfo, regions):
                address_point = vt_holder + 8
                first = backend.qword(address_point)
                if not first or not backend.is_code(first):
                    continue
                out.append((address_point, backend.qword(vt_holder - 8) or 0))
    out.sort(key=lambda item: (item[1] != 0, item[0]))
    return out


# ----------------------------------------------------------------------------- instruction views

def masked_instruction(backend, ea, pin_low_bytes=0):
    """(masked_tokens, insn) with relocatable operands wildcarded from their first byte."""
    insn = backend.insn(ea)
    if insn is None:
        raise ValueError(f"cannot decode the instruction at {hex(ea)}")
    masked = [f"{b:02X}" for b in insn.raw]
    for op in insn.ops:
        if op.kind in MASK_KINDS and op.offb not in (None, -1) and op.offb < insn.size:
            start = op.offb
            if pin_low_bytes and insn.size - op.offb == 4:
                start = op.offb + pin_low_bytes
            for i in range(start, insn.size):
                masked[i] = "??"
            break
    return masked, insn


def insn_shape(backend, ea):
    """Register-agnostic description: mnemonic | operand kinds | small immediates."""
    insn = backend.insn(ea)
    if insn is None:
        return None
    kinds, imms = [], []
    for op in insn.ops:
        kinds.append(op.kind)
        if op.kind == "imm":
            value = int(op.value or 0) & 0xFFFFFFFFFFFFFFFF
            imms.append(str(value) if value < 0x80000000 else "big")
    return f"{insn.mnem}|{','.join(kinds)}|{','.join(imms)}"


def masked_head(backend, ea, limit=HEAD_BYTES, func_end=None):
    tokens, cur = [], ea
    while len(tokens) < limit:
        if func_end is not None and cur >= func_end:
            break
        try:
            masked, insn = masked_instruction(backend, cur)
        except ValueError:
            break
        tokens.extend(masked)
        cur += insn.size
    return tokens[:limit]


def grow_signature(backend, scan, ea, end_ea, pin_low_bytes=0, pin_first=False, max_bytes=None):
    tokens, cur = [], ea
    while end_ea is None or cur < end_ea:
        try:
            masked, insn = masked_instruction(backend, cur, pin_low_bytes=pin_low_bytes)
        except ValueError:
            break
        if end_ea is not None and cur + insn.size > end_ea:
            break
        if pin_first and cur == ea:
            masked = [f"{b:02X}" for b in insn.raw]
        tokens.extend(masked)
        cur += insn.size
        if len(scan.matches(" ".join(tokens), limit=2)) == 1:
            return " ".join(tokens)
        if max_bytes is not None and len(tokens) >= max_bytes:
            break
    return None


def signature_ex(backend, scan, func_ea, log=None):
    """(sig, crossed_boundary, pinned) with the pipeline's fallback ladder."""
    func = backend.get_func(func_ea)
    if not func:
        raise ValueError(f"no function at {hex(func_ea)}")
    start, end = func
    sig = grow_signature(backend, scan, func_ea, end)
    if sig:
        return sig, False, False
    sig = grow_signature(backend, scan, func_ea, None, max_bytes=max(MAX_SIG_BYTES, 4 * MIN_SIG_BYTES))
    if sig:
        return sig, True, False
    sig = grow_signature(backend, scan, func_ea, end, pin_low_bytes=3)
    if sig:
        if log:
            log(f"[hunt] {hex(func_ea)}: only unique with displacement bytes pinned - fragile across builds")
        return sig, False, True
    raise ValueError(f"No unique signature for {hex(func_ea)} within its function bounds")


def site_signature(backend, scan, ea, pin_first=True, allow_across_function_boundary=True):
    """(sig, crossed) starting AT ea, first instruction pinned when asked."""
    func = backend.get_func(ea)
    end = func[1] if func else None
    tokens, cur, crossed = [], ea, False
    while True:
        if end is not None and cur >= end:
            if not allow_across_function_boundary:
                break
            crossed = True
        try:
            masked, insn = masked_instruction(backend, cur)
        except ValueError:
            break
        if pin_first and cur == ea:
            masked = [f"{b:02X}" for b in insn.raw]
        tokens.extend(masked)
        cur += insn.size
        if len(tokens) > MAX_SIG_BYTES * 2:
            break
        if len(scan.matches(" ".join(tokens), limit=2)) == 1:
            return " ".join(tokens), crossed
    raise ValueError(f"No unique signature starting at {hex(ea)}")


# ----------------------------------------------------------------------------- facts

class FactsBuilder:
    def __init__(self, backend):
        self.b = backend
        self._calls = {}

    def mnemonics(self, start, end, limit=MNEM_COUNT):
        out = []
        for ea in self.b.func_items(start):
            if ea >= end or len(out) >= limit:
                break
            insn = self.b.insn(ea)
            if insn is None:
                break
            out.append(insn.mnem)
        return out

    def direct_calls(self, start):
        if start in self._calls:
            return self._calls[start]
        func = self.b.get_func(start)
        out = []
        if func:
            f_start, f_end = func
            for ea in self.b.func_items(f_start):
                insn = self.b.insn(ea)
                if insn is None or insn.mnem not in ("call", "jmp"):
                    continue
                target = next((op.addr for op in insn.ops if op.kind in ("near", "far") and op.addr), None)
                if not target:
                    continue
                if insn.mnem == "jmp":
                    if f_start <= target < f_end:
                        continue
                    tf = self.b.get_func(target)
                    if not tf or tf[0] != target:
                        continue
                out.append((ea, target))
        self._calls[start] = out
        return out

    def vcalls(self, start, limit=8):
        out = []
        for ea in self.b.func_items(start):
            insn = self.b.insn(ea)
            if insn and insn.mnem == "call":
                op = insn.ops[0] if insn.ops else None
                if op is not None and op.kind == "displ" and op.addr is not None:
                    out.append(int(op.addr))
                    if len(out) >= limit:
                        break
        return out

    def consts(self, start, limit=64):
        """Struct offsets and immediates the function uses - its layout fingerprint.

        Survives a rebuild that moves every call and RIP target, and tells apart two
        functions that merely look alike. Small values are left out: stack slots and
        loop counters would make every function resemble every other.
        """
        out = set()
        for ea in self.b.func_items(start):
            insn = self.b.insn(ea)
            if insn is None or insn.mnem in ("call", "jmp") or insn.mnem.startswith("j"):
                continue
            for op in insn.ops:
                if op.kind == "displ" and op.addr is not None:
                    value = int(op.addr) & 0xFFFFFFFF
                    if 0x80 <= value <= 0x40000:
                        out.add(value)
                elif op.kind == "imm" and op.value is not None:
                    value = int(op.value) & 0xFFFFFFFFFFFFFFFF
                    if 0x10 <= value <= 0x40000:
                        out.add(value)
        return sorted(out)[:limit]

    def strings_of(self, start):
        out = set()
        for ea in self.b.func_items(start):
            for ref in self.b.data_refs_from(ea):
                text = self.b.string_at(ref)
                if text and len(text) >= 6:
                    out.add(text[:160])
        return sorted(out)

    def callers_of(self, start, va_to_symbol):
        out = []
        for xref in self.b.code_refs_to(start):
            caller = self.b.get_func(xref)
            if not caller:
                continue
            calls = self.direct_calls(caller[0])
            ordinal = next((i for i, (site, _) in enumerate(calls) if site == xref), None)
            out.append({"va": hex(caller[0]), "name": va_to_symbol.get(caller[0]), "ordinal": ordinal, "site": hex(xref), "ncalls": len(calls)})
        return out[:24]

    def function_facts(self, ea, va_to_symbol):
        func = self.b.get_func(ea)
        if not func:
            return {"va": hex(ea), "size": 0, "no_function": True}
        start, end = func
        calls = self.direct_calls(start)
        return {
            "va": hex(start),
            "size": end - start,
            "head": masked_head(self.b, start, func_end=end),
            "mnem": self.mnemonics(start, end),
            "callees": [{"va": hex(t), "name": va_to_symbol.get(t),
                         "head": None if va_to_symbol.get(t) else masked_head(self.b, t, limit=24)} for _, t in calls][:40],
            "callers": self.callers_of(start, va_to_symbol),
            "strings": self.strings_of(start)[:40],
            "vcalls": self.vcalls(start),
            "consts": self.consts(start),
        }

    def context_shapes(self, start, site_ea, before=3, after=3):
        items = self.b.func_items(start) if start is not None else [site_ea]
        try:
            i = items.index(site_ea)
        except ValueError:
            return []
        window = items[max(0, i - before): i] + items[i + 1: i + 1 + after]
        return [insn_shape(self.b, ea) for ea in window]

    def thunk_target(self, start, va_to_symbol):
        func = self.b.get_func(start)
        if not func or func[1] - func[0] > 32:
            return None
        items = self.b.func_items(func[0])
        if not items:
            return None
        insn = self.b.insn(items[-1])
        if insn is None or insn.mnem != "jmp":
            return None
        target = next((op.addr for op in insn.ops if op.kind in ("near", "far") and op.addr), None)
        tf = self.b.get_func(target) if target else None
        if not tf or tf[0] != target:
            return None
        return self.function_facts(target, va_to_symbol)

    def site_facts(self, site_ea, va_to_symbol):
        func = self.b.get_func(site_ea)
        ordinal = sum(1 for ea in self.b.func_items(func[0]) if ea < site_ea) if func else None
        try:
            masked, insn = masked_instruction(self.b, site_ea)
            raw = insn.raw
        except ValueError:
            masked, raw = [], b""
        owner = self.function_facts(func[0], va_to_symbol) if func else None
        if owner is not None:
            thunk = self.thunk_target(func[0], va_to_symbol)
            if thunk:
                owner["thunk_target"] = thunk
        ins = self.b.insn(site_ea)
        return {
            "site_va": hex(site_ea),
            "site_head": masked,
            "site_raw": [f"{b:02X}" for b in raw],
            "site_mnem": ins.mnem if ins else None,
            "site_shape": insn_shape(self.b, site_ea),
            "site_context": self.context_shapes(func[0] if func else None, site_ea),
            "site_ordinal": ordinal,
            "owner": owner,
        }


def extract_facts(backend, artifact_dir, platform, gamever, module, log=print):
    """Facts JSON (as a dict) for every artifact in artifact_dir on the loaded BASELINE binary."""
    scan = Scan(backend.exec_regions())
    fb = FactsBuilder(backend)
    records = {}
    for name in sorted(os.listdir(artifact_dir)):
        if name.endswith(f".{platform}.yaml"):
            records[name[: -len(f".{platform}.yaml")]] = parse_yaml(os.path.join(artifact_dir, name))
    va_to_symbol = {}
    for symbol, rec in records.items():
        va = to_int(rec.get("func_va"))
        if va is not None and category_of(rec) in ("func", "vfunc"):
            va_to_symbol.setdefault(va, symbol)
    out = {"gamever": gamever, "module": module, "platform": platform, "imagebase": hex(backend.imagebase()), "symbols": {}, "vtables": {}}
    vtable_classes = set()
    for symbol, rec in records.items():
        category = category_of(rec)
        entry = {"category": category}
        try:
            if category in ("func", "vfunc"):
                va = to_int(rec.get("func_va"))
                if va is not None:
                    entry.update(fb.function_facts(va, va_to_symbol))
                if category == "vfunc":
                    entry["vtable_name"] = rec.get("vtable_name")
                    entry["vfunc_index"] = to_int(rec.get("vfunc_index"))
                    if rec.get("vtable_name"):
                        vtable_classes.add(rec["vtable_name"])
            elif category == "structmember":
                entry.update({"struct_name": rec.get("struct_name"), "member_name": rec.get("member_name"), "offset": rec.get("offset"), "size": to_int(rec.get("size"))})
                hits = scan.matches(rec["offset_sig"], limit=2) if rec.get("offset_sig") else []
                if len(hits) == 1:
                    entry.update(fb.site_facts(hits[0], va_to_symbol))
                else:
                    entry["site_error"] = f"offset_sig hits={len(hits)}"
            elif category == "gv":
                entry["gv_va"] = rec.get("gv_va")
                site = to_int(rec.get("gv_sig_va"))
                if site is None and rec.get("gv_sig"):
                    hits = scan.matches(rec["gv_sig"], limit=2)
                    site = hits[0] if len(hits) == 1 else None
                if site is not None:
                    entry.update(fb.site_facts(site, va_to_symbol))
                else:
                    entry["site_error"] = "gv site not found"
            elif category == "patch":
                entry["patch_bytes"] = rec.get("patch_bytes")
                hits = scan.matches(rec["patch_sig"], limit=2) if rec.get("patch_sig") else []
                if len(hits) == 1:
                    entry.update(fb.site_facts(hits[0], va_to_symbol))
                else:
                    entry["site_error"] = f"patch_sig hits={len(hits)}"
            elif category == "vtable":
                entry["vtable_class"] = rec.get("vtable_class")
                if rec.get("vtable_class"):
                    vtable_classes.add(rec["vtable_class"])
        except Exception as error:
            entry["error"] = str(error)
        out["symbols"][symbol] = entry
    regions = backend.data_regions()
    for class_name in sorted(vtable_classes):
        try:
            tables = [ap for ap, ott in rtti_vtables(backend, rtti_class(class_name), regions) if ott == 0]
            if len(tables) != 1:
                out["vtables"][class_name] = {"error": f"{len(tables)} primary vtables"}
                continue
            ap = tables[0]
            slots = []
            for index in range(1024):
                fn = backend.qword(ap + 8 * index)
                if not fn or not backend.is_code(fn):
                    break
                slots.append([hex(fn), masked_head(backend, fn, limit=16), va_to_symbol.get(fn)])
            out["vtables"][class_name] = {"address_point": hex(ap), "slots": slots}
        except Exception as error:
            out["vtables"][class_name] = {"error": str(error)}
    log(f"[facts] {len(out['symbols'])} symbols, {len(out['vtables'])} vtables")
    return out


def facts_path(repo, gamever, module, platform):
    return os.path.join(repo, "baseline_facts", gamever, f"{module}.{platform}.json")


def load_baseline_facts(repo, gamever, module, platform):
    root = os.path.join(repo, "baseline_facts")
    if not os.path.isdir(root):
        return None, None
    for version in sorted((d for d in os.listdir(root) if version_key(d) < version_key(gamever)), key=version_key, reverse=True):
        path = os.path.join(root, version, f"{module}.{platform}.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                return version, json.load(handle)
    return None, None


# ----------------------------------------------------------------------------- similarity

def similarity(base, live):
    parts, weights = [], []
    if base.get("head") and live.get("head"):
        parts.append(token_match(base["head"], live["head"])); weights.append(3)
    if base.get("mnem") and live.get("mnem"):
        parts.append(difflib.SequenceMatcher(None, base["mnem"], live["mnem"]).ratio()); weights.append(3)
    bs, ls = base.get("size") or 0, live.get("size") or 0
    if bs and ls:
        ratio = min(bs, ls) / max(bs, ls)
        parts.append(ratio if ratio > 0.4 else 0.0); weights.append(1)
    if base.get("strings"):
        b = set(base["strings"]); l = set(live.get("strings") or [])
        parts.append(len(b & l) / len(b)); weights.append(2)
    if base.get("vcalls") and live.get("vcalls"):
        parts.append(difflib.SequenceMatcher(None, base["vcalls"], live["vcalls"]).ratio()); weights.append(1)
    if not parts:
        return 0.0
    return sum(p * w for p, w in zip(parts, weights)) / sum(weights)


# ----------------------------------------------------------------------------- emit (generic)

def emit_artifact(backend, scan, symbol, rule, out_dir, platform, log=None):
    """Write one artifact from an explicit-address rule using only Backend primitives.

    IDA callers may prefer ida_sig_maker.emit_symbol (same schema); this is the
    path Ghidra and any other backend use.
    """
    kind = rule.get("kind", "func")
    base = backend.imagebase()
    data = {}
    if kind == "func":
        func = backend.get_func(to_int(rule["ea"]))
        if not func:
            raise ValueError(f"{symbol}: no function at {rule['ea']}")
        start, end = func
        sig, crossed, _ = signature_ex(backend, scan, start, log=log)
        data = {"func_name": symbol, "func_va": hex(start), "func_rva": hex(start - base), "func_size": hex(end - start), "func_sig": sig}
        if crossed:
            data["func_sig_allow_across_function_boundary"] = True
    elif kind == "vfunc":
        class_name = rtti_class(rule["class"])
        tables = [to_int(rule["address_point"])] if rule.get("address_point") else \
            [ap for ap, ott in rtti_vtables(backend, class_name) if ott == 0]
        if len(tables) != 1:
            raise ValueError(f"{symbol}: {len(tables)} primary vtables for {class_name}")
        index = int(rule["index"])
        fn = backend.qword(tables[0] + 8 * index)
        if not fn or not backend.is_code(fn):
            raise ValueError(f"{symbol}: slot {index} holds no code")
        func = backend.get_func(fn) or (fn, fn)
        data = {"func_name": symbol, "func_va": hex(fn), "func_rva": hex(fn - base), "func_size": hex(func[1] - func[0])}
        try:
            sig, crossed, _ = signature_ex(backend, scan, fn, log=log)
            data["func_sig"] = sig
            if crossed:
                data["func_sig_allow_across_function_boundary"] = True
        except ValueError as error:
            if log:
                log(f"[hunt] {symbol}: slot-only artifact, {error}")
        data.update({"vtable_name": rule.get("vtable_name") or rule["class"], "vfunc_offset": hex(index * 8), "vfunc_index": index})
    elif kind == "structmember":
        ea = to_int(rule["ea"])
        insn = backend.insn(ea)
        if insn is None:
            raise ValueError(f"{symbol}: cannot decode {hex(ea)}")
        offset = None
        for op in insn.ops:
            if op.kind == "displ" and op.addr is not None:
                offset = int(op.addr) & 0xFFFFFFFF
                offset = offset - 0x100000000 if offset >= 0x80000000 else offset
                break
        if offset is None and insn.mnem in ("add", "sub", "lea"):
            for op in insn.ops:
                if op.kind == "imm" and 0 < int(op.value or 0) < 0x10000:
                    offset = int(op.value) * (-1 if insn.mnem == "sub" else 1)
                    break
        if offset is None:
            raise ValueError(f"{symbol}: {hex(ea)} carries no member offset")
        sig, crossed = site_signature(backend, scan, ea, pin_first=True)
        data = {"struct_name": rule["struct_name"], "member_name": rule["member_name"], "offset": hex(offset), "size": int(rule.get("size") or 4), "offset_sig": sig}
        if crossed:
            data["offset_sig_allow_across_function_boundary"] = True
    elif kind == "gv":
        ea = to_int(rule["ea"])
        insn = backend.insn(ea)
        rip = next((op for op in (insn.ops if insn else []) if op.rip), None)
        if rip is None:
            raise ValueError(f"{symbol}: {hex(ea)} has no RIP-relative operand")
        sig, _ = site_signature(backend, scan, ea, pin_first=False, allow_across_function_boundary=False)
        data = {"gv_name": symbol, "gv_va": hex(rip.addr), "gv_rva": hex(rip.addr - base), "gv_sig": sig, "gv_sig_va": hex(ea),
                "gv_inst_offset": 0, "gv_inst_length": insn.size, "gv_inst_disp": int(rip.offb)}
    elif kind == "patch":
        ea = to_int(rule["ea"])
        if not rule.get("patch_bytes"):
            raise ValueError(f"{symbol}: patch rules need patch_bytes")
        sig, _ = site_signature(backend, scan, ea, pin_first=False, allow_across_function_boundary=False)
        data = {"patch_name": symbol, "patch_va": hex(ea), "patch_rva": hex(ea - base), "patch_sig": sig, "patch_bytes": rule["patch_bytes"]}
    else:
        raise ValueError(f"{symbol}: unknown kind {kind!r}")
    writer = getattr(backend, "write_artifact", None)
    if writer:
        return writer(out_dir, symbol, platform, data)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{symbol}.{platform}.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_yaml(data))
    return path


# ----------------------------------------------------------------------------- hunter

class Hunter:
    def __init__(self, backend, gamever, module, platform, facts, out_dir, emit=None, dry_run=False, min_score=MIN_SCORE, log=print,
                 scan=None, sister_facts=None):
        self.b = backend
        self.gamever, self.module, self.platform = gamever, module, platform
        self.facts = facts
        self.out_dir = out_dir
        self.dry_run = dry_run
        self.min_score = min_score
        self.log = log
        # a caller hunting one task at a time (pipeline_hunt) passes its cached scan
        self.scan = scan or Scan(backend.exec_regions())
        self.data_regions = backend.data_regions()
        self.fb = FactsBuilder(backend)
        self._emit = emit or (lambda symbol, rule: emit_artifact(backend, self.scan, symbol, rule, out_dir, platform, log=log))
        self.resolved, self.resolved_va = {}, {}
        self._vt_cache, self._live_cache, self._string_cache = {}, {}, {}
        # the same build's other platform (facts of its artifacts): what a symbol with no
        # baseline on this platform can be transferred from, by compiler-neutral evidence
        self.sister = sister_facts
        # where this build's own <Class>_vtable.<platform>.yaml may already sit: the answer
        # when RTTI cannot name the class (templates such as CLoopModeFactory<CLoopModeGame>)
        self.vtable_artifact_dirs = [out_dir]
        self.baseline_artifact_dir, self.existing_dirs = None, ()
        self.report = {"solved": [], "unresolved": [], "changed": [], "skipped": []}
        if os.path.isdir(out_dir):
            for name in os.listdir(out_dir):
                if name.endswith(f".{platform}.yaml"):
                    rec = parse_yaml(os.path.join(out_dir, name))
                    va = to_int(rec.get("func_va"))
                    if va is not None:
                        symbol = name[: -len(f".{platform}.yaml")]
                        self.resolved[symbol] = va
                        self.resolved_va.setdefault(va, symbol)

    # -- live views ---------------------------------------------------------------
    def live_facts(self, ea):
        func = self.b.get_func(ea)
        if not func:
            return None
        if func[0] not in self._live_cache:
            self._live_cache[func[0]] = self.fb.function_facts(func[0], self.resolved_va)
        return self._live_cache[func[0]]

    def score(self, base, ea):
        live = self.live_facts(ea)
        return similarity(base, live) if live else 0.0

    def func_start(self, ea):
        func = self.b.get_func(ea)
        return func[0] if func else None

    # -- strategies -----------------------------------------------------------------
    def s_reloc(self, symbol, base, artifact):
        sig = artifact.get("func_sig")
        if not sig:
            return []
        hits = self.scan.matches(sig, limit=2)
        return [(hits[0], "reloc")] if len(hits) == 1 else []

    def s_headreloc(self, symbol, base, artifact):
        head = base.get("head") or []
        if len(head) < 12:
            return []
        for n in range(12, len(head) + 1, 4):
            hits = self.scan.matches(" ".join(head[:n]), limit=2)
            if len(hits) == 1:
                return [(hits[0], f"head-reloc {n}B")]
            if not hits:
                return []
        return []

    def vtable_live(self, class_name):
        if class_name in self._vt_cache:
            return self._vt_cache[class_name]
        # this build's own vtable artifact first: its task already resolved and validated the
        # table, where RTTI can offer another one (IGameSystem on windows 14182) or none (templates)
        from_artifact = self.vtable_from_artifact(class_name)
        tables = [from_artifact] if from_artifact is not None else \
            [ap for ap, ott in rtti_vtables(self.b, rtti_class(class_name), self.data_regions) if ott == 0]
        slots = []
        if len(tables) == 1:
            for index in range(1024):
                fn = self.b.qword(tables[0] + 8 * index)
                if not fn or not self.b.is_code(fn):
                    break
                slots.append(fn)
        self._vt_cache[class_name] = (tables[0] if len(tables) == 1 else None, slots)
        return self._vt_cache[class_name]

    def vtable_from_artifact(self, class_name):
        """vtable_va of this build's <Class>_vtable artifact, if its slot 0 holds code."""
        name = class_name if class_name.endswith("_vtable") else f"{class_name}_vtable"
        for directory in self.vtable_artifact_dirs:
            path = os.path.join(directory, f"{name}.{self.platform}.yaml")
            if os.path.isfile(path):
                va = to_int(parse_yaml(path).get("vtable_va"))
                first = self.b.qword(va) if va is not None else None
                if first and self.b.is_code(first):
                    return va
        return None

    def measure_shift(self, class_name, index):
        """Shift that aligns the baseline vtable neighbourhood onto the live one.

        Only DISCRIMINATIVE neighbours count: a head that several slots of the
        baseline vtable share (empty stubs, `xor eax,eax; ret`) agrees with any
        shift and says nothing. Ties go to the smallest |shift|, since the usual
        answer is "nothing moved".
        """
        base_slots = ((self.facts.get("vtables") or {}).get(class_name) or {}).get("slots") or []
        ap, live_slots = self.vtable_live(class_name)
        if ap is None or not base_slots or not live_slots or index is None:
            return None, "vtable not resolvable"
        counts = {}
        for _, head, _ in base_slots:
            counts[" ".join(head)] = counts.get(" ".join(head), 0) + 1
        window = [i for i in range(max(0, index - 8), min(len(base_slots), index + 9))
                  if counts[" ".join(base_slots[i][1])] == 1 and len(base_slots[i][1]) >= 8]
        if len(window) < 3:
            return None, f"too few discriminative neighbours ({len(window)})"
        live_heads = {}
        best = (None, -1)
        for shift in sorted(range(-12, 13), key=abs):
            agree = 0
            for i in window:
                j = i + shift
                if not (0 <= j < len(live_slots)):
                    continue
                if j not in live_heads:
                    live_heads[j] = masked_head(self.b, live_slots[j], limit=16)
                if token_match(base_slots[i][1], live_heads[j]) >= 0.9:
                    agree += 1
            if agree > best[1]:
                best = (shift, agree)
        shift, agree = best
        if shift is None or agree < 3 or agree < len(window) // 2:
            return None, f"neighbourhood agreement too low ({agree}/{len(window)})"
        return shift, f"shift {shift:+d} ({agree}/{len(window)} discriminative neighbours agree)"

    def index_in_vtable(self, class_name, va):
        """Slot index of va in the class's primary live vtable, when it appears exactly once."""
        _, live_slots = self.vtable_live(class_name)
        hits = [i for i, fn in enumerate(live_slots) if fn == va]
        if len(hits) != 1:
            return None
        return hits[0]

    def is_shared_stub(self, va, limit=32):
        """True when `limit` or more qwords in data point at va (vtable slots of many classes)."""
        needle = struct.pack("<Q", va)
        count = 0
        for _base, blob in self.data_regions:
            count += blob.count(needle)
            if count >= limit:
                return True
        return False

    def s_samelayout(self, symbol, base, artifact):
        """The class's vtable unchanged: as many slots as in the baseline and every slot's
        code the same shape, so no method was added or removed and the index still holds.
        Decides what neighbour agreement cannot - a slot among a run of identical stubs."""
        class_name, index = base.get("vtable_name"), to_int(base.get("vfunc_index"))
        before = ((self.facts.get("vtables") or {}).get(class_name) or {}).get("slots") or []
        if base.get("category") != "vfunc" or not class_name or index is None or len(before) < 8:
            return []
        _ap, live = self.vtable_live(class_name)
        if len(live) != len(before) or not 0 <= index < len(live):
            return []
        for (_old, old_head, _name), now in zip(before, live):
            if masked_head(self.b, now, limit=16) != old_head:
                return []
        return [(live[index], f"vtable-layout unchanged ({len(live)}/{len(live)} slots)")]

    def s_siblingcallees(self, symbol, base, artifact):
        """Twins: pick the candidate that calls what a found sibling calls.

        Functions stamped from one template (CCSCustomHudLayout's *ForPlayer setters)
        share every byte but their helpers. In the baseline the target shared some unnamed
        helpers with a sibling that is already found here; the sibling's live calls, in the
        same order, say what those helpers are now, and only one other function calls all
        of them.
        """
        mine = {to_int(c.get("va")) for c in base.get("callees") or []} - {None}
        if not mine:
            return []
        mapped = {}
        for other, entry in self.facts["symbols"].items():
            if other == symbol or other not in self.resolved or entry.get("category") not in ("func", "vfunc"):
                continue
            theirs = [to_int(c.get("va")) for c in entry.get("callees") or []]
            if not mine.intersection(theirs):
                continue
            live = [target for _, target in self.fb.direct_calls(self.resolved[other])][:40]
            if len(live) != len(theirs):
                continue
            for was, now in zip(theirs, live):
                if was in mine:
                    mapped[was] = now if mapped.get(was, now) == now else None
        targets = {now for now in mapped.values() if now}
        if len(targets) < 2:
            return []
        callers = None
        for target in targets:
            here = {self.func_start(frm) for frm in self.b.code_refs_to(target)} - {None}
            callers = here if callers is None else callers & here
        callers = {fn for fn in callers or () if self.resolved_va.get(fn) in (None, symbol)}
        if len(callers) != 1:
            return []
        return [(callers.pop(), f"sibling-callees {len(targets)} shared helpers")]

    def s_consts(self, symbol, base, artifact):
        """Weak evidence: the layout fingerprint among the functions between the found
        neighbours. Only a clear, unique winner votes - twins tie and stay undecided."""
        mine = set(base.get("consts") or [])
        va = to_int(base.get("va"))
        if len(mine) < 5 or va is None:
            return []
        window = self._neighbour_window(va)
        if not window:
            return []
        lo, hi = window
        scored = []
        ea = self.b.next_func(lo)
        while ea is not None and ea < hi:
            live = set(self.fb.consts(ea))
            if live:
                scored.append((len(mine & live) / len(mine | live), ea))
            ea = self.b.next_func(ea)
        scored.sort(reverse=True)
        if not scored or scored[0][0] < 0.8 or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15):
            return []
        return [(scored[0][1], f"consts {scored[0][0]:.2f} of {len(mine)}")]

    def inlined_into(self, symbol, base):
        """(va, why) when the symbol's own strings now sit in another function.

        A function the compiler folded into its caller leaves nothing to find, and an
        agent spends three attempts learning that. Its string set moving whole into a
        function that is already something else, or has grown well past its old size,
        is what that looks like (ParseNetadrList into ConnectSocketToAddressList).
        """
        strings = [s for s in (base.get("strings") or []) if len(s) >= 8 and s.strip() not in GENERIC_STRINGS][:12]
        if len(strings) < 2:
            return self._inlined_by_calls(symbol, base)
        votes = {}
        for text in strings:
            for fn in self.string_refs(text):
                votes[fn] = votes.get(fn, 0) + 1
        if not votes:
            return None
        top, count = max(votes.items(), key=lambda kv: kv[1])
        if count < max(2, -(-len(strings) * 4 // 5)):
            return None
        owner = self.resolved_va.get(top)
        if owner and owner != symbol:
            return top, f"its strings ({count}/{len(strings)}) now sit in {owner} {hex(top)}"
        live = self.live_facts(top) or {}
        old, new = base.get("size") or 0, live.get("size") or 0
        if old and new >= 2 * old and self.score(base, top) < 0.5:
            return top, f"its strings ({count}/{len(strings)}) now sit in {hex(top)}, {new / old:.1f}x its old size"
        return None

    def _inlined_by_calls(self, symbol, base):
        """No strings: its callees and virtual calls, all found together in one function
        that is much bigger or already something else (InputTestActivator folded into
        the TestActivator script binding on windows 14182)."""
        targets = set()
        for callee in base.get("callees") or []:
            if callee.get("name") in self.resolved:
                targets.add(self.resolved[callee["name"]])
            elif callee.get("head"):
                hits = self.scan.matches(" ".join(callee["head"][:16]), limit=2)
                if len(hits) == 1:
                    targets.add(hits[0])
        vcalls = set(base.get("vcalls") or [])
        if not targets or len(targets) + len(vcalls) < 2:
            return None
        callers = None
        for target in targets:
            here = {self.func_start(frm) for frm in self.b.code_refs_to(target)} - {None}
            callers = here if callers is None else callers & here
        hosts = [fn for fn in callers or () if vcalls <= set(self.fb.vcalls(fn, limit=64))]
        if len(hosts) != 1:
            return None
        host = hosts[0]
        owner = self.resolved_va.get(host)
        what = f"its {len(targets)} callee(s) and {len(vcalls)} virtual call(s) now sit in"
        if owner and owner != symbol:
            return host, f"{what} {owner} {hex(host)}"
        live = self.live_facts(host) or {}
        old, new = base.get("size") or 0, live.get("size") or 0
        if old and new >= 2 * old and self.score(base, host) < 0.5:
            return host, f"{what} {hex(host)}, {new / old:.1f}x its old size"
        return None

    def s_vtable(self, symbol, base, artifact):
        class_name, index = base.get("vtable_name"), base.get("vfunc_index")
        if not class_name or index is None:
            return []
        shift, why = self.measure_shift(class_name, index)
        if shift is None:
            return []
        _, live_slots = self.vtable_live(class_name)
        new_index = index + shift
        if not (0 <= new_index < len(live_slots)):
            return []
        fn = live_slots[new_index]
        target = fn
        items = self.b.func_items(fn)[:3]
        if len(items) == 3:
            i0, i1, i2 = (self.b.insn(x) for x in items)
            if i0 and i1 and i2 and i0.mnem == "test" and i1.mnem in ("jz", "je") and i2.mnem == "jmp":
                t = next((op.addr for op in i2.ops if op.kind in ("near", "far") and op.addr), None)
                if t:
                    target = t
        return [(target, f"vtable {class_name}[{new_index}] {why}")]

    def string_refs(self, text):
        if text in self._string_cache:
            return self._string_cache[text]
        needle = text.encode("utf-8", "replace")
        funcs = set()
        for base, blob in self.data_regions:
            pos = blob.find(needle)
            while pos != -1:
                if pos == 0 or blob[pos - 1] == 0:
                    for frm in self.b.xrefs_to(base + pos):
                        start = self.func_start(frm)
                        if start is not None:
                            funcs.add(start)
                pos = blob.find(needle, pos + 1)
        self._string_cache[text] = funcs
        return funcs

    def s_strings(self, symbol, base, artifact):
        strings = [s for s in (base.get("strings") or []) if len(s) >= 8 and s.strip() not in GENERIC_STRINGS]
        if not strings:
            return []
        votes = {}
        for text in strings[:12]:
            for fn in self.string_refs(text):
                votes[fn] = votes.get(fn, 0) + 1
        if not votes:
            return []
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        top, count = ranked[0]
        if count < min(2, len(strings)) or (len(ranked) > 1 and ranked[1][1] == count):
            return []
        return [(top, f"strings {count}/{len(strings)}")]

    def s_callgraph(self, symbol, base, artifact):
        out = []
        for caller in base.get("callers") or []:
            name, ordinal = caller.get("name"), caller.get("ordinal")
            if not name or ordinal is None or name not in self.resolved:
                continue
            calls = self.fb.direct_calls(self.resolved[name])
            for k in (ordinal, ordinal - 1, ordinal + 1):
                if 0 <= k < len(calls):
                    out.append((calls[k][1], f"callgraph {name}#{k}"))
        callees = [c["name"] for c in (base.get("callees") or []) if c.get("name") in self.resolved]
        if callees:
            votes = {}
            for name in callees[:6]:
                for frm in self.b.code_refs_to(self.resolved[name]):
                    start = self.func_start(frm)
                    if start is not None:
                        votes[start] = votes.get(start, 0) + 1
            for fn, count in sorted(votes.items(), key=lambda kv: -kv[1])[:3]:
                if count >= min(2, len(callees)):
                    out.append((fn, f"calls {count} known callees"))
        return out

    def s_calleeheads(self, symbol, base, artifact):
        callees = [c for c in (base.get("callees") or []) if c.get("head") and not c.get("name")]
        if len(callees) < 2:
            return []
        located = []
        for c in callees[:10]:
            hits = self.scan.matches(" ".join(c["head"][:16]), limit=2)
            if len(hits) == 1:
                located.append(hits[0])
        if len(located) < 2:
            return []
        votes = {}
        for target in located:
            for frm in self.b.code_refs_to(target):
                start = self.func_start(frm)
                if start is not None:
                    votes[start] = votes.get(start, 0) + 1
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        if not ranked:
            return []
        top, count = ranked[0]
        if count < max(2, len(located) // 2) or (len(ranked) > 1 and ranked[1][1] == count):
            return []
        return [(top, f"callee-heads {count}/{len(located)}")]

    def _neighbour_window(self, va):
        """(lo, hi) live addresses of the found symbols that bracketed `va` in the baseline."""
        base_syms = sorted(((to_int(e.get("va")), n) for n, e in self.facts["symbols"].items()
                            if e.get("va") and n in self.resolved and e.get("category") in ("func", "vfunc")), key=lambda t: t[0])
        before = [t for t in base_syms if t[0] < va]
        after = [t for t in base_syms if t[0] > va]
        if not before or not after:
            return None
        lo, hi = self.resolved[before[-1][1]], self.resolved[after[0][1]]
        if hi <= lo or hi - lo > 0x40000:
            return None
        return lo, hi

    def s_neighbour(self, symbol, base, artifact):
        va = to_int(base.get("va"))
        if va is None:
            return []
        window = self._neighbour_window(va)
        if not window:
            return []
        lo, hi = window
        best = []
        ea = self.b.next_func(lo)
        while ea is not None and ea < hi:
            best.append((self.score(base, ea), ea))
            ea = self.b.next_func(ea)
        best.sort(reverse=True)
        return [(fn, f"neighbour score {s:.2f}") for s, fn in best[:2] if s >= self.min_score]

    def s_thunk(self, owner):
        target, head = owner.get("thunk_target"), owner.get("head") or []
        if not target or not head:
            return []
        out = []
        for ea in self.scan.matches(" ".join(head[:6]), limit=400):
            func = self.b.get_func(ea)
            if not func or func[0] != ea or func[1] - func[0] > 32:
                continue
            items = self.b.func_items(ea)
            last = self.b.insn(items[-1]) if items else None
            if last is None or last.mnem != "jmp":
                continue
            jt = next((op.addr for op in last.ops if op.kind in ("near", "far") and op.addr), None)
            if not jt or not self.b.get_func(jt):
                continue
            sc = self.score(target, jt)
            if sc >= self.min_score:
                out.append((sc, ea))
        out.sort(reverse=True)
        if not out or (len(out) > 1 and out[0][0] - out[1][0] < 0.05):
            return []
        return [(out[0][1], f"thunk -> target score {out[0][0]:.2f}")]

    # -- resolution -----------------------------------------------------------------
    def resolve_function(self, symbol, base, artifact):
        candidates = []
        for strat in (self.s_reloc, self.s_headreloc, self.s_samelayout, self.s_vtable, self.s_strings, self.s_callgraph,
                      self.s_calleeheads, self.s_neighbour, self.s_siblingcallees, self.s_consts):
            try:
                for va, how in strat(symbol, base, artifact):
                    head = self.func_start(va)
                    if head is not None:
                        candidates.append((head, how, self.score(base, head)))
            except Exception as error:
                self.log(f"    {strat.__name__} failed: {error}")
        # a stub every class shares (_purecall fills hundreds of vtable slots) is never one
        # symbol: an abstract base's slot points at it, the implementation lives elsewhere
        # ... unless the baseline function was itself such a stub (IGameSystem_OnSaveGame is a
        # 3-byte `ret 0` that many game systems share)
        tiny = 0 < (base.get("size") or 0) <= 8
        stubs = set() if tiny else {va for va in {c[0] for c in candidates} if self.is_shared_stub(va)}
        if stubs:
            candidates = [c for c in candidates if c[0] not in stubs]
            if not candidates:
                return None, (f"only a shared stub ({', '.join(hex(v) for v in sorted(stubs))}, e.g. _purecall) - "
                              f"the slot belongs to an abstract class; take it from one that implements it"), 0.0, []
        if not candidates:
            return None, "no candidate", 0.0, []
        by_va = {}
        for va, how, sc in candidates:
            by_va.setdefault(va, {"how": [], "score": sc})["how"].append(how)
        # agreement counts DISTINCT strategies: the same caller voting for ordinals
        # k and k+1 is one opinion, not two
        for info in by_va.values():
            info["families"] = len({h.split()[0] for h in info["how"]})
        ranked = sorted(by_va.items(), key=lambda kv: (kv[1]["families"], kv[1]["score"]), reverse=True)
        va, info = ranked[0]
        no_function_facts = not base.get("head") and not base.get("mnem")
        strong_slot = any(h.startswith("vtable") and self._slot_agreement(h) >= 5 for h in info["how"])
        strong = self._strong_families(info["how"])
        # Identity needs evidence about THIS function: the old signature still matching, its
        # string set, its callers or callees, or a vtable slot most neighbours agree on. A head
        # that merely resembles the old one, or a similar-looking neighbour, is what put three
        # CLoopModeGame callbacks on one stub in the 14182 windows run - never enough alone.
        decisive = "reloc" in strong or strong_slot or any(h.startswith("vtable-layout") for h in info["how"]) or any(
            h.startswith("strings") and int(re.match(r"strings (\d+)", h).group(1)) >= 3 for h in info["how"])
        if decisive or (strong and info["families"] >= 2 and info["score"] >= 0.35) or len(strong) >= 2:
            return va, " + ".join(info["how"]), info["score"], ranked
        why = "weak evidence only" if info["score"] >= self.min_score else f"score {info['score']:.2f}"
        return None, f"best {hex(va)} {why} via {' + '.join(info['how'])[:120]}", info["score"], ranked

    @classmethod
    def _strong_families(cls, hows):
        strong = set()
        for how in hows:
            family = how.split()[0]
            if family in ("reloc", "callgraph", "calls", "callee-heads", "thunk", "sibling-callees", "consts"):
                strong.add(family)
            elif family == "strings":
                m = re.match(r"strings (\d+)/(\d+)", how)
                if m and int(m.group(1)) >= 2:
                    strong.add(family)
            elif family == "vtable" and cls._slot_agreement(how) >= 4:
                strong.add(family)
        return strong

    @staticmethod
    def _slot_agreement(how):
        m = re.search(r"\((\d+)/(\d+) discriminative neighbours agree\)", how)
        return int(m.group(1)) if m else 0

    def find_site(self, owner_va, base, exact_bytes=False):
        func = self.b.get_func(owner_va)
        if not func:
            return None, 0.0
        items = self.b.func_items(func[0])
        ordinal = base.get("site_ordinal") or 0
        want_shape, want_ctx, want_raw = base.get("site_shape"), base.get("site_context") or [], base.get("site_raw") or []
        want_mnem, want_head = base.get("site_mnem"), base.get("site_head") or []
        scored, best_ctx = [], 0.0
        for i, ea in enumerate(items):
            insn = self.b.insn(ea)
            if insn is None:
                continue
            if want_shape:
                if insn_shape(self.b, ea) != want_shape:
                    continue
            elif insn.mnem != want_mnem:
                continue
            if exact_bytes and want_raw and [f"{b:02X}" for b in insn.raw] != want_raw:
                continue
            if not want_shape:
                masked, _ = masked_instruction(self.b, ea)
                if token_match(want_head, masked) < 0.99:
                    continue
            live_ctx = self.fb.context_shapes(func[0], ea)
            agree = (sum(1 for a, b in zip(want_ctx, live_ctx) if a == b) / len(want_ctx)) if want_ctx else 1.0
            best_ctx = max(best_ctx, agree)
            scored.append((-agree, abs(i - ordinal) / max(len(items), 1), ea))
        scored.sort()
        if not scored:
            return None, best_ctx
        if len(scored) == 1 and want_shape:
            return scored[0][2], max(-scored[0][0], 0.51)
        good = [row for row in scored if -row[0] >= 0.5]
        return (good[0][2], -good[0][0]) if good else (None, best_ctx)

    def resolve_owner(self, base):
        owner = base.get("owner")
        if not owner:
            return None, "no owner function in baseline"
        base_va = to_int(owner.get("va"))
        for name, entry in self.facts["symbols"].items():
            if to_int(entry.get("va")) == base_va and entry.get("category") in ("func", "vfunc") and name in self.resolved:
                return self.resolved[name], f"owner {name}"
        if owner.get("thunk_target"):
            found = self.s_thunk(owner)
            if found:
                return found[0][0], f"owner via {found[0][1]}"
        va, how, _, _ = self.resolve_function("(owner)", owner, {})
        return va, (f"owner via {how}" if va else how)

    def emit(self, symbol, rule):
        if self.dry_run:
            return f"(dry-run) {rule}"
        return self._emit(symbol, rule)

    @staticmethod
    def trim_to_baseline(out, artifact):
        """Keep only the fields the baseline artifact carries.

        The producing task's GENERATE_YAML_DESIRED_FIELDS decides an artifact's fields
        (CLAUDE.md rule 18), and the baseline is what that list produced last time. An
        emitter adds a func_sig to every function it can, including getters upstream
        chose to leave unsigned; the next pipeline run would drop it again. The boundary
        flag survives whenever the signature it qualifies does.
        """
        if not out or not artifact or not os.path.isfile(out):
            return out
        keep = set(artifact)
        if "func_sig" in keep:
            keep.add("func_sig_allow_across_function_boundary")
        if "vfunc_sig" in keep:
            keep.add("vfunc_sig_allow_across_function_boundary")
        with open(out, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        kept = [line for line in lines if line.partition(":")[0].strip() in keep or line.startswith((" ", "#"))]
        if len(kept) != len(lines):
            with open(out, "w", encoding="utf-8") as handle:
                handle.writelines(kept)
        return out

    def relocate_vcall(self, symbol, artifact):
        """A slot number read at a call site (vfunc_sig, no func_va): CLoopTypeBase_GetImplType
        is `call [rax+0x48]` inside CEngineServiceMgr_UnregisterLoopMode. The interface's own
        slot points at _purecall, so the site is the only evidence - and it is exact when the
        old pattern, displacement included, still matches once."""
        sig = artifact.get("vfunc_sig")
        if not sig or artifact.get("func_va"):
            return None
        offset = to_int(artifact.get("vfunc_offset"))
        hits = self.scan.matches(sig, limit=2)
        moved = False
        if not hits:
            # the slot may have moved (IEngineServiceMgr_GetEventDispatcher: call [rax+0xE8] ->
            # [rax+0xE0] on client 14182): the same site with the displacement as a wildcard,
            # still unique, is the same call - and its displacement is the new slot
            for variant in vcall_disp_variants(sig):
                hits = self.scan.matches(variant, limit=2)
                if hits:
                    sig, moved = variant, True
                    break
        if len(hits) != 1:
            return f"call-site pattern matches {len(hits)} places"
        insn = self.b.insn(hits[0])
        disp = next((op.addr for op in (insn.ops if insn else []) if op.kind == "displ" and op.addr is not None), None)
        if insn is None or insn.mnem != "call" or disp is None or offset is None:
            return f"no virtual call at {hex(hits[0])}"
        disp = int(disp) & 0xFFFFFFFF
        if disp % 8 or disp > 0x2000:
            return f"call at {hex(hits[0])} uses offset {hex(disp)}, not a vtable slot"
        if disp != offset and not moved and "??" not in sig.split()[2:3]:
            return f"call site at {hex(hits[0])} does not call slot offset {artifact.get('vfunc_offset')}"
        data = {key: artifact[key] for key in ("func_name", "vtable_name", "vfunc_sig_allow_across_function_boundary")
                if key in artifact}
        data.update({"vfunc_offset": hex(disp), "vfunc_index": disp // 8, "vfunc_sig": artifact["vfunc_sig"]})
        if moved:
            # the new site's own call bytes, displacement pinned again as in the baseline
            raw = self.b.read(hits[0], insn.size) or b""
            tokens = sig.split()
            tokens[: len(raw)] = [f"{b:02X}" for b in raw]
            data["vfunc_sig"] = " ".join(tokens)
        out = None
        if not self.dry_run:
            os.makedirs(self.out_dir, exist_ok=True)
            out = os.path.join(self.out_dir, f"{symbol}.{self.platform}.yaml")
            with open(out, "w", encoding="utf-8") as handle:
                handle.write(render_yaml(data))
        self.report["solved"].append({"symbol": symbol, "category": "vfunc", "va": hex(hits[0]),
                                      "how": (f"call site relocated, slot moved {artifact.get('vfunc_index')} -> {disp // 8} "
                                              f"(call [reg+{hex(offset)}] is now [reg+{hex(disp)}])" if disp != offset else
                                              f"call site relocated (call [reg+{hex(disp)}] -> slot {disp // 8})"),
                                      "score": None, "output": out})
        return True

    def relocate_slot_only(self, symbol, artifact, existing_dirs=()):
        """An interface slot with no function and no call site (INetworkGameServer_Set...):
        the method of the same name in another class shared its slot in the baseline, and
        that one has been found in this build - so the slot is the one it has now."""
        index = to_int(artifact.get("vfunc_index"))
        method = symbol.split("_", 1)[1] if "_" in symbol else None
        if index is None or not method or not self.baseline_artifact_dir:
            return None
        suffix = f"_{method}.{self.platform}.yaml"
        for name in sorted(os.listdir(self.baseline_artifact_dir)):
            if not name.endswith(suffix) or name == f"{symbol}.{self.platform}.yaml":
                continue
            before = parse_yaml(os.path.join(self.baseline_artifact_dir, name))
            if to_int(before.get("vfunc_index")) != index:
                continue
            for directory in (self.out_dir, *existing_dirs):
                path = os.path.join(directory, name)
                if not os.path.isfile(path):
                    continue
                now = to_int(parse_yaml(path).get("vfunc_index"))
                if now is None:
                    continue
                data = {"func_name": symbol, "vtable_name": artifact.get("vtable_name"),
                        "vfunc_offset": hex(now * 8), "vfunc_index": now}
                out = None
                if not self.dry_run:
                    os.makedirs(self.out_dir, exist_ok=True)
                    out = os.path.join(self.out_dir, f"{symbol}.{self.platform}.yaml")
                    with open(out, "w", encoding="utf-8") as handle:
                        handle.write(render_yaml(data))
                sibling = name[: -len(f".{self.platform}.yaml")]
                self.report["solved"].append({"symbol": symbol, "category": "vfunc", "va": "-",
                                              "how": f"slot {now}: {sibling} shared slot {index} in the baseline and is at {now} now",
                                              "score": None, "output": out})
                return True
        return None

    def hunt(self, symbol, base, artifact):
        category = base.get("category", "func")
        if category in ("func", "vfunc") and artifact and not artifact.get("func_va") \
                and not artifact.get("vfunc_sig") and artifact.get("vfunc_index") is not None:
            if self.relocate_slot_only(symbol, artifact, self.existing_dirs):
                return
        if category in ("func", "vfunc") and artifact.get("vfunc_sig") and not artifact.get("func_va"):
            outcome = self.relocate_vcall(symbol, artifact)
            if outcome is True:
                return
            if outcome:
                self.report["unresolved"].append({"symbol": symbol, "category": "vfunc", "why": outcome, "candidates": []})
                return
        if category == "vtable":
            self.report["skipped"].append({"symbol": symbol, "why": "vtable artifacts come from their own task"})
            return
        if category in ("func", "vfunc"):
            va, how, score, ranked = self.resolve_function(symbol, base, artifact)
            if va is not None:
                owner = self.resolved_va.get(va)
                if owner is not None and owner != symbol:
                    # one address, one name - unless the baseline shared it too (an alias, or
                    # two bodies the compiler folded into one)
                    other = (self.facts.get("symbols") or {}).get(owner) or {}
                    if not (other.get("va") and other.get("va") == base.get("va")):
                        how = f"{hex(va)} is already {owner}, and 14181 kept them apart"
                        va = None
            if va is None:
                row = {"symbol": symbol, "category": category, "why": how,
                       "candidates": [{"va": hex(v), "score": round(i["score"], 2), "how": i["how"]} for v, i in ranked[:4]]}
                inlined = self.inlined_into(symbol, base)
                if inlined:
                    row["inlined_into"] = hex(inlined[0])
                    row["why"] = f"inlined? {inlined[1]} - check, then declare it optional_output with an -inlined task"
                self.report["unresolved"].append(row)
                return
            if category == "vfunc":
                class_name = base.get("vtable_name")
                # the function's own position in the live vtable is the answer when it is
                # unambiguous; the measured shift is the fallback (and the only option for
                # slot-only baselines, where va came from that shift in the first place)
                index = self.index_in_vtable(class_name, va)
                if index is not None:
                    how += f" -> slot {index}"
                else:
                    shift, why = self.measure_shift(class_name, base.get("vfunc_index"))
                    if shift is None:
                        self.report["unresolved"].append({"symbol": symbol, "category": category, "why": f"function found at {hex(va)} but its {class_name} slot could not be determined ({why})",
                                                          "candidates": [{"va": hex(va), "score": round(score, 2), "how": [how]}]})
                        return
                    index = base["vfunc_index"] + shift
                rule = {"kind": "vfunc", "class": rtti_class(class_name), "index": index, "vtable_name": class_name,
                        # the table the index was measured in: same answer as RTTI where RTTI
                        # works, and the only one for template classes RTTI cannot name
                        "address_point": self.vtable_live(class_name)[0]}
            else:
                rule = {"kind": "func", "ea": va}
            out = self.trim_to_baseline(self.emit(symbol, rule), artifact)
            self.resolved[symbol] = va
            self.resolved_va.setdefault(va, symbol)
            self.report["solved"].append({"symbol": symbol, "category": category, "va": hex(va), "how": how, "score": round(score, 2), "output": out})
            return
        owner_va, how = self.resolve_owner(base)
        if owner_va is None:
            self.report["unresolved"].append({"symbol": symbol, "category": category, "why": how, "candidates": []})
            return
        site, agree = self.find_site(owner_va, base, exact_bytes=(category == "patch"))
        if site is None and category == "patch":
            site, agree = self.find_site(owner_va, base, exact_bytes=False)
            if site is not None:
                how += ", bytes changed (register/encoding), shape+immediate unique"
        if site is None:
            self.report["changed" if category == "patch" else "unresolved"].append(
                {"symbol": symbol, "category": category,
                 "why": f"{how}, but no instruction matching shape '{base.get('site_shape') or base.get('site_mnem')}' with its context in {hex(owner_va)} (best context {agree:.2f})",
                 "candidates": [{"va": hex(owner_va), "how": [how]}]})
            return
        if category == "structmember":
            rule = {"kind": "structmember", "ea": site, "struct_name": base.get("struct_name"), "member_name": base.get("member_name"), "size": base.get("size") or 4}
        elif category == "gv":
            rule = {"kind": "gv", "ea": site}
        else:
            rule = {"kind": "patch", "ea": site, "patch_bytes": base.get("patch_bytes")}
        out = self.trim_to_baseline(self.emit(symbol, rule), artifact)
        self.report["solved"].append({"symbol": symbol, "category": category, "va": hex(site), "how": f"{how}, site shape+context {agree:.2f}", "output": out})

    def hunt_new(self, symbol, category=None):
        """A symbol with no baseline on this platform: the same build's other platform,
        by its strings - the one fact two compilers agree on.

        Not the names IDA shows: the game's functions carry no symbols in the shipped
        binaries (14182's libserver.so exports only libstdc++ and third-party code), so
        a name in the database is one an earlier run gave it, and trusting it would let a
        wrong find confirm itself."""
        def unresolved(why, candidates=()):
            self.report["unresolved"].append({"symbol": symbol, "category": category or "?", "why": why,
                                              "candidates": [{"va": hex(v), "how": [h]} for v, h in candidates]})

        if category not in (None, "func", "vfunc"):
            unresolved(f"new {category}: no baseline to relocate - it needs an anchor (string, callee, slot) once")
            return
        va, how = None, None
        if self.sister and symbol in (self.sister.get("symbols") or {}):
            other = self.sister["symbols"][symbol]
            hits = self.s_strings(symbol, other, {})
            count = int(re.match(r"strings (\d+)", hits[0][1]).group(1)) if hits else 0
            if count >= 3:
                va, how = self.func_start(hits[0][0]), f"{self.sister.get('platform')} {self.sister.get('gamever')} {hits[0][1]}"
            else:
                unresolved(f"new here; the {self.sister.get('platform')} record's strings do not decide it"
                           + (f" ({hits[0][1]})" if hits else ""), [(hits[0][0], hits[0][1])] if hits else [])
                return
        else:
            where = f" and no {self.sister.get('platform')} record" if self.sister else ""
            unresolved(f"new: no baseline in {self.facts.get('gamever')}{where} - it needs an anchor (string, callee, slot) once")
            return
        owner = self.resolved_va.get(va)
        if va is None or (owner is not None and owner != symbol):
            unresolved(f"{how} points at {hex(va) if va else '?'}, which is already {owner}")
            return
        out = self.emit(symbol, {"kind": "func", "ea": va})
        self.resolved[symbol] = va
        self.resolved_va.setdefault(va, symbol)
        self.report["solved"].append({"symbol": symbol, "category": "func", "va": hex(va), "how": how, "score": None, "output": out})

    def run(self, symbols=None, baseline_artifact_dir=None, existing_dirs=(), categories=None):
        suffix = f".{self.platform}.yaml"
        have = set()
        # symbols named explicitly are hunted even when some folder already holds them: an
        # unreviewed file in the review folder is not a reason to skip (Ctrl-Alt-D's list)
        for directory in () if symbols else (self.out_dir, *existing_dirs):
            if os.path.isdir(directory):
                have.update(n[: -len(suffix)] for n in os.listdir(directory) if n.endswith(suffix))
        targets = [s for s in self.facts["symbols"] if s not in have and (not symbols or s in symbols)]
        self.log(f"[hunt] {self.module}/{self.platform} {self.gamever}: {len(targets)} missing vs {self.facts.get('gamever')}")
        order = sorted(targets, key=lambda s: 0 if self.facts["symbols"][s].get("category") in ("func", "vfunc") else 1)
        self.baseline_artifact_dir, self.existing_dirs = baseline_artifact_dir, tuple(existing_dirs)
        for n, symbol in enumerate(order, 1):
            base = self.facts["symbols"][symbol]
            artifact = {}
            if baseline_artifact_dir:
                path = os.path.join(baseline_artifact_dir, f"{symbol}.{self.platform}.yaml")
                if os.path.isfile(path):
                    artifact = parse_yaml(path)
            try:
                self.hunt(symbol, base, artifact)
            except Exception as error:
                self.report["unresolved"].append({"symbol": symbol, "category": base.get("category"), "why": f"error: {error}", "candidates": []})
            if n % 25 == 0:
                self.log(f"[hunt] {n}/{len(order)} ... solved {len(self.report['solved'])}")
        # named symbols the baseline never had: nothing to relocate, so other evidence
        for symbol in symbols or ():
            if symbol in self.facts["symbols"] or symbol in have:
                continue
            try:
                self.hunt_new(symbol, (categories or {}).get(symbol))
            except Exception as error:
                self.report["unresolved"].append({"symbol": symbol, "category": "?", "why": f"error: {error}", "candidates": []})
        return self.report


def print_report(report, log=print):
    log("=" * 78)
    log(f"[hunt] solved {len(report['solved'])}, unresolved {len(report['unresolved'])}, changed {len(report['changed'])}, skipped {len(report['skipped'])}")
    for row in report["solved"]:
        log(f"  OK   {row['category']:12} {row['symbol']:55} {row['va']:12} {row['how']}")
    for row in report["changed"]:
        log(f"  CHG  {row['category']:12} {row['symbol']:55} {row['why']}")
    for row in report["unresolved"]:
        cands = ", ".join(f"{c['va']}({c.get('score', '?')})" for c in row.get("candidates", [])[:3])
        log(f"  ??   {row['category']:12} {row['symbol']:55} {row['why']}" + (f"  candidates: {cands}" if cands else ""))
    log("=" * 78)
