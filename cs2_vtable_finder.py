"""Alt+F7 i IDA (med libserver.so/server.dll loadet).

Finder CCSPlayer_WeaponServices' vtable via RTTI-kæden automatisk:
  typeinfo-navnstreng -> _ZTI objekt -> vtable typeinfo-slot -> vtable-start
og emitter vfunc-YAML for det angivne slot (SelectItem = 31 linux / 30 windows).
"""
import ida_bytes
import ida_funcs
import ida_idaapi
import ida_kernwin
import ida_segment
import idautils

CLASS_NAME = "CCSPlayer_WeaponServices"   # default - spoerges ved koersel
SLOT = 31          # default - spoerges ved koersel (linux: 31, windows: 30)
SYMBOL = "CCSPlayer_WeaponServices_SelectItem"

ns = {"__name__": "cs2vibe_vtable_finder"}
exec(open("/home/mikkel/CS2_VibeSignatures/ida_sig_maker.py").read(), ns)

def find_bytes(needle):
    hits = []
    for seg_ea in idautils.Segments():
        seg = ida_segment.getseg(seg_ea)
        if not seg:
            continue
        blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
        if not blob:
            continue
        pos = blob.find(needle)
        while pos != -1:
            hits.append(seg.start_ea + pos)
            pos = blob.find(needle, pos + 1)
    return hits

def is_code(ea):
    seg = ida_segment.getseg(ea)
    return bool(seg and (seg.perm & ida_segment.SEGPERM_EXEC))

def main():
    global CLASS_NAME, SLOT, SYMBOL
    CLASS_NAME = ida_kernwin.ask_str(CLASS_NAME, 0, "Class name (vtable ejer):") or CLASS_NAME
    SLOT = ida_kernwin.ask_long(SLOT, "vfunc slot index (0-based fra vtable-start):")
    if SLOT is None:
        return
    SYMBOL = ida_kernwin.ask_str(SYMBOL, 1, "Output symbol-navn (YAML-filnavn):") or SYMBOL

    # 1. typeinfo name-string: _ZTS = length-prefixed class name
    ts = f"{len(CLASS_NAME)}{CLASS_NAME}".encode()
    ts_eas = find_bytes(ts)
    if not ts_eas:
        print(f"[vtable] typeinfo-streng '{ts}' ikke fundet - er auto-analysen faerdig?")
        return
    print(f"[vtable] typeinfo-navn: {len(ts_eas)} hit(s): {[hex(e) for e in ts_eas]}")

    # 2. data-references to the string -> _ZTI objects
    ztis = set()
    for ts_ea in ts_eas:
        for ref in idautils.DataRefsTo(ts_ea):
            ztis.add(ref)
    if not ztis:
        # strengen er evt. ikke analyseret som data - proev at oprette qword-refs ved at
        # soege efter pointere til strengen direkte
        ptr_blob = b""
        for seg_ea in idautils.Segments():
            seg = ida_segment.getseg(seg_ea)
            if seg and (seg.perm & ida_segment.SEGPERM_EXEC):
                continue
            blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
            if not blob:
                continue
            pos = blob.find(ts_ea.to_bytes(8, "little"))
            while pos != -1:
                ztis.add(seg.start_ea + pos)
                pos = blob.find(ts_ea.to_bytes(8, "little"), pos + 1)
        print(f"[vtable] (raa pointer-scan) _ZTI kandidater: {len(ztis)}")

    # 3. find vtable typeinfo slots: qwords equal to a _ZTI pointer, located in
    #    non-executable segments (.data.rel.ro). Raw scan - immune to missing xrefs.
    vtable_starts = set()
    for zti in ztis:
        needle = zti.to_bytes(8, "little")
        for seg_ea in idautils.Segments():
            seg = ida_segment.getseg(seg_ea)
            if not seg or (seg.perm & ida_segment.SEGPERM_EXEC):
                continue
            blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
            if not blob or needle not in blob:
                continue
            pos = blob.find(needle)
            while pos != -1:
                vtable_starts.add(seg.start_ea + pos + 8)  # typeinfo ptr = slot -1
                pos = blob.find(needle, pos + 1)
    if not vtable_starts:
        print("[vtable] ingen qword-pointere til _ZTI fundet i data-segmenter.")
        return

    print(f"[vtable] kandidater: {[hex(v) for v in sorted(vtable_starts)]}")

    # 4. validate: slot must point at code; primary vtable has offset-to-top 0 at start-16
    for vt in sorted(vtable_starts):
        func = ida_bytes.get_qword(vt + 8 * SLOT)
        if not func or not is_code(func):
            print(f"  {hex(vt)}: slot {SLOT} peger ikke paa kode ({hex(func) if func else '0'}) - skip")
            continue
        ott = ida_bytes.get_qword(vt - 16)
        size = 0
        f = ida_funcs.get_func(func)
        if f:
            size = f.size()
        print(f"[vtable] CCSPlayer_WeaponServices vtable @ {hex(vt)} (offset-to-top {ott})")
        print(f"  slot {SLOT} -> {hex(func)} (size {hex(size)})")
        for n in (SLOT - 1, SLOT + 1):
            print(f"  nabo slot {n}: {hex(ida_bytes.get_qword(vt + 8 * n))}")
        ns["emit_vfunc_yaml"](func, SYMBOL, CLASS_NAME, SLOT)
        print("[vtable] Windows-side: gentag i server.dll-IDB og saet SLOT = 30.")
        return

class _VtableFinderAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        main()
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


ACTION_ID = "cs2vibe:vtable_finder"


def register_action():
    try:
        ida_kernwin.unregister_action(ACTION_ID)
    except Exception:
        pass
    desc = ida_kernwin.action_desc_t(
        ACTION_ID, "CS2 vtable finder", _VtableFinderAction(), "Ctrl-Alt-V",
        "Find vtable via RTTI og emit vfunc YAML", -1,
    )
    ida_kernwin.register_action(desc)
    ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 vtable finder", ACTION_ID)


register_action()

if __name__ == "__main__":
    main()
