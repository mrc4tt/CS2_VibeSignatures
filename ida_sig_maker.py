"""
ida_sig_maker.py - IDA Pro 9 sig/YAML maker for CS2_VibeSignatures artifacts.

Usage (inside IDA, with a CS2 server module loaded):
  1. Ctrl-Alt-S (or Edit > Plugins > CS2 sig maker).
  2. A queue of symbol names is shown (pre-filled with the weaponpaints set) - edit freely.
  3. For each symbol: navigate so the cursor is INSIDE the target function, press YES.
  4. The script finds the true function head, wildcards relocated/variable bytes,
     grows the pattern until it is UNIQUE across all executable segments, and writes:

       bin/<GAMEVER>/<module>/<Symbol>.<platform>.yaml        (pipeline working dir)
       bin_artifacts/<GAMEVER>/<module>/<Symbol>.<platform>.yaml  (durable reuse)

Platform + gamever are inferred from the loaded input file path:
  server.dll -> windows, libserver.so -> linux.
"""

import json
import os
import re

import ida_auto
import ida_bytes
import ida_funcs
import ida_idaapi
import ida_kernwin
import ida_name
import ida_nalt
import ida_segment
import ida_ua
import idautils
import idc

MAX_SIG_BYTES = 128
# a func head sig may run the whole body: twins generated from one template (the
# CCSCustomHudLayout_*ForPlayer setters) differ only at +0x90, past MAX_SIG_BYTES
MAX_FUNC_SIG_BYTES = 512
STEP = 16
MIN_SIG_BYTES = 24

# operand types whose bytes must be wildcarded (relocated/variable content)
MASK_OP_TYPES = {ida_ua.o_displ, ida_ua.o_mem, ida_ua.o_near, ida_ua.o_far, ida_ua.o_imm}

DEFAULT_QUEUE = """CAttributeList_SetOrAddAttributeValueByName
UpdateItemView
CCSPlayerInventory_GetItemInLoadout
CEconItemView_CEconItemView
CEconItemView_operator=
CCSPlayerInventory_SendInventoryUpdateEvent
CCSPlayer_ItemServices_SetWearables
CCSPlayerPawn_SetModelFromClass
CCSPlayerPawn_SetModelFromLoadout
CCSPlayerController_InventoryServices_m_pInventory
CCSPlayerInventory_m_pSOCache
CGCClientSharedObjectCache_m_Owner
CCSPlayer_WeaponServices_DropWeapon"""


def get_target_ea():
    ea = ida_kernwin.get_screen_ea()
    func = ida_funcs.get_func(ea)
    if func:
        return func.start_ea
    return None


def build_pattern(func_ea, length):
    """Return (sig_str, bytes_covered) for the first `length` bytes of the function,
    wildcarding operand bytes of instructions that reference addresses/immediates."""
    out = []
    covered = 0
    ea = func_ea
    while covered < length:
        insn = ida_ua.insn_t()
        size = ida_ua.decode_insn(insn, ea)
        if size <= 0:
            break
        raw = ida_bytes.get_bytes(ea, size) or b"\x00" * size
        masked = [f"{b:02X}" for b in raw]
        for op in insn.ops:
            if op.type == ida_ua.o_void:
                break
            # On x86-64 the displacement/immediate/address operand is the LAST field of
            # the instruction encoding, so masking from offb to the end of the
            # instruction is always sufficient (and never over-masks prior bytes).
            if op.type in MASK_OP_TYPES and op.offb != -1 and op.offb < size:
                for i in range(op.offb, size):
                    masked[i] = "??"
                break
        out.extend(masked)
        covered += size
        ea += size
    return " ".join(out), covered


def count_matches(sig_str):
    """Count occurrences of the wildcarded pattern across all executable segments.
    Pure-Python regex matching over segment bytes - immune to IDA bin_search API churn."""
    parts = sig_str.split()
    rx = re.compile(
        b"".join(b"." if p == "??" else re.escape(bytes([int(p, 16)])) for p in parts),
        re.DOTALL,
    )
    total = 0
    for seg_ea in idautils.Segments():
        seg = ida_segment.getseg(seg_ea)
        if not seg or not (seg.perm & ida_segment.SEGPERM_EXEC):
            continue
        blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
        if not blob:
            continue
        pos = rx.search(blob)
        while pos:
            total += 1
            if total > 1:
                return total
            pos = rx.search(blob, pos.start() + 1)
    return total


def detect_target():
    """Infer (dirs, platform) from the loaded input path, e.g.
    .../CS2_VibeSignatures/bin/14178b/server/server.dll -> windows + [bin/14178b/server,
    bin_artifacts/14178b/server]."""
    input_path = (ida_nalt.get_input_file_path() or "").replace("\\", "/")
    # the gamever segment is whatever directory name bin/ uses, not only <digits><letter>
    m = re.search(r"/bin/([A-Za-z0-9_.\-]+)/(\w+)/([^/]+)$", input_path)
    if not m:
        return None
    gamever, module, binname = m.groups()
    if binname.endswith(".dll"):
        platform = "windows"
    elif binname.endswith(".so"):
        platform = "linux"
    else:
        return None
    repo_root = input_path[: input_path.rfind("/bin/")]
    dirs = [os.path.join(repo_root, "bin", gamever, module)]
    if os.path.isdir(os.path.join(repo_root, "bin_artifacts")):
        dirs.append(os.path.join(repo_root, "bin_artifacts", gamever, module))
    return {
        "dirs": dirs,
        "platform": platform,
        "repo_root": repo_root,
        "gamever": gamever,
        "module": module,
        # bin/ is hydrated from bin_artifacts/, so the queue runner writes only here
        "artifact_dir": os.path.join(repo_root, "bin_artifacts", gamever, module),
    }


# =============================================================================
# Queue runner (headless batch protocol driven by ida_sig_maker_batch.py)
#
# ida_sig_maker_batch.py copies this file in as runner.py, points IDA at it and
# sets CS2_SIG_MAKER_JOB to a job JSON holding {queue, rules, module, platform,
# output_dir, report_path}. Everything below implements that contract; nothing
# here runs on import.
# =============================================================================

SAFE_SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_=:]*$")
# "Foo_m_bar" is a struct member offset, not a function head
MEMBER_NAME_RE = re.compile(r"_m_[A-Za-z0-9]")

_OUTPUT_DIR_OVERRIDE = None
_PLATFORM_OVERRIDE = None


def safe_symbol(name):
    """Reject anything that could escape the artifact directory."""
    text = str(name or "").strip()
    if not text or "/" in text or "\\" in text or ".." in text or os.path.basename(text) != text:
        raise ValueError(f"unsafe symbol name: {name!r}")
    if not SAFE_SYMBOL_RE.match(text):
        raise ValueError(f"unsafe symbol name: {name!r}")
    return text


