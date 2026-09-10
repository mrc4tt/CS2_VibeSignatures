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
    pattern = rule.get("pattern")
    if pattern:
        hits = set(scan.matches(pattern))
        candidates = (found & hits) if found else hits
    else:
        candidates = found
    if len(candidates) != 1:
        raise ValueError(f"{symbol}: evidence found {len(candidates)} candidates, need exactly 1")
    return candidates.pop()


def signature(func_ea, scan):
    """Grow a wildcarded head signature until unique, never past the function end."""
    func = ida_funcs.get_func(func_ea)
    if not func:
        raise ValueError(f"no function defined at {hex(func_ea)}")
    tokens, ea = [], func_ea
    while ea < func.end_ea:
        insn = ida_ua.insn_t()
        size = ida_ua.decode_insn(insn, ea)
        # stop rather than read bytes that belong to the next function
        if size <= 0 or ea + size > func.end_ea:
            break
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
        tokens.extend(masked)
        ea += size
        if len(scan.matches(" ".join(tokens), limit=2)) == 1:
            return " ".join(tokens)
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
    platform = (target or {}).get("platform") or "unknown"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{safe_symbol(symbol)}.{platform}.yaml")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(render_yaml(data))
    return out_path


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
        if not pattern:
            raise ValueError(f"{symbol}: structmember rules need a typed instruction pattern")
        hits = scan.matches(pattern, limit=2)
        if len(hits) != 1:
            raise ValueError(f"{symbol}: pattern found {len(hits)} matches, need exactly 1")
        ea = hits[0]
        if not ida_bytes.is_code(ida_bytes.get_flags(ea)):
            raise ValueError(f"{symbol}: {hex(ea)} is not code")
        insn = ida_ua.insn_t()
        if ida_ua.decode_insn(insn, ea) <= 0:
            raise ValueError(f"{symbol}: cannot decode the instruction at {hex(ea)}")
        op = insn.ops[int(rule.get("operand", 0))]
        if op.type != ida_ua.o_displ:
            raise ValueError(f"{symbol}: operand {rule.get('operand', 0)} at {hex(ea)} has no displacement")
        # read the displacement from THIS build, never from the rule
        offset = op.addr & 0xFFFFFFFF
        if offset >= 0x80000000:
            offset -= 0x100000000
        data = {
            "struct_name": rule["struct_name"],
            "member_name": rule["member_name"],
            "offset": hex(offset),
            "size": int(rule.get("size", 4)),
            "offset_sig": pattern,
        }
        data.update(extra or {})
        return write_yaml(data, symbol, detect_target())

    if kind == "vfunc":
        index = int(rule["index"])
        anchor = rule.get("address_point_name")
        base = ida_name.get_name_ea(ida_idaapi.BADADDR, anchor) if anchor else None
        if base in (None, ida_idaapi.BADADDR, 0):
            raise ValueError(f"{symbol}: cannot resolve the vtable anchor {anchor!r}")
        slot = base + 8 * index
        func_ea = ida_bytes.get_qword(slot)
        if func_ea in (0, ida_idaapi.BADADDR):
            raise ValueError(f"{symbol}: vtable slot {index} at {hex(slot)} holds no pointer")
        return emit_vfunc_yaml(func_ea, symbol, rule["vtable_name"], index, extra)

    if kind != "func":
        raise ValueError(f"{symbol}: unknown rule kind {kind!r}")

    ea = resolve(symbol, rule, scan)
    sig = signature(ea, scan)
    func = ida_funcs.get_func(ea)
    data = {
        "func_name": symbol,
        "func_va": hex(ea),
        "func_rva": hex(ea - ida_nalt.get_imagebase()),
        "func_size": hex(func.size()) if func else "0x0",
        "func_sig": sig,
    }
    data.update(extra or {})
    return write_yaml(data, symbol, detect_target())


def run_queue(queue, output_dir=None, module=None, platform=None, report_path=None, rules=None):
    """Work the queue for ONE module/platform and always produce a report."""
    global _OUTPUT_DIR_OVERRIDE
    ida_auto.auto_wait()
    rules = rules or {}
    _OUTPUT_DIR_OVERRIDE = output_dir
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


