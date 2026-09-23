"""ida_backend.py - hunt_core Backend implemented on IDAPython (IDA 9).

Loaded inside IDA (GUI or idat). Everything hunt_core needs about the loaded
binary is answered here; nothing else in the hunting stack imports IDA.
"""
import struct

import ida_bytes
import ida_funcs
import ida_idaapi
import ida_nalt
import ida_segment
import ida_ua
import idautils
import idc

_KIND = {}


def _kinds():
    if not _KIND:
        _KIND.update({
            int(ida_ua.o_reg): "reg", int(ida_ua.o_imm): "imm", int(ida_ua.o_mem): "mem",
            int(ida_ua.o_displ): "displ", int(ida_ua.o_near): "near", int(ida_ua.o_far): "far",
            int(ida_ua.o_phrase): "phrase",
        })
    return _KIND


class Operand:
    __slots__ = ("kind", "offb", "value", "addr", "rip")

    def __init__(self, kind, offb, value, addr, rip):
        self.kind, self.offb, self.value, self.addr, self.rip = kind, offb, value, addr, rip


class Insn:
    __slots__ = ("ea", "size", "mnem", "raw", "ops")

    def __init__(self, ea, size, mnem, raw, ops):
        self.ea, self.size, self.mnem, self.raw, self.ops = ea, size, mnem, raw, ops


class IdaBackend:
    def __init__(self):
        self._insn_cache = {}

    # -- memory / segments ---------------------------------------------------------
    def _regions(self, executable):
        out = []
        for seg_ea in idautils.Segments():
            seg = ida_segment.getseg(seg_ea)
            if not seg or bool(seg.perm & ida_segment.SEGPERM_EXEC) != executable:
                continue
            blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
            if blob:
                out.append((seg.start_ea, blob))
        return out

    def exec_regions(self):
        return self._regions(True)

    def data_regions(self):
        return self._regions(False)

    def is_code(self, ea):
        seg = ida_segment.getseg(ea)
        return bool(seg and (seg.perm & ida_segment.SEGPERM_EXEC))

    def qword(self, ea):
        try:
            value = ida_bytes.get_qword(ea)
        except Exception:
            return None
        return None if value in (None, ida_idaapi.BADADDR) else value

    def read(self, ea, n):
        return ida_bytes.get_bytes(ea, n)

    def imagebase(self):
        return ida_nalt.get_imagebase()

    def input_path(self):
        return (ida_nalt.get_input_file_path() or "").replace("\\", "/")

    # -- functions -----------------------------------------------------------------
    def get_func(self, ea):
        func = ida_funcs.get_func(ea)
        return (func.start_ea, func.end_ea) if func else None

    def next_func(self, ea):
        func = ida_funcs.get_next_func(ea)
        return func.start_ea if func else None

    def func_items(self, start):
        return list(idautils.FuncItems(start))

    # -- instructions --------------------------------------------------------------
    def insn(self, ea):
        cached = self._insn_cache.get(ea)
        if cached is not None:
            return cached
        raw_insn = ida_ua.insn_t()
        size = ida_ua.decode_insn(raw_insn, ea)
        if size <= 0:
            return None
        raw = ida_bytes.get_bytes(ea, size) or b""
        ops = []
        kinds = _kinds()
        for op in raw_insn.ops:
            if op.type == ida_ua.o_void:
                break
            kind = kinds.get(int(op.type), "other")
            offb = int(op.offb) if op.offb != -1 else -1
            value = int(op.value) if kind == "imm" else None
            addr = int(op.addr) if kind in ("mem", "displ", "near", "far") else None
            rip = False
            if kind == "mem" and offb >= 0 and offb + 4 <= size:
                disp = struct.unpack_from("<i", raw, offb)[0]
                rip = (ea + size + disp) == addr
            ops.append(Operand(kind, offb, value, addr, rip))
        result = Insn(ea, size, idc.print_insn_mnem(ea), raw, ops)
        self._insn_cache[ea] = result
        return result

    # -- references ----------------------------------------------------------------
    def string_at(self, ea):
        text = idc.get_strlit_contents(ea, -1, ida_nalt.STRTYPE_C)
        return text.decode("utf-8", "replace") if text else None

    def data_refs_from(self, ea):
        return list(idautils.DataRefsFrom(ea))

    def code_refs_to(self, ea):
        return list(idautils.CodeRefsTo(ea, 0))

    def xrefs_to(self, ea):
        return [x.frm for x in idautils.XrefsTo(ea, 0)]