def parse_queue(text):
    """Queue text -> ordered unique entries, dropping comments and blanks."""
    out, seen = [], set()
    for raw in str(text or "").replace(",", "\n").splitlines():
        entry = raw.split("#", 1)[0].strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out


class Scan:
    """Byte cache over executable segments, with wildcard pattern search.

    Kept as plain (start_va, bytes) regions so matching is pure Python and
    immune to IDA's bin_search API churn.
    """

    def __init__(self):
        self.regions = []
        for seg_ea in idautils.Segments():
            seg = ida_segment.getseg(seg_ea)
            if not seg or not (seg.perm & ida_segment.SEGPERM_EXEC):
                continue
            blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
            if blob:
                self.regions.append((seg.start_ea, blob))

    @staticmethod
    def compile_pattern(sig):
        parts = str(sig).split()
        if not parts:
            raise ValueError("empty pattern")
        if all("?" in part for part in parts):
            raise ValueError(f"pattern is all wildcards, it would match everywhere: {sig!r}")
        return re.compile(
            b"".join(b"." if "?" in part else re.escape(bytes([int(part, 16)])) for part in parts),
            re.DOTALL,
        )

    def matches(self, sig, limit=None):
        """Every match address, including overlapping ones."""
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


def resolve(symbol, rule, scan):
    """Locate a symbol from name and/or pattern evidence.

    Every source must agree: with both kinds present the answer is their
    intersection, so contradictory evidence resolves to nothing rather than
    silently preferring one source.
    """
    found = set()
    for name in [symbol] + list(rule.get("names") or []):
        ea = ida_name.get_name_ea(ida_idaapi.BADADDR, name)
        if ea not in (ida_idaapi.BADADDR, 0, None):
            found.add(ea)
    explicit = parse_ea(rule.get("ea"))
    if explicit is not None:
        # a hand-verified address is evidence like any other: it must agree
        func = ida_funcs.get_func(explicit)
        head = func.start_ea if func else explicit
        found = (found & {head}) if found else {head}
        if not found:
            raise ValueError(f"{symbol}: explicit ea {hex(explicit)} disagrees with the named function")
    pattern = rule.get("pattern")
    if pattern:
        hits = set(scan.matches(pattern))
        candidates = (found & hits) if found else hits
    else:
        candidates = found
    if len(candidates) != 1:
        raise ValueError(f"{symbol}: evidence found {len(candidates)} candidates, need exactly 1")
    head = candidates.pop()
    if head == entry_point_ea():
        raise ValueError(
            f"{symbol}: {hex(head)} is the binary's entry point (_DllMainCRTStartup / _start), "
            f"where IDA opens a database - move the cursor to the real function first"
        )
    return head


def entry_point_ea():
    """The image entry point IDA positions a freshly opened database on."""
    try:
        import ida_ida
        return ida_ida.inf_get_start_ea()
    except Exception:
        try:
            return idc.get_inf_attr(idc.INF_START_EA)
        except Exception:
            return None


def _grow_signature(func_ea, scan, end_ea, pin_low_bytes=0, max_bytes=None):
    """Grow a head signature until unique.

    Relocatable operands are wildcarded from their first byte to the end of the
    instruction. With ``pin_low_bytes`` the low bytes of a 4-byte relocatable
    operand stay visible (the pipeline's own last resort for families of
    identical heads: those bytes move on every rebuild, so callers must say so).
    Growth stops at ``end_ea`` (function end, or None for "until unique").
    """
    tokens, ea = [], func_ea
    while end_ea is None or ea < end_ea:
        insn = ida_ua.insn_t()
        size = ida_ua.decode_insn(insn, ea)
        # stop rather than read bytes that belong to the next function
        if size <= 0 or (end_ea is not None and ea + size > end_ea):
            break
        raw = ida_bytes.get_bytes(ea, size)
        if raw is None:
            raise ValueError(f"Unreadable bytes at {hex(ea)} - refusing to invent them")
        masked = [f"{b:02X}" for b in raw]
        for op in insn.ops:
            if op.type == ida_ua.o_void:
                break
            if op.type in MASK_OP_TYPES and op.offb != -1 and op.offb < size:
                start = op.offb
                if pin_low_bytes and size - op.offb == 4:
                    start = op.offb + pin_low_bytes
                for i in range(start, size):
                    masked[i] = "??"
                break
        tokens.extend(masked)
        ea += size
        if len(scan.matches(" ".join(tokens), limit=2)) == 1:
            return " ".join(tokens)
        if max_bytes is not None and len(tokens) >= max_bytes:
            break
    return None


def signature_ex(func_ea, scan, allow_across_function_boundary=True, allow_pinned=True):
    """(sig, crossed_boundary, pinned_displacements) with the pipeline's fallback ladder.

    1. wildcarded head inside the function (the durable form);
    2. the same pattern continued into padding and the next head, recorded with
       func_sig_allow_across_function_boundary so the relocator keeps the
       displacements wildcarded (CLAUDE.md);
    3. low displacement bytes pinned (what preprocess_common_skill emits for
       families of identical heads such as the point_script bindings). Those
       bytes move on every rebuild, so the caller is told and should prefer a
       string or vtable anchor for the next gamever.
    """
    func = ida_funcs.get_func(func_ea)
    if not func:
        raise ValueError(f"no function defined at {hex(func_ea)}")
    sig = _grow_signature(func_ea, scan, func.end_ea)
    if sig:
        return sig, False, False
    if allow_across_function_boundary:
        sig = _grow_signature(func_ea, scan, None, max_bytes=max(MAX_SIG_BYTES, 4 * MIN_SIG_BYTES))
        if sig:
            return sig, True, False
    if allow_pinned:
        sig = _grow_signature(func_ea, scan, func.end_ea, pin_low_bytes=3)
        if sig:
            print(f"[sig_maker] {hex(func_ea)}: only unique with displacement bytes pinned - fragile across builds")
            return sig, False, True
    raise ValueError(f"No unique signature for {hex(func_ea)} within its function bounds")


def signature(func_ea, scan):
    """Grow a wildcarded head signature until unique, never past the function end."""
    func = ida_funcs.get_func(func_ea)
    if not func:
        raise ValueError(f"no function defined at {hex(func_ea)}")
    sig = _grow_signature(func_ea, scan, func.end_ea)
    if sig:
        return sig
    raise ValueError(f"No unique signature for {hex(func_ea)} within its function bounds")


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


def write_yaml(data, symbol, target):
    """Write one artifact, only ever under bin_artifacts/<gamever>/<module>/."""
    out_dir = _OUTPUT_DIR_OVERRIDE
    if not out_dir:
        if not target:
            raise ValueError("loaded binary is outside bin/<GAMEVER>/<module>/ - nowhere to place the artifact")
        out_dir = target["artifact_dir"]
    platform = _PLATFORM_OVERRIDE or (target or {}).get("platform")
    if not platform:
        raise ValueError("cannot tell the platform: pass it in the job, or load the binary from bin/<GAMEVER>/<module>/")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{safe_symbol(symbol)}.{platform}.yaml")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(render_yaml(data))
    return out_path