def interactive_main():
    text = ida_kernwin.ask_text(16384, DEFAULT_QUEUE,
                                "Symbols to make (one per line). Edit the list freely:")
    if not text:
        return
    symbols = [s.strip() for s in text.replace(",", "\n").split() if s.strip()]
    if not symbols:
        return

    done, skipped = [], []
    emitted = {}  # func_ea -> symbol (guard: samme funktion under to navne = naesten altid en fejl)
    for i, symbol in enumerate(symbols, 1):
        answer = ida_kernwin.ask_yn(
            1,
            f"[{i}/{len(symbols)}] Navigate so the cursor is INSIDE the target function of:\n\n"
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
        emit_yaml(func_ea, symbol)
        emitted[func_ea] = symbol
        done.append(symbol)

    print("=" * 60)
    print(f"[sig_maker] batch finished: {len(done)} made, {len(skipped)} skipped")
    if skipped:
        print("[sig_maker] skipped symbols (rerun the queue for these):")
        for s in skipped:
            print(f"    {s}")
    print("=" * 60)


def emit_yaml(func_ea, symbol):
    func = ida_funcs.get_func(func_ea)
    func_size = func.size()

    length = MIN_SIG_BYTES
    while length <= min(MAX_SIG_BYTES, func_size):
        sig_str, covered = build_pattern(func_ea, length)
        if covered < MIN_SIG_BYTES:
            print(f"[sig_maker] Could not decode {MIN_SIG_BYTES} bytes from function head - aborting.")
            return
        matches = count_matches(sig_str)
        print(f"[sig_maker] {covered} bytes, {matches} match(es)...")
        if matches == 1:
            break
        length += STEP
    else:
        print("[sig_maker] Signature still not unique at max length - consider fewer wildcards or a longer pattern.")
        return

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


def emit_vfunc_yaml(func_ea, symbol, vtable_name, vfunc_index):
    """Write a vfunc-schema YAML (vtable slot) for a virtual function.
    Cursor workflow: navigate to the VTABLE SLOT ENTRY (the qword holding the
    function pointer) in IDA and use the driver's cursor variant."""
    if not ida_funcs.get_func(func_ea):
        if not ida_funcs.add_func(func_ea):
            print(f"[sig_maker] could not create function at {hex(func_ea)}")
            return
    func = ida_funcs.get_func(func_ea)
    vfunc_offset = vfunc_index * 8
    yaml_block = (
        f"func_name: {symbol}\n"
        f"func_va: '{hex(func_ea)}'\n"
        f"func_rva: '{hex(func_ea - ida_nalt.get_imagebase())}'\n"
        f"func_size: '{hex(func.size())}'\n"
        f"vtable_name: {vtable_name}\n"
        f"vfunc_offset: '{hex(vfunc_offset)}'\n"
        f"vfunc_index: {vfunc_index}\n"
    )
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
    offset_sig = " ".join(f"{b:02X}" for b in raw)
    yaml_block = (
        f"struct_name: {struct_name}\n"
        f"member_name: {member_name}\n"
        f"offset: '{hex(offset)}'\n"
        f"size: {size}\n"
        f"offset_sig: {offset_sig}\n"
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


ACTION_ID_SM = "cs2vibe:struct_member"
try:
    ida_kernwin.unregister_action(ACTION_ID_SM)
except Exception:
    pass
_desc_sm = ida_kernwin.action_desc_t(
    ACTION_ID_SM, "CS2 struct member emitter", _StructMemberAction(), "Ctrl-Alt-M",
    "Cursor paa member-adgangsinstruktion -> structmember YAML", -1,
)
ida_kernwin.register_action(_desc_sm)
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 struct member emitter", ACTION_ID_SM)

register_action()

# A batch job takes precedence: the driver runs this file as __main__ with
# CS2_SIG_MAKER_JOB set and waits for the report it writes.
if os.environ.get("CS2_SIG_MAKER_JOB"):
    run_batch_job()
elif __name__ == "__main__":
    main()
