"""ghidra_backend.py - hunt_core Backend on Ghidra through PyGhidra (CPython).

Runs in a normal CPython process with `pyghidra` (pip extra `ghidra`) and a
Ghidra install (GHIDRA_INSTALL_DIR or ~/ghidra_*). ghidra_hunt.py opens the
program and hands the FlatProgramAPI here; everything hunt_core asks about the
binary is answered from Ghidra's listing, memory and reference manager.

Operand model: Ghidra has no operand byte offsets, but the instruction
prototype exposes an operand VALUE MASK over the encoded bytes, which is exactly
what "the bytes that relocate" means for wildcarding. Kinds map from the operand
objects: Register+Scalar -> displ, Register only -> reg (or phrase when it is a
memory deref), Scalar only -> imm, Address -> near for flow instructions and
mem otherwise (rip when the 4-byte displacement resolves to that address).
"""
import struct


def _file_image_base(path):
    """Lowest PT_LOAD vaddr of an ELF64 (0 for a PIE), or the PE ImageBase."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
            if head[:4] == b"\x7fELF":
                phoff, = struct.unpack_from("<Q", head, 0x20)
                phentsize, phnum = struct.unpack_from("<HH", head, 0x36)
                handle.seek(phoff)
                table = handle.read(phentsize * phnum)
                loads = [struct.unpack_from("<Q", table, i * phentsize + 0x10)[0]
                         for i in range(phnum) if struct.unpack_from("<I", table, i * phentsize)[0] == 1]
                return min(loads) if loads else 0
    except OSError:
        return 0
    if head[:2] == b"MZ":
        pe, = struct.unpack_from("<I", head, 0x3C)
        magic, = struct.unpack_from("<H", head, pe + 24)
        return struct.unpack_from("<Q", head, pe + 48)[0] if magic == 0x20B else struct.unpack_from("<I", head, pe + 52)[0]
    return 0


# Ghidra's x86 mnemonics where IDA spells them differently; facts must compare equal
_MNEM = {
    "ret": "retn", "jc": "jb", "jnc": "jnb", "setc": "setb", "setnc": "setnb",
    "cmovc": "cmovb", "cmovnc": "cmovnb",
}


class Operand:
    __slots__ = ("kind", "offb", "value", "addr", "rip")

    def __init__(self, kind, offb, value, addr, rip):
        self.kind, self.offb, self.value, self.addr, self.rip = kind, offb, value, addr, rip


class Insn:
    __slots__ = ("ea", "size", "mnem", "raw", "ops")

    def __init__(self, ea, size, mnem, raw, ops):
        self.ea, self.size, self.mnem, self.raw, self.ops = ea, size, mnem, raw, ops


class GhidraBackend:
    def __init__(self, flat_api, binary_path=None):
        from ghidra.program.model.address import Address  # noqa: F401  (import check)
        from ghidra.program.model.lang import Register
        from ghidra.program.model.scalar import Scalar
        from ghidra.program.model.address import GenericAddress
        self._Register, self._Scalar, self._GenericAddress = Register, Scalar, GenericAddress
        self.flat = flat_api
        self.program = flat_api.getCurrentProgram()
        self.listing = self.program.getListing()
        self.memory = self.program.getMemory()
        self.fm = self.program.getFunctionManager()
        self.refs = self.program.getReferenceManager()
        self.space = self.program.getAddressFactory().getDefaultAddressSpace()
        self._insn_cache = {}
        self._pseudo = None
        self._blocks = [b for b in self.memory.getBlocks() if b.isInitialized() and not b.isExternalBlock()]
        # Ghidra loads a PIE ELF whose lowest PT_LOAD is 0 at 0x100000; IDA and every
        # artifact use the file's own addresses. Every address crossing this API is a
        # file address: addr() adds the delta, _ea() takes it off again.
        self.binary_path = binary_path or self.input_path()
        self.delta = int(self.program.getImageBase().getOffset()) - _file_image_base(self.binary_path)

    # -- helpers -------------------------------------------------------------------
    def addr(self, ea):
        return self.space.getAddress(int(ea) + self.delta)

    def _ea(self, address):
        return int(address.getOffset()) - self.delta

    def _block(self, ea):
        return self.memory.getBlock(self.addr(ea))

    def _read_block(self, block):
        size = int(block.getSize())
        buf = bytearray(size)
        from jpype import JArray, JByte
        jbuf = JArray(JByte)(size)
        got = block.getBytes(block.getStart(), jbuf)
        return bytes(bytearray(jbuf[:got]))

    # -- memory / segments ---------------------------------------------------------
    def _regions(self, executable):
        out = []
        for block in self._blocks:
            if bool(block.isExecute()) != executable:
                continue
            try:
                data = self._read_block(block)
            except Exception:
                continue
            if data:
                out.append((self._ea(block.getStart()), data))
        return out

    def exec_regions(self):
        return self._regions(True)

    def data_regions(self):
        return self._regions(False)

    def is_code(self, ea):
        block = self._block(ea)
        return bool(block and block.isExecute())

    def qword(self, ea):
        try:
            return int(self.memory.getLong(self.addr(ea))) & 0xFFFFFFFFFFFFFFFF
        except Exception:
            return None

    def read(self, ea, n):
        try:
            from jpype import JArray, JByte
            jbuf = JArray(JByte)(int(n))
            got = self.memory.getBytes(self.addr(ea), jbuf)
            return bytes(bytearray(jbuf[:got]))
        except Exception:
            return None

    def imagebase(self):
        return int(self.program.getImageBase().getOffset()) - self.delta

    def input_path(self):
        return str(self.program.getExecutablePath() or "")

    # -- functions -----------------------------------------------------------------
    def _function_at_boundary(self, ea):
        """Create a function Ghidra's analysis missed, but only on a real boundary:
        artifact VAs are function starts, a mid-body EA must never become one."""
        prev = self.read(ea - 1, 1)
        if not prev or prev[0] not in (0xCC, 0x90, 0xC3, 0x00) and self.read(ea - 2, 2) != b"\x0f\x0b":
            return None
        tx = self.program.startTransaction("cs2vibe create function")
        try:
            return self.flat.createFunction(self.addr(ea), None)
        except Exception:
            return None
        finally:
            self.program.endTransaction(tx, True)

    def _function(self, ea, create=False):
        func = self.fm.getFunctionContaining(self.addr(ea))
        if func is None and create:
            func = self._function_at_boundary(ea)
        return func

    def get_func(self, ea):
        func = self._function(ea, create=True)
        if func is None:
            return None
        entry = func.getEntryPoint()
        # IDA's end_ea is the end of the entry chunk; a Ghidra body can hold far chunks
        chunk = func.getBody().getRangeContaining(entry)
        end = chunk.getMaxAddress() if chunk is not None else func.getBody().getMaxAddress()
        return self._ea(entry), self._ea(end) + 1

    def next_func(self, ea):
        func = self.fm.getFunctionAfter(self.addr(ea))
        return self._ea(func.getEntryPoint()) if func is not None else None

    def func_items(self, start):
        func = self._function(start, create=True)
        if func is None:
            return []
        return [self._ea(i.getAddress()) for i in self.listing.getInstructions(func.getBody(), True)]

    # -- instructions --------------------------------------------------------------
    def _instruction(self, ea):
        instr = self.listing.getInstructionAt(self.addr(ea))
        if instr is not None:
            return instr
        # padding and bytes Ghidra left undefined: decode without touching the listing
        if self._pseudo is None:
            from ghidra.app.util import PseudoDisassembler
            self._pseudo = PseudoDisassembler(self.program)
        try:
            return self._pseudo.disassemble(self.addr(ea))
        except Exception:
            return None

    def _find_disp(self, raw, value, after):
        """Offset of an encoded displacement: Ghidra's operand mask starts at ModRM."""
        encodings = []
        if -128 <= value < 128:
            encodings.append(struct.pack("<b", value))
        if -(1 << 31) <= value < (1 << 31):
            encodings.append(struct.pack("<i", value))
        for enc in encodings:
            pos = raw.find(enc, max(after, 1))
            if pos >= 0 and pos + len(enc) <= len(raw):
                return pos
        return -1

    def insn(self, ea):
        cached = self._insn_cache.get(ea)
        if cached is not None:
            return cached
        instr = self._instruction(ea)
        if instr is None:
            return None
        raw = bytes(bytearray(instr.getBytes()))
        size = len(raw)
        mnem = str(instr.getMnemonicString()).lower()
        mnem = _MNEM.get(mnem, mnem)
        flow = instr.getFlowType()
        is_flow = bool(flow.isCall() or flow.isJump())
        proto = instr.getPrototype()
        ops = []
        for i in range(instr.getNumOperands()):
            objs = list(instr.getOpObjects(i))
            regs = [o for o in objs if isinstance(o, self._Register)]
            scalars = [o for o in objs if isinstance(o, self._Scalar)]
            addrs = [o for o in objs if isinstance(o, self._GenericAddress)]
            mask_off = -1
            try:
                mask = proto.getOperandValueMask(i)
                mbytes = bytes(bytearray(mask.getBytes())) if mask is not None else b""
                for k, b in enumerate(mbytes):
                    if b:
                        mask_off = k
                        break
            except Exception:
                mask_off = -1
            offb = mask_off
            value = addr = None
            rip = False
            optype = int(instr.getOperandType(i))
            indirect = bool(optype & 0x4)        # OperandType.INDIRECT
            dynamic = bool(optype & 0x400000)    # OperandType.DYNAMIC
            target = None
            if addrs:
                target = self._ea(addrs[0])
            elif scalars and not regs:
                # a PIE `lea reg,[rip+x]` comes back as a bare scalar holding the target
                cand = int(scalars[0].getUnsignedValue()) - self.delta
                pos = self._find_disp(raw, cand - (ea + size), 1) if not is_flow else -1
                if pos >= 0 and pos + 4 <= size and struct.unpack_from("<i", raw, pos)[0] == cand - (ea + size):
                    target = cand
            if target is not None:
                addr = target
                if is_flow and i == 0:
                    kind = "near"
                else:
                    kind = "mem"
                    pos = self._find_disp(raw, addr - (ea + size), 1)
                    if pos >= 0 and pos + 4 <= size and struct.unpack_from("<i", raw, pos)[0] == addr - (ea + size):
                        offb, rip = pos, True
            elif regs and scalars:
                kind = "displ"
                disp = int(scalars[0].getSignedValue())
                addr = disp & 0xFFFFFFFF
                pos = self._find_disp(raw, disp, mask_off + 1 if mask_off >= 0 else 1)
                offb = pos if pos >= 0 else mask_off
            elif scalars:
                kind = "imm"
                value = int(scalars[0].getUnsignedValue())
            elif regs:
                kind = "phrase" if (dynamic or indirect) else "reg"
            else:
                kind = "other"
            ops.append(Operand(kind, offb, value, addr, rip))
        result = Insn(ea, size, mnem, raw, ops)
        self._insn_cache[ea] = result
        return result

    # -- references ----------------------------------------------------------------
    def string_at(self, ea):
        data = self.listing.getDataContaining(self.addr(ea))
        if data is not None and data.hasStringValue():
            try:
                return str(data.getValue())
            except Exception:
                pass
        raw = self.read(ea, 200)
        if not raw:
            return None
        text = raw.split(b"\x00", 1)[0]
        if len(text) >= 6 and all(32 <= b < 127 or b in (9, 10, 13) for b in text):
            return text.decode("ascii", "replace")
        return None

    def data_refs_from(self, ea):
        instr = self.listing.getInstructionAt(self.addr(ea))
        if instr is None:
            return []
        return [self._ea(r.getToAddress()) for r in instr.getReferencesFrom() if not r.getReferenceType().isFlow()]

    def code_refs_to(self, ea):
        out = []
        for r in self.refs.getReferencesTo(self.addr(ea)):
            t = r.getReferenceType()
            if t.isCall() or t.isJump():
                out.append(self._ea(r.getFromAddress()))
        return out

    def xrefs_to(self, ea):
        return [self._ea(r.getFromAddress()) for r in self.refs.getReferencesTo(self.addr(ea))]