# =============================================================================
# Explicit-address hand-off (GUI find -> artifact) and RTTI vtable resolution
#
# The rule keys below let a human (or emit_artifact.py) hand the script an
# address it already trusts, so the script only has to do what it is good at:
# read the current bytes, wildcard what relocates, grow until unique, write the
# schema the pipeline expects. Nothing here guesses an identity.
# =============================================================================

def parse_ea(value):
    """'0x15dab30' / 0x15dab30 / '22981424' -> int; None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text, 0)


def data_regions():
    """(start_va, bytes) for every NON-executable segment; vtables and RTTI live here."""
    out = []
    for seg_ea in idautils.Segments():
        seg = ida_segment.getseg(seg_ea)
        if not seg or (seg.perm & ida_segment.SEGPERM_EXEC):
            continue
        blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
        if blob:
            out.append((seg.start_ea, blob))
    return out


def find_qword_holders(value, regions=None):
    """Addresses in data segments whose qword equals ``value`` (raw scan, no xrefs needed)."""
    needle = int(value).to_bytes(8, "little", signed=False)
    hits = []
    for base, blob in regions or data_regions():
        pos = blob.find(needle)
        while pos != -1:
            hits.append(base + pos)
            pos = blob.find(needle, pos + 1)
    return hits


def is_code_ea(ea):
    seg = ida_segment.getseg(ea)
    return bool(seg and (seg.perm & ida_segment.SEGPERM_EXEC))


def rtti_vtables(class_name):
    """Every vtable address point (slot-0 address) of ``class_name`` via the Itanium RTTI chain.

    typeinfo-name string "<len><Class>" -> typeinfo object (holds a pointer to
    the name at +8) -> vtable (holds a pointer to the typeinfo at slot -1).
    Returns a list of (address_point, offset_to_top); the primary vtable is the
    one with offset_to_top == 0.
    """
    regions = data_regions()
    if (ida_nalt.get_input_file_path() or "").lower().endswith((".dll", ".exe")):
        # MSVC RTTI (TypeDescriptor -> Complete Object Locator -> vtable) lives in the
        # tool-neutral hunt_core, so the emitter and the hunter resolve the same table
        import hunt_core
        import ida_backend
        return hunt_core.msvc_rtti_vtables(ida_backend.IdaBackend(), class_name, regions)
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
                first = ida_bytes.get_qword(address_point)
                if not first or not is_code_ea(first):
                    continue
                offset_to_top = ida_bytes.get_qword(vt_holder - 8)
                out.append((address_point, offset_to_top))
    out.sort(key=lambda item: (item[1] != 0, item[0]))
    return out


def vtable_slot_func(class_name, index):
    """Function pointer held by slot ``index`` of ``class_name``'s primary vtable."""
    tables = [ap for ap, ott in rtti_vtables(class_name) if ott == 0]
    if len(tables) != 1:
        raise ValueError(f"{class_name}: found {len(tables)} primary vtables via RTTI, need exactly 1")
    slot = tables[0] + 8 * int(index)
    func_ea = ida_bytes.get_qword(slot)
    if func_ea in (0, ida_idaapi.BADADDR) or not is_code_ea(func_ea):
        raise ValueError(f"{class_name}: slot {index} at {hex(slot)} does not hold code")
    return func_ea, tables[0]


def vtable_slot_at(slot_ea):
    """(class_name, index) for a cursor ON a vtable slot, walking back to the typeinfo pointer."""
    ea = slot_ea
    for _ in range(4096):
        candidate = ida_bytes.get_qword(ea)
        if candidate and not is_code_ea(candidate):
            # a non-code qword inside the table is the typeinfo pointer (slot -1)
            name_ptr = ida_bytes.get_qword(candidate + 8)
            raw = ida_bytes.get_bytes(name_ptr, 256) if name_ptr else None
            if raw:
                text = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
                digits = ""
                while text and text[0].isdigit():
                    digits, text = digits + text[0], text[1:]
                if digits and len(text) >= int(digits):
                    return text[: int(digits)], (slot_ea - (ea + 8)) // 8
            break
        ea -= 8
    raise ValueError(f"{hex(slot_ea)}: no typeinfo pointer found above this slot - not inside an RTTI vtable?")


def masked_instruction(ea):
    """(masked_tokens, insn) for one instruction with relocatable operands wildcarded."""
    insn = ida_ua.insn_t()
    size = ida_ua.decode_insn(insn, ea)
    if size <= 0:
        raise ValueError(f"cannot decode the instruction at {hex(ea)}")
    raw = ida_bytes.get_bytes(ea, size)
    if raw is None:
        raise ValueError(f"Unreadable bytes at {hex(ea)} - refusing to invent them")
    masked = [f"{b:02X}" for b in raw]
    for op in insn.ops:
        if op.type == ida_ua.o_void:
            break
        if op.type in MASK_OP_TYPES and op.offb != -1 and op.offb < size:
            for i in range(op.offb, size):
                masked[i] = "??"
            break
    return masked, insn, raw


def instruction_signature(ea, scan, pin_first=True, allow_across_function_boundary=False):
    """Grow a signature that STARTS at ``ea`` until unique.

    With ``pin_first`` the first instruction is kept verbatim (a struct offset or
    a patch site has to be identified by its own bytes); later instructions are
    wildcarded like a function head. Growth stops at the function end unless
    ``allow_across_function_boundary`` is set, then it may run into padding and
    the next head (the pipeline flag of the same name records that choice).
    Returns (signature, crossed_boundary).
    """
    func = ida_funcs.get_func(ea)
    end = func.end_ea if func else None
    tokens, cur, crossed = [], ea, False
    while True:
        if end is not None and cur >= end:
            if not allow_across_function_boundary:
                break
            crossed = True
        try:
            masked, insn, raw = masked_instruction(cur)
        except ValueError:
            break
        if pin_first and cur == ea:
            masked = [f"{b:02X}" for b in raw]
        tokens.extend(masked)
        cur += insn.size
        if len(tokens) > MAX_SIG_BYTES * 2:
            break
        if len(scan.matches(" ".join(tokens), limit=2)) == 1:
            return " ".join(tokens), crossed
    raise ValueError(f"No unique signature starting at {hex(ea)}")


