"""ida_baseline_facts.py - IDA script: extract what a hunt needs to know about the PREVIOUS build.

Run headless by baseline_facts.py over a copy of the baseline IDB:

    idat -A -S"ida_baseline_facts.py <repo> <artifact_dir> <platform> <out.json>" <baseline>.i64

For every artifact of the baseline module/platform it records the facts that
survive a rebuild better than raw bytes do: the masked head, the mnemonic
sequence, the direct callees in order, the callers with the ordinal of the call
inside them, the referenced strings, the vcall offsets, and for vfuncs the whole
vtable neighbourhood (slot -> masked head) so a slot shift can be measured
instead of assumed. Struct-member, global and patch sites are located from their
baseline signature and recorded with their owning function and instruction
ordinal. ida_auto_hunt.py consumes the result on the NEW build.
"""
import json
import os
import sys

import ida_auto
import ida_bytes
import ida_funcs
import ida_idaapi
import ida_nalt
import ida_ua
import idautils
import idc

HEAD_BYTES = 48
MNEM_COUNT = 40


def load_sig_maker(repo):
    ns = {"__name__": "cs2_facts_sig_maker"}
    with open(os.path.join(repo, "ida_sig_maker.py"), "r", encoding="utf-8") as handle:
        exec(compile(handle.read(), "ida_sig_maker.py", "exec"), ns)
    return ns


def parse_yaml(path):
    data = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if ":" in line and not line.startswith((" ", "#")):
                key, _, value = line.partition(":")
                data[key.strip()] = value.strip().strip("'\"")
    return data


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


def to_int(value):
    if value in (None, ""):
        return None
    text = str(value)
    return int(text, 16) if text.lower().startswith("0x") else int(text)


