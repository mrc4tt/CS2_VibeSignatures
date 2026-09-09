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

import os
import re

import ida_bytes
import ida_funcs
import ida_idaapi
import ida_kernwin
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
    m = re.search(r"/bin/([0-9]+[a-z]?)/(\w+)/([^/]+)$", input_path)
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
    return {"dirs": dirs, "platform": platform}


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


def main():
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

if __name__ == "__main__":
    main()

    main()

if __name__ == "__main__":
    main()

    main()