def rip_relative_operand(insn, ea):
    """(target_va, disp_offset_in_insn) for the RIP-relative memory operand, or None."""
    for op in insn.ops:
        if op.type == ida_ua.o_void:
            break
        if op.type in (ida_ua.o_mem, ida_ua.o_displ) and op.offb != -1:
            # x86-64 RIP-relative: 4-byte displacement, target = next_ip + disp
            raw = ida_bytes.get_bytes(ea + op.offb, 4)
            if raw is None or len(raw) < 4:
                continue
            disp = int.from_bytes(raw, "little", signed=True)
            target = ea + insn.size + disp
            if op.type == ida_ua.o_mem and op.addr == target:
                return target, op.offb
            if op.type == ida_ua.o_mem and op.addr not in (0, ida_idaapi.BADADDR):
                return op.addr, op.offb
    return None


def displacement_operand(insn, index=None, ea=None):
    """(member offset, operand slot) read from the instruction.

    A [reg+disp] operand gives the offset directly. A member reached by pointer
    arithmetic (`add rdi, 70h ; jmp getter`, the shape of an accessor thunk)
    has it as the immediate of an add/sub/lea, so those are accepted when no
    displacement operand exists.
    """
    slots = [int(index)] if index is not None else range(len(insn.ops))
    for slot in slots:
        op = insn.ops[slot]
        if op.type == ida_ua.o_void:
            break
        if op.type == ida_ua.o_displ and getattr(op, "offb", 0) != -1:
            offset = op.addr & 0xFFFFFFFF
            if offset >= 0x80000000:
                offset -= 0x100000000
            return offset, slot
    mnem = idc.print_insn_mnem(ea) if ea is not None else None
    if mnem in ("add", "sub", "lea"):
        for slot in range(len(insn.ops)):
            op = insn.ops[slot]
            if op.type == ida_ua.o_void:
                break
            if op.type == ida_ua.o_imm and 0 < int(op.value) < 0x10000:
                return int(op.value) * (-1 if mnem == "sub" else 1), slot
    return None


def baseline_artifact(symbol, target=None):
    """Newest previous-gamever artifact for ``symbol`` on this platform, as a dict, or None.

    Prefills what a human should not have to retype: vtable_name, size,
    patch_bytes, struct/member names. Values are hints, never evidence.
    """
    target = target or detect_target()
    if not target:
        return None
    root = os.path.join(target["repo_root"], "bin_artifacts")
    if not os.path.isdir(root):
        return None
    versions = [d for d in os.listdir(root) if d != target["gamever"] and os.path.isdir(os.path.join(root, d))]

    def version_key(name):
        m = re.match(r"^(\d+)([a-z]*)$", name)
        return (int(m.group(1)), m.group(2)) if m else (0, name)

    for version in sorted(versions, key=version_key, reverse=True):
        path = os.path.join(root, version, target["module"], f"{symbol}.{target['platform']}.yaml")
        if os.path.isfile(path):
            data = {}
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if ":" in line and not line.startswith(" "):
                        key, _, value = line.partition(":")
                        data[key.strip()] = value.strip().strip("'\"")
            data["_path"] = path
            return data
    return None


def emit_symbol(symbol, rule, extra, scan):
    """Emit one artifact in the schema its rule asks for."""
    symbol = safe_symbol(symbol)
    rule = rule or {}
    kind = rule.get("kind")
    if not kind:
        if MEMBER_NAME_RE.search(symbol):
            raise ValueError(
                f"{symbol} names a struct member, so it cannot be emitted as a function: give it a "
                f"rule anchored on a typed instruction (kind: structmember, pattern, operand)"
            )
        kind = "func"

    if kind == "structmember":
        pattern = rule.get("pattern")
        ea = parse_ea(rule.get("ea"))
        if ea is None:
            if not pattern:
                raise ValueError(f"{symbol}: structmember rules need a typed instruction pattern or an ea")
            hits = scan.matches(pattern, limit=2)
            if len(hits) != 1:
                raise ValueError(f"{symbol}: pattern found {len(hits)} matches, need exactly 1")
            ea = hits[0]
        if not ida_bytes.is_code(ida_bytes.get_flags(ea)):
            raise ValueError(f"{symbol}: {hex(ea)} is not code")
        insn = ida_ua.insn_t()
        if ida_ua.decode_insn(insn, ea) <= 0:
            raise ValueError(f"{symbol}: cannot decode the instruction at {hex(ea)}")
        found = displacement_operand(insn, rule.get("operand"), ea=ea)
        if found is None:
            raise ValueError(f"{symbol}: operand {rule.get('operand', 0)} at {hex(ea)} has no displacement or add/sub immediate")
        # read the displacement from THIS build, never from the rule
        offset, _ = found
        crossed = False
        if not pattern:
            pattern, crossed = instruction_signature(
                ea, scan, pin_first=True, allow_across_function_boundary=True
            )
        data = {
            "struct_name": rule["struct_name"],
            "member_name": rule["member_name"],
            "offset": hex(offset),
            "size": int(rule.get("size", 4)),
            "offset_sig": pattern,
        }
        if crossed:
            data["offset_sig_allow_across_function_boundary"] = True
        data.update(extra or {})
        return write_yaml(data, symbol, detect_target())

    if kind == "vfunc":
        index = int(rule["index"])
        class_name = rule.get("class")
        if class_name:
            func_ea, address_point = vtable_slot_func(class_name, index)
            return emit_vfunc_yaml(func_ea, symbol, rule.get("vtable_name") or class_name, index, extra, scan=scan)
        anchor = rule.get("address_point_name")
        base = ida_name.get_name_ea(ida_idaapi.BADADDR, anchor) if anchor else None
        if base in (None, ida_idaapi.BADADDR, 0):
            raise ValueError(f"{symbol}: cannot resolve the vtable anchor {anchor!r}")
        slot = base + 8 * index
        func_ea = ida_bytes.get_qword(slot)
        if func_ea in (0, ida_idaapi.BADADDR):
            raise ValueError(f"{symbol}: vtable slot {index} at {hex(slot)} holds no pointer")
        return emit_vfunc_yaml(func_ea, symbol, rule["vtable_name"], index, extra)

    if kind == "gv":
        ea = parse_ea(rule.get("ea"))
        if ea is None:
            pattern = rule.get("pattern")
            if not pattern:
                raise ValueError(f"{symbol}: gv rules need the referencing instruction's ea or a pattern")
            hits = scan.matches(pattern, limit=2)
            if len(hits) != 1:
                raise ValueError(f"{symbol}: pattern found {len(hits)} matches, need exactly 1")
            ea = hits[0]
        masked, insn, raw = masked_instruction(ea)
        found = rip_relative_operand(insn, ea)
        if found is None:
            raise ValueError(f"{symbol}: {hex(ea)} has no RIP-relative operand")
        gv_va, disp_offset = found
        sig, _ = instruction_signature(ea, scan, pin_first=False, allow_across_function_boundary=False)
        data = {
            "gv_name": symbol,
            "gv_va": hex(gv_va),
            "gv_rva": hex(gv_va - ida_nalt.get_imagebase()),
            "gv_sig": sig,
            "gv_sig_va": hex(ea),
            "gv_inst_offset": 0,
            "gv_inst_length": int(insn.size),
            "gv_inst_disp": int(disp_offset),
        }
        data.update(extra or {})
        return write_yaml(data, symbol, detect_target())

    if kind == "patch":
        ea = parse_ea(rule.get("ea"))
        if ea is None:
            raise ValueError(f"{symbol}: patch rules need the ea of the instruction to patch")
        patch_bytes = rule.get("patch_bytes")
        if not patch_bytes:
            raise ValueError(f"{symbol}: patch rules need patch_bytes (what the plugin writes)")
        sig, _ = instruction_signature(ea, scan, pin_first=False, allow_across_function_boundary=False)
        data = {
            "patch_name": symbol,
            "patch_va": hex(ea),
            "patch_rva": hex(ea - ida_nalt.get_imagebase()),
            "patch_sig": sig,
            "patch_bytes": patch_bytes,
        }
        data.update(extra or {})
        return write_yaml(data, symbol, detect_target())

    if kind != "func":
        raise ValueError(f"{symbol}: unknown rule kind {kind!r}")

    ea = resolve(symbol, rule, scan)
    sig, crossed, _pinned = signature_ex(ea, scan)
    func = ida_funcs.get_func(ea)
    data = {
        "func_name": symbol,
        "func_va": hex(ea),
        "func_rva": hex(ea - ida_nalt.get_imagebase()),
        "func_size": hex(func.size()) if func else "0x0",
        "func_sig": sig,
    }
    if crossed:
        data["func_sig_allow_across_function_boundary"] = True
    data.update(extra or {})
    return write_yaml(data, symbol, detect_target())