class Facts:
    def __init__(self, sm):
        self.sm = sm
        self._calls = {}
        self.strings_cache = {}

    def masked_head(self, ea, limit=HEAD_BYTES, func_end=None):
        tokens, cur = [], ea
        while len(tokens) < limit:
            if func_end is not None and cur >= func_end:
                break
            try:
                masked, insn, raw = self.sm["masked_instruction"](cur)
            except ValueError:
                break
            tokens.extend(masked)
            cur += insn.size
        return tokens[:limit]

    def mnemonics(self, ea, func_end, limit=MNEM_COUNT):
        out, cur = [], ea
        while cur < func_end and len(out) < limit:
            insn = ida_ua.insn_t()
            size = ida_ua.decode_insn(insn, cur)
            if size <= 0:
                break
            out.append(idc.print_insn_mnem(cur))
            cur += size
        return out

    def direct_calls(self, func):
        if func.start_ea in self._calls:
            return self._calls[func.start_ea]
        out = []
        for head in idautils.FuncItems(func.start_ea):
            mnem = idc.print_insn_mnem(head)
            if mnem not in ("call", "jmp"):
                continue
            target = idc.get_operand_value(head, 0)
            if idc.get_operand_type(head, 0) not in (idc.o_near, idc.o_far) or target in (0, ida_idaapi.BADADDR):
                continue
            if mnem == "jmp":
                # a tail call leaves the function; an in-function jump does not count
                if func.start_ea <= target < func.end_ea:
                    continue
                if not ida_funcs.get_func(target) or ida_funcs.get_func(target).start_ea != target:
                    continue
            out.append((head, target))
        self._calls[func.start_ea] = out
        return out

    def vcalls(self, func, limit=8):
        out = []
        for head in idautils.FuncItems(func.start_ea):
            if idc.print_insn_mnem(head) == "call" and idc.get_operand_type(head, 0) == idc.o_displ:
                out.append(idc.get_operand_value(head, 0))
                if len(out) >= limit:
                    break
        return out

    def strings_of(self, func):
        out = set()
        for head in idautils.FuncItems(func.start_ea):
            for xref in idautils.DataRefsFrom(head):
                text = idc.get_strlit_contents(xref, -1, ida_nalt.STRTYPE_C)
                if text and len(text) >= 6:
                    out.add(text.decode("utf-8", "replace")[:160])
        return sorted(out)

    def callers_of(self, func, va_to_symbol):
        out = []
        for xref in idautils.CodeRefsTo(func.start_ea, 0):
            caller = ida_funcs.get_func(xref)
            if not caller:
                continue
            calls = self.direct_calls(caller)
            ordinal = next((i for i, (site, _) in enumerate(calls) if site == xref), None)
            out.append({"va": hex(caller.start_ea), "name": va_to_symbol.get(caller.start_ea), "ordinal": ordinal, "site": hex(xref), "ncalls": len(calls)})
        return out[:24]

    def function_facts(self, ea, va_to_symbol):
        func = ida_funcs.get_func(ea)
        if not func:
            return {"va": hex(ea), "size": 0, "no_function": True}
        calls = self.direct_calls(func)
        return {
            "va": hex(func.start_ea),
            "size": func.size(),
            "head": self.masked_head(func.start_ea, func_end=func.end_ea),
            "mnem": self.mnemonics(func.start_ea, func.end_ea),
            "callees": [{"va": hex(t), "name": va_to_symbol.get(t),
                         "head": None if va_to_symbol.get(t) else self.masked_head(t, limit=24)} for _, t in calls][:40],
            "callers": self.callers_of(func, va_to_symbol),
            "strings": self.strings_of(func)[:40],
            "vcalls": self.vcalls(func),
        }

    @staticmethod
    def insn_shape(ea):
        """Register-agnostic description of one instruction: mnemonic, operand kinds, small immediates."""
        insn = ida_ua.insn_t()
        if ida_ua.decode_insn(insn, ea) <= 0:
            return None
        kinds, imms = [], []
        for op in insn.ops:
            if op.type == ida_ua.o_void:
                break
            kinds.append(int(op.type))
            if op.type == ida_ua.o_imm:
                value = int(op.value) & 0xFFFFFFFFFFFFFFFF
                imms.append(value if value < 0x80000000 else "big")
        return f"{idc.print_insn_mnem(ea)}|{','.join(map(str, kinds))}|{','.join(map(str, imms))}"

    def context_shapes(self, func, site_ea, before=3, after=3):
        items = list(idautils.FuncItems(func.start_ea)) if func else [site_ea]
        try:
            i = items.index(site_ea)
        except ValueError:
            return []
        window = items[max(0, i - before): i] + items[i + 1: i + 1 + after]
        return [self.insn_shape(ea) for ea in window]

    def thunk_target(self, func, va_to_symbol):
        """For a tiny owner ending in a tail jump, the facts of the function it jumps to."""
        if not func or func.size() > 32:
            return None
        last = None
        for head in idautils.FuncItems(func.start_ea):
            last = head
        if last is None or idc.print_insn_mnem(last) != "jmp" or idc.get_operand_type(last, 0) not in (idc.o_near, idc.o_far):
            return None
        target = idc.get_operand_value(last, 0)
        tf = ida_funcs.get_func(target)
        if not tf or tf.start_ea != target:
            return None
        return self.function_facts(target, va_to_symbol)

    def site_facts(self, site_ea, va_to_symbol):
        func = ida_funcs.get_func(site_ea)
        ordinal = None
        if func:
            ordinal = sum(1 for head in idautils.FuncItems(func.start_ea) if head < site_ea)
        try:
            masked, insn, raw = self.sm["masked_instruction"](site_ea)
        except ValueError:
            masked, insn, raw = [], None, b""
        owner = self.function_facts(func.start_ea, va_to_symbol) if func else None
        if owner is not None:
            thunk = self.thunk_target(func, va_to_symbol)
            if thunk:
                owner["thunk_target"] = thunk
        return {
            "site_va": hex(site_ea),
            "site_head": masked,
            "site_raw": [f"{b:02X}" for b in (raw or b"")],
            "site_mnem": idc.print_insn_mnem(site_ea),
            "site_shape": self.insn_shape(site_ea),
            "site_context": self.context_shapes(func, site_ea),
            "site_ordinal": ordinal,
            "owner": owner,
        }