def run_queue(queue, output_dir=None, module=None, platform=None, report_path=None, rules=None):
    """Work the queue for ONE module/platform and always produce a report."""
    global _OUTPUT_DIR_OVERRIDE, _PLATFORM_OVERRIDE
    ida_auto.auto_wait()
    rules = rules or {}
    _OUTPUT_DIR_OVERRIDE = output_dir
    _PLATFORM_OVERRIDE = platform
    try:
        scan = Scan()
        results = []
        for entry in parse_queue(queue):
            owner, _, name = entry.rpartition("!")
            if owner and module and owner != module:
                continue  # queue entry belongs to another module
            try:
                symbol = safe_symbol(name)
            except ValueError as exc:
                results.append({"symbol": name, "status": "invalid", "reason": str(exc)})
                continue
            try:
                output = emit_symbol(symbol, rules.get(symbol, {}), {}, scan)
                results.append({"symbol": symbol, "status": "ok", "output": output})
            except Exception as exc:
                results.append({"symbol": symbol, "status": "unresolved", "reason": str(exc)})
        report = {
            "module": module,
            "platform": platform,
            "output_dir": output_dir,
            "resolved": sum(1 for r in results if r["status"] == "ok"),
            "results": results,
        }
    finally:
        _OUTPUT_DIR_OVERRIDE = None
        _PLATFORM_OVERRIDE = None
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return report


def run_batch_job():
    """Entry point used when the batch driver sets CS2_SIG_MAKER_JOB."""
    with open(os.environ["CS2_SIG_MAKER_JOB"], "r", encoding="utf-8") as handle:
        job = json.load(handle)
    report = run_queue(
        job.get("queue"),
        output_dir=job.get("output_dir"),
        module=job.get("module"),
        platform=job.get("platform"),
        report_path=job.get("report_path"),
        rules=job.get("rules"),
    )
    print(f"[sig_maker] batch job: {report['resolved']}/{len(report['results'])} resolved")
    # the driver blocks on this process until it exits, so leave now rather than
    # letting it sit until the batch timeout expires
    idc.qexit(0)
    return report


class _SigMakerAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        main()
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


ACTION_ID = "cs2vibe:sig_maker"


def register_action():
    try:
        ida_kernwin.unregister_action(ACTION_ID)
    except Exception:
        pass
    desc = ida_kernwin.action_desc_t(
        ACTION_ID, "CS2 sig maker", _SigMakerAction(), "Ctrl-Alt-D",
        "CS2_VibeSignatures signature/YAML maker", -1,
    )
    ida_kernwin.register_action(desc)
    ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 sig maker", ACTION_ID)


def main(queue=None, output_dir=None, module=None, platform=None, report_path=None, rules=None):
    """Queue runner when given a queue, interactive cursor workflow otherwise."""
    if queue is not None:
        return run_queue(queue, output_dir=output_dir, module=module,
                         platform=platform, report_path=report_path, rules=rules)
    return interactive_main()


def _auto_hunt_first(symbols):
    """(solved symbols, {symbol: best candidate ea}) from the baseline-facts hunter.

    Solved artifacts are written to auto_hunt_out/<gamever>/<module>/ like Ctrl-Alt-H's, for
    review before promotion; a symbol without baseline facts simply falls through to the
    cursor workflow.
    """
    try:
        import ida_auto_hunt
        report = ida_auto_hunt.run(symbols=symbols)
    except Exception as error:
        print(f"[sig_maker] automatic pass skipped: {error}")
        return [], {}
    if not report:
        return [], {}
    solved = [row["symbol"] for row in report.get("solved", [])]
    hints = {}
    for row in report.get("unresolved", []) + report.get("changed", []):
        for candidate in row.get("candidates") or []:
            try:
                hints[row["symbol"]] = int(str(candidate.get("va")), 16)
                break
            except (TypeError, ValueError):
                continue
    return solved, hints


def manual_todo_symbols():
    """Symbols the pipeline left for a person (manual_todo/<gamever>/<module>.<platform>.txt),
    written by ida_analyze_bin when neither its hunter nor an agent could prove them."""
    target = detect_target()
    if not target:
        return [], None
    path = os.path.join(target["repo_root"], "manual_todo", target["gamever"],
                        f"{target['module']}.{target['platform']}.txt")
    if not os.path.isfile(path):
        return [], path
    symbols = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip() and not line.startswith("#"):
                name = line.split()[0]
                if not os.path.isfile(os.path.join(target["artifact_dir"], f"{name}.{target['platform']}.yaml")):
                    symbols.append(name)
    return symbols, path


def interactive_main():
    todo, todo_path = manual_todo_symbols()
    if todo:
        print(f"[sig_maker] {len(todo)} symbol(s) left by the pipeline in {todo_path}")
    text = ida_kernwin.ask_text(16384, "\n".join(todo) if todo else DEFAULT_QUEUE,
                                "Symbols to make (one per line). Edit the list freely:")
    if not text:
        return
    symbols = [s.strip() for s in text.replace(",", "\n").split() if s.strip()]
    if not symbols:
        return

    # 1. automatic first: the baseline-facts hunter (Ctrl-Alt-H's engine and evidence rule)
    #    resolves what it can prove, so only the rest needs a human
    auto_done, hints = _auto_hunt_first(symbols)
    remaining = [s for s in symbols if s not in auto_done]
    if auto_done:
        print(f"[sig_maker] found automatically ({len(auto_done)}): {', '.join(auto_done)}")
    if not remaining:
        print("[sig_maker] every symbol was found automatically - nothing to place by hand")
        return

    done, skipped = [], []
    emitted = {}  # func_ea -> symbol (guard: samme funktion under to navne = naesten altid en fejl)
    for i, symbol in enumerate(remaining, 1):
        hint = hints.get(symbol)
        where = ""
        if hint is not None:
            # 2. the cursor goes to the hunter's best guess, so the question is "is this it?"
            ida_kernwin.jumpto(hint)
            where = (f"The cursor was moved to the hunter's best candidate {hex(hint)} "
                     f"(not proven - check it).\n\n")
        answer = ida_kernwin.ask_yn(
            1,
            f"[{i}/{len(remaining)}] {where}Is the cursor INSIDE the target function of:\n\n"
            f"    {symbol}\n\n"
            f"YES = cursor is in place, make the sig\n"
            f"NO = skip this symbol\n"
            f"Cancel = stop the whole queue",
        )
        if answer == -1:
            print(f"[sig_maker] queue cancelled at {symbol}")
            break
        if answer == 0:
            skipped.append(symbol)
            continue

        func_ea = get_target_ea()
        if func_ea is None:
            cursor = ida_kernwin.get_screen_ea()
            if cursor == ida_idaapi.BADADDR:
                print(f"[sig_maker] no function under cursor for '{symbol}' - skipped")
                skipped.append(symbol)
                continue
            answer = ida_kernwin.ask_yn(
                1,
                f"No IDA function is defined at the cursor ({hex(cursor)}).\n"
                f"Create a function here and continue with '{symbol}'?",
            )
            if answer != 1:
                print(f"[sig_maker] no function under cursor for '{symbol}' - skipped")
                skipped.append(symbol)
                continue
            if not ida_funcs.add_func(cursor):
                print(f"[sig_maker] could not create a function at {hex(cursor)} - skipped")
                skipped.append(symbol)
                continue
            func_ea = ida_funcs.get_func(cursor).start_ea
        if func_ea in emitted:
            answer = ida_kernwin.ask_yn(
                0,
                f"VA {hex(func_ea)} er ALLEREDE emitteret som '{emitted[func_ea]}'.\n"
                f"Er '{symbol}' den SAMME funktion (rename - der laves alias i stedet)?",
            )
            if answer != 1:
                print(f"[sig_maker] {symbol}: samme VA som {emitted[func_ea]} - skipped (flyt cursor!)")
                skipped.append(symbol)
                continue
        if not confirm_identity(func_ea, symbol):
            skipped.append(symbol)
            continue
        if not emit_yaml(func_ea, symbol):
            skipped.append(symbol)
            continue
        emitted[func_ea] = symbol
        done.append(symbol)

    print("=" * 60)
    print(f"[sig_maker] batch finished: {len(done)} made, {len(skipped)} skipped")
    if skipped:
        print("[sig_maker] skipped symbols (rerun the queue for these):")
        for s in skipped:
            print(f"    {s}")
    print("=" * 60)


IDENTITY_MIN_SCORE = 0.5


def verify_identity(func_ea, symbol):
    """(ok, report) - is the function at func_ea plausibly `symbol`? Run before every write.

    A unique signature only proves the bytes occur once; the entry point's signature is
    unique too, and it was written under three different names on windows 14182. Three
    checks, each shown to the user rather than hidden:
      1. never the image entry point (where IDA opens the database);
      2. an artifact already in bin_artifacts at another address is not replaced silently;
      3. the candidate must resemble the previous gamever's function (baseline facts:
         head bytes, mnemonics, size, string set, vcalls) - a low score needs a yes.
    """
    lines = []
    if func_ea == entry_point_ea():
        return False, (f"{hex(func_ea)} is the binary's entry point (CRT startup) - never a game function. "
                       f"Move the cursor to the real function.")
    target = detect_target() or {}
    existing = os.path.join(target.get("artifact_dir", ""), f"{symbol}.{target.get('platform', '')}.yaml")
    if target and os.path.isfile(existing):
        import hunt_core
        old = hunt_core.parse_yaml(existing).get("func_va")
        if old and int(str(old), 16) != func_ea:
            lines.append(f"bin_artifacts already has {symbol} at {old} (this would replace it with {hex(func_ea)})")
    try:
        import hunt_core
        import ida_backend
        _ver, facts = hunt_core.load_baseline_facts(target.get("repo_root", ""), target.get("gamever", ""),
                                                    target.get("module", ""), target.get("platform", ""))
        base = ((facts or {}).get("symbols") or {}).get(symbol)
        if base and (base.get("head") or base.get("mnem")):
            live = hunt_core.FactsBuilder(ida_backend.IdaBackend()).function_facts(func_ea, {})
            score = hunt_core.similarity(base, live) if live else 0.0
            bstr = set(base.get("strings") or [])
            lstr = set((live or {}).get("strings") or [])
            detail = (f"resemblance to the previous build: {score:.2f}"
                      f" | size {hex(base.get('size') or 0)} -> {hex((live or {}).get('size') or 0)}")
            if bstr:
                detail += f" | strings {len(bstr & lstr)}/{len(bstr)}"
            print(f"[sig_maker] {symbol}: {detail}")
            if score < IDENTITY_MIN_SCORE:
                lines.append(f"it does not look like {symbol} did in the previous build ({detail})")
        elif not base:
            print(f"[sig_maker] {symbol}: no baseline facts to compare against - identity unchecked")
    except Exception as error:
        print(f"[sig_maker] {symbol}: identity check unavailable ({error})")
    if lines:
        return None, "\n".join(f"- {line}" for line in lines)
    return True, ""


def confirm_identity(func_ea, symbol):
    """verify_identity with the user deciding the doubtful cases (default: No)."""
    ok, report = verify_identity(func_ea, symbol)
    if ok is True:
        return True
    if ok is False:
        print(f"[sig_maker] {symbol}: refused - {report}")
        ida_kernwin.warning(f"{symbol}: {report}")
        return False
    answer = ida_kernwin.ask_yn(0, f"{symbol} at {hex(func_ea)} looks doubtful:\n\n{report}\n\nWrite it anyway?")
    if answer != 1:
        print(f"[sig_maker] {symbol}: not written ({report.strip()})")
        return False
    return True