def main():
    repo, artifact_dir, platform, out_path = idc.ARGV[1:5]
    ida_auto.auto_wait()
    sm = load_sig_maker(repo)
    scan = sm["Scan"]()
    facts = Facts(sm)
    records = {}
    for name in sorted(os.listdir(artifact_dir)):
        if not name.endswith(f".{platform}.yaml"):
            continue
        rec = parse_yaml(os.path.join(artifact_dir, name))
        records[name[: -len(f".{platform}.yaml")]] = rec
    va_to_symbol = {}
    for symbol, rec in records.items():
        va = to_int(rec.get("func_va"))
        if va is not None and category_of(rec) in ("func", "vfunc"):
            va_to_symbol.setdefault(va, symbol)

    out = {"gamever": os.path.basename(os.path.dirname(artifact_dir)), "module": os.path.basename(artifact_dir),
           "platform": platform, "imagebase": hex(ida_nalt.get_imagebase()), "symbols": {}, "vtables": {}}
    vtable_classes = set()
    for symbol, rec in records.items():
        category = category_of(rec)
        entry = {"category": category}
        try:
            if category in ("func", "vfunc"):
                va = to_int(rec.get("func_va"))
                if va is not None:
                    entry.update(facts.function_facts(va, va_to_symbol))
                if category == "vfunc":
                    entry["vtable_name"] = rec.get("vtable_name")
                    entry["vfunc_index"] = to_int(rec.get("vfunc_index"))
                    if rec.get("vtable_name"):
                        vtable_classes.add(rec["vtable_name"])
            elif category == "structmember":
                entry.update({"struct_name": rec.get("struct_name"), "member_name": rec.get("member_name"),
                              "offset": rec.get("offset"), "size": to_int(rec.get("size"))})
                sig = rec.get("offset_sig")
                hits = scan.matches(sig, limit=2) if sig else []
                if len(hits) == 1:
                    entry.update(facts.site_facts(hits[0], va_to_symbol))
                else:
                    entry["site_error"] = f"offset_sig hits={len(hits)}"
            elif category == "gv":
                entry["gv_va"] = rec.get("gv_va")
                site = to_int(rec.get("gv_sig_va"))
                if site is None and rec.get("gv_sig"):
                    hits = scan.matches(rec["gv_sig"], limit=2)
                    site = hits[0] if len(hits) == 1 else None
                if site is not None:
                    entry.update(facts.site_facts(site, va_to_symbol))
                else:
                    entry["site_error"] = "gv site not found"
            elif category == "patch":
                entry["patch_bytes"] = rec.get("patch_bytes")
                sig = rec.get("patch_sig")
                hits = scan.matches(sig, limit=2) if sig else []
                if len(hits) == 1:
                    entry.update(facts.site_facts(hits[0], va_to_symbol))
                else:
                    entry["site_error"] = f"patch_sig hits={len(hits)}"
            elif category == "vtable":
                entry["vtable_class"] = rec.get("vtable_class")
                if rec.get("vtable_class"):
                    vtable_classes.add(rec["vtable_class"])
        except Exception as error:  # one bad record must not lose the rest
            entry["error"] = str(error)
        out["symbols"][symbol] = entry

    for class_name in sorted(vtable_classes):
        try:
            rtti_name = class_name[: -len("_vtable")] if class_name.endswith("_vtable") else class_name
            tables = [ap for ap, ott in sm["rtti_vtables"](rtti_name) if ott == 0]
            if len(tables) != 1:
                out["vtables"][class_name] = {"error": f"{len(tables)} primary vtables"}
                continue
            ap = tables[0]
            slots = []
            for index in range(1024):
                fn = ida_bytes.get_qword(ap + 8 * index)
                if not fn or not sm["is_code_ea"](fn):
                    break
                slots.append([hex(fn), facts.masked_head(fn, limit=16), va_to_symbol.get(fn)])
            out["vtables"][class_name] = {"address_point": hex(ap), "slots": slots}
        except Exception as error:
            out["vtables"][class_name] = {"error": str(error)}

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(out, handle)
    print(f"[facts] {len(out['symbols'])} symbols, {len(out['vtables'])} vtables -> {out_path}")


if __name__ == "__main__":
    try:
        main()
    finally:
        idc.qexit(0)