def emit_yaml(func_ea, symbol):
    """Write the func artifact; False when no unique signature exists (nothing written)."""
    func = ida_funcs.get_func(func_ea)
    func_size = func.size()

    cap = min(MAX_FUNC_SIG_BYTES, func_size)
    lengths = list(range(MIN_SIG_BYTES, cap, STEP)) + [cap]
    for length in lengths:
        sig_str, covered = build_pattern(func_ea, length)
        if covered < MIN_SIG_BYTES:
            print(f"[sig_maker] Could not decode {MIN_SIG_BYTES} bytes from function head - aborting.")
            return False
        matches = count_matches(sig_str)
        print(f"[sig_maker] {covered} bytes, {matches} match(es)...")
        if matches == 1:
            break
    else:
        print(f"[sig_maker] {symbol}: NOT WRITTEN - no unique signature even over the whole body ({hex(func_size)} bytes);"
              f" an identical twin exists")
        return False

    rva = func_ea - ida_nalt.get_imagebase()
    yaml_block = (
        f"func_name: {symbol}\n"
        f"func_va: '{hex(func_ea)}'\n"
        f"func_rva: '{hex(rva)}'\n"
        f"func_size: '{hex(func_size)}'\n"
        f"func_sig: {sig_str}\n"
    )

    target = detect_target()
    if target:
        for out_dir in target["dirs"]:
            out_path = os.path.join(out_dir, f"{symbol}.{target['platform']}.yaml")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(yaml_block)
            print(f"[sig_maker] written: {out_path}")
        print(f"[sig_maker] UNIQUE {target['platform']} signature for {symbol}:")
        print(yaml_block)
    else:
        print("[sig_maker] UNIQUE signature (input path outside bin/<GAMEVER> - paste manually):")
        print(yaml_block)
    return True


def emit_vfunc_yaml(func_ea, symbol, vtable_name, vfunc_index, extra=None, scan=None):
    """Write a vfunc-schema YAML (vtable slot) for a virtual function.
    Cursor workflow: navigate to the VTABLE SLOT ENTRY (the qword holding the
    function pointer) in IDA and use the driver's cursor variant.

    A unique head signature is added when one exists inside the function: the
    signature tracker compares byte patterns, and a record with an index but no
    pattern cannot be checked. A thunk too small to be unique keeps slot-only
    output, which is correct rather than lazy (CLAUDE.md)."""
    if not ida_funcs.get_func(func_ea):
        if not ida_funcs.add_func(func_ea):
            print(f"[sig_maker] could not create function at {hex(func_ea)}")
            return
    func = ida_funcs.get_func(func_ea)
    vfunc_offset = vfunc_index * 8
    data = {
        "func_name": symbol,
        "func_va": hex(func_ea),
        "func_rva": hex(func_ea - ida_nalt.get_imagebase()),
        "func_size": hex(func.size()),
    }
    try:
        sig, crossed, _pinned = signature_ex(func_ea, scan or Scan())
        data["func_sig"] = sig
        if crossed:
            data["func_sig_allow_across_function_boundary"] = True
    except ValueError as error:
        print(f"[sig_maker] {symbol}: slot-only artifact, {error}")
    data.update({
        "vtable_name": vtable_name,
        "vfunc_offset": hex(vfunc_offset),
        "vfunc_index": int(vfunc_index),
    })
    data.update(extra or {})
    if _OUTPUT_DIR_OVERRIDE or os.environ.get("CS2_SIG_MAKER_JOB"):
        return write_yaml(data, symbol, detect_target())
    yaml_block = render_yaml(data)
    target = detect_target()
    if target:
        for out_dir in target["dirs"]:
            out_path = os.path.join(out_dir, f"{symbol}.{target['platform']}.yaml")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(yaml_block)
            print(f"[sig_maker] written: {out_path}")
        print(f"[sig_maker] vfunc {symbol} (slot {vfunc_index}) -> {target['platform']}")
        print(yaml_block)
    else:
        print("[sig_maker] input path outside bin/<GAMEVER> - YAML blok:")
        print(yaml_block)


def emit_vfunc_from_cursor(symbol, vtable_name, vfunc_index):
    """Cursor must be ON the vtable slot entry (the qword containing the function
    pointer). Reads the pointer, derives vtable start from slot index, emits YAML."""
    import ida_bytes as _b
    slot_ea = ida_kernwin.get_screen_ea()
    if slot_ea == ida_idaapi.BADADDR:
        print("[sig_maker] placér cursor på vtable-slot-entry foerst.")
        return
    func_ea = _b.get_qword(slot_ea)
    if func_ea == ida_idaapi.BADADDR or func_ea == 0:
        print(f"[sig_maker] slot-entry {hex(slot_ea)} indeholder ikke en gyldig pointer.")
        return
    vtable_start = slot_ea - 8 * vfunc_index
    print(f"[sig_maker] slot {vfunc_index} @ {hex(slot_ea)} -> func {hex(func_ea)} (vtable start {hex(vtable_start)})")
    emit_vfunc_yaml(func_ea, symbol, vtable_name, vfunc_index)


def emit_structmember_from_cursor(struct_name, member_name, size=4):
    """Cursor paa en instruktion der tilgaer memberet (fx mov eax, [r13+0x5C]).
    Laeser displacement'en og skriver structmember-YAML."""
    import ida_ua
    ea = ida_kernwin.get_screen_ea()
    insn = ida_ua.insn_t()
    if ida_ua.decode_insn(insn, ea) <= 0:
        print("[sig_maker] kan ikke dekode instruktion under cursor.")
        return
    offset = None
    raw = ida_bytes.get_bytes(ea, insn.size) or b""
    for op in insn.ops:
        if op.type == ida_ua.o_displ and op.offb != -1:
            offset = op.addr & 0xFFFFFFFF
            if offset >= 0x80000000:
                offset -= 0x100000000
            break
    if offset is None or offset <= 0:
        print("[sig_maker] ingen positiv displacement under cursor - placér cursor paa member-adgang.")
        return
    try:
        offset_sig, crossed = instruction_signature(ea, Scan(), pin_first=True, allow_across_function_boundary=True)
    except ValueError as error:
        print(f"[sig_maker] {error} - falling back to the bare instruction bytes (may not be unique)")
        offset_sig, crossed = " ".join(f"{b:02X}" for b in raw), False
    yaml_block = (
        f"struct_name: {struct_name}\n"
        f"member_name: {member_name}\n"
        f"offset: '{hex(offset)}'\n"
        f"size: {size}\n"
        f"offset_sig: {offset_sig}\n"
        + ("offset_sig_allow_across_function_boundary: true\n" if crossed else "")
    )
    target = detect_target()
    if target:
        for out_dir in target["dirs"]:
            out_path = os.path.join(out_dir, f"{struct_name}_{member_name}.{target['platform']}.yaml")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(yaml_block)
            print(f"[sig_maker] written: {out_path}")
        print(f"[sig_maker] structmember {struct_name}.{member_name} = {hex(offset)} ({offset})")
        print(yaml_block)
    else:
        print("[sig_maker] YAML blok (paste manuelt):")
        print(yaml_block)


class _StructMemberAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        struct_name = ida_kernwin.ask_str("CServerSideClient", 0, "Struct/class navn:")
        member_name = ida_kernwin.ask_str("m_member", 1, "Member navn (fx m_NetChannel):")
        if not struct_name or not member_name:
            return
        emit_structmember_from_cursor(struct_name, member_name)
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


def emit_here(symbol=None):
    """One hotkey for every artifact kind, decided by what is under the cursor.

    - cursor on a vtable slot (data qword pointing at code): vfunc; class and
      index come from the RTTI typeinfo pointer above the slot.
    - cursor on an instruction with a [reg+disp] operand: struct member; the
      struct/member names are taken from the symbol (Struct_m_member) and the
      size from the previous gamever's artifact when it exists.
    - cursor on an instruction with a RIP-relative operand: asks gv or func.
    - anything else inside a function: func at the function head.
    The symbol name is asked once; the previous gamever's artifact, when it
    exists, prefills vtable_name / size / patch_bytes.
    """
    ea = ida_kernwin.get_screen_ea()
    if ea == ida_idaapi.BADADDR:
        print("[sig_maker] no address under the cursor")
        return
    func = ida_funcs.get_func(ea)
    if func is not None and func.start_ea == entry_point_ea():
        # IDA opens every database here; an artifact from this spot is DllMain, not the symbol
        print(f"[sig_maker] the cursor is in the entry point {hex(func.start_ea)} (CRT startup) - "
              f"jump to the function you want first (G + address)")
        return
    symbol = symbol or ida_kernwin.ask_str("", 0, "Symbol name (artifact file name):")
    if not symbol:
        return
    symbol = safe_symbol(symbol)
    target = detect_target()
    baseline = baseline_artifact(symbol, target) or {}
    if baseline:
        print(f"[sig_maker] baseline: {baseline.get('_path')}")
    scan = Scan()
    extra = {}
    if not is_code_ea(ea):
        pointer = ida_bytes.get_qword(ea)
        if not pointer or not is_code_ea(pointer):
            print(f"[sig_maker] {hex(ea)} is data but holds no code pointer - not a vtable slot")
            return
        class_name, index = vtable_slot_at(ea)
        vtable_name = baseline.get("vtable_name") or class_name
        print(f"[sig_maker] vtable slot: {class_name}[{index}] -> {hex(pointer)}")
        return emit_vfunc_yaml(pointer, symbol, vtable_name, index, extra, scan=scan)
    insn = ida_ua.insn_t()
    if ida_ua.decode_insn(insn, ea) <= 0:
        print(f"[sig_maker] cannot decode the instruction at {hex(ea)}")
        return
    kind = None
    if MEMBER_NAME_RE.search(symbol) and displacement_operand(insn) is not None:
        kind = "structmember"
    elif rip_relative_operand(insn, ea) is not None:
        choice = ida_kernwin.ask_buttons("gv", "func", "patch", 0, "RIP-relative operand here: emit the global (gv), the function head, or a patch site?")
        kind = {1: "gv", 0: "func", -1: "patch"}.get(choice, "func")
    else:
        func = ida_funcs.get_func(ea)
        if func and func.start_ea != ea:
            choice = ida_kernwin.ask_buttons("func", "patch", "member", 0, "Inside a function: emit the function head, a patch at this instruction, or a struct member?")
            kind = {1: "func", 0: "patch", -1: "structmember"}.get(choice, "func")
        else:
            kind = "func"
    if kind == "structmember":
        struct_name, _, member_name = symbol.partition("_m_")
        member_name = "m_" + member_name
        rule = {
            "kind": "structmember", "ea": ea,
            "struct_name": baseline.get("struct_name") or struct_name,
            "member_name": baseline.get("member_name") or member_name,
            "size": int(baseline.get("size") or 4),
        }
    elif kind == "gv":
        rule = {"kind": "gv", "ea": ea}
    elif kind == "patch":
        patch_bytes = baseline.get("patch_bytes") or ida_kernwin.ask_str("", 0, "patch_bytes the plugin writes (hex, space separated):")
        rule = {"kind": "patch", "ea": ea, "patch_bytes": patch_bytes}
    else:
        rule = {"kind": "func", "ea": ea}
        func = ida_funcs.get_func(ea)
        if func is not None and not confirm_identity(func.start_ea, symbol):
            return None
    out = emit_symbol(symbol, rule, extra, scan)
    print(f"[sig_maker] {kind} {symbol} written: {out}")
    # bin/ is a hydrated copy; keep it in step so the IDA session sees its own output
    if target and out:
        for out_dir in target["dirs"]:
            if os.path.normpath(out_dir) != os.path.normpath(os.path.dirname(out)):
                try:
                    os.makedirs(out_dir, exist_ok=True)
                    with open(out, "r", encoding="utf-8") as src, open(os.path.join(out_dir, os.path.basename(out)), "w", encoding="utf-8") as dst:
                        dst.write(src.read())
                except OSError as error:
                    print(f"[sig_maker] could not mirror into {out_dir}: {error}")
    return out


class _EmitHereAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        try:
            emit_here()
        except Exception as error:
            print(f"[sig_maker] emit failed: {error}")
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


ACTION_ID_EMIT = "cs2vibe:emit_here"
try:
    ida_kernwin.unregister_action(ACTION_ID_EMIT)
except Exception:
    pass
ida_kernwin.register_action(ida_kernwin.action_desc_t(
    ACTION_ID_EMIT, "CS2 emit artifact here", _EmitHereAction(), "Ctrl-Alt-E",
    "Cursor on a function / vtable slot / member access / RIP-relative insn -> artifact YAML", -1,
))
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 emit artifact here", ACTION_ID_EMIT)


ACTION_ID_SM = "cs2vibe:struct_member"
try:
    ida_kernwin.unregister_action(ACTION_ID_SM)
except Exception:
    pass
_desc_sm = ida_kernwin.action_desc_t(
    ACTION_ID_SM, "CS2 struct member emitter", _StructMemberAction(), "Ctrl-Alt-O",
    "Cursor paa member-adgangsinstruktion -> structmember YAML", -1,
)
ida_kernwin.register_action(_desc_sm)
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 struct member emitter", ACTION_ID_SM)

register_action()

# Only act when IDA executes this file directly (-S runner.py sets __name__ to
# "__main__"). Loaded as a plugin, or exec'd by cs2_sig_maker_plugin.py, the
# module must merely define its actions - otherwise a stray CS2_SIG_MAKER_JOB in
# the environment would run the queue a second time and rewrite the report.
if __name__ == "__main__":
    if os.environ.get("CS2_SIG_MAKER_JOB"):
        run_batch_job()
    else:
        main()
