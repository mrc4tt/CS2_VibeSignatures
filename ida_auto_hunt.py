"""
ida_auto_hunt.py — auto-hunt missing artifacts for the LOADED module binary (IDA 9).

Workflow (local PC, parallel with server agent runs):
  1. Run `uv run missing_report.py -gamever <VER>` in the repo first — it writes
     missing_<platform>_<gamever>.txt (the plugin reads it).
  2. Open any module binary (bin/<VER>/<module>/lib*.so or *.dll) in IDA, let
     auto-analysis finish once.
  3. Ctrl-Alt-H. For every missing symbol of THIS module the plugin tries:
       a) SIG RELOCATION — search the newest baseline artifact's func_sig/
          offset_sig in the loaded image (wildcards honored); unique hit → emit.
       b) VTABLE WALK — for vfunc symbols: locate the class vtable via its
          typeinfo-name string (RTTI), read the baseline vfunc_index slot,
          emit with a fresh head signature.
     Whatever it cannot solve automatically is listed as a cursor-queue you can
     finish with Ctrl-Alt-S (batch emitter).

Emits to bin/<VER>/<module>/ AND bin_artifacts/<VER>/<module>/ — same schema as
the pipeline. Commit bin_artifacts afterwards; the next server run skips them.
"""

import glob
import os
import re

import ida_bytes
import ida_kernwin
import ida_nalt
import ida_segment
import idautils
import idc

REPO = None
for cand in ("/home/mikkel/CS2_VibeSignatures", os.path.join(os.path.expanduser("~"), "CS2_VibeSignatures")):
    if os.path.isdir(cand):
        REPO = cand
        break

PLUGIN_HOTKEY = "Ctrl-Alt-H"


def loaded_context():
    path = (ida_nalt.get_input_file_path() or "").replace("\\", "/")
    m = re.search(r"/bin/([0-9]+[a-z]?)/(\w+)/([^/]+)$", path)
    if not m:
        return None
    gamever, module, binname = m.groups()
    platform = "windows" if binname.lower().endswith(".dll") else "linux"
    return gamever, module, platform, path


def parse_yaml_fields(path):
    fields = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"(\w+): '?([^'\n]*)'?", line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def baseline_artifact(repo, module, symbol, platform, gamever):
    """Newest OTHER gamever carrying this symbol's artifact."""
    cands = []
    for d in glob.glob(os.path.join(repo, "bin_artifacts", "*", module)):
        ver = os.path.basename(os.path.dirname(d))
        if ver == gamever:
            continue
        p = os.path.join(d, f"{symbol}.{platform}.yaml")
        if os.path.exists(p):
            cands.append((ver, p))
    if not cands:
        return None
    cands.sort(key=lambda c: (len(c[0]), c[0]))
    ver, p = cands[-1]
    return ver, parse_yaml_fields(p)


def sig_to_data_mask(sig):
    data, mask = bytearray(), bytearray()
    for tok in sig.split():
        if tok in ("?", "??"):
            data.append(0)
            mask.append(0)
        else:
            data.append(int(tok, 16))
            mask.append(0xFF)
    return bytes(data), bytes(mask)


def unique_search(data, mask):
    """Wildcard pattern scan via Python regex over segment bytes — immune to the
    bin_search binding quirks that vary across IDA 9 builds (same fix as
    ida_sig_maker)."""
    import re as _re
    rx = _re.compile(b"".join(
        b"." if m == 0 else _re.escape(bytes([d]))
        for d, m in zip(data, mask)
    ), _re.DOTALL)
    hits = []
    for seg_ea in idautils.Segments():
        seg = ida_segment.getseg(seg_ea)
        if not seg or not (seg.perm & ida_segment.SEGPERM_EXEC):
            continue
        blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
        if not blob:
            continue
        pos = rx.search(blob)
        while pos:
            hits.append(seg.start_ea + pos.start())
            if len(hits) > 1:
                return hits
            pos = rx.search(blob, pos.start() + 1)
    return hits


def head_sig(ea, length=32):
    raw = ida_bytes.get_bytes(ea, length) or b""
    return " ".join(f"{b:02X}" for b in raw)


def find_vtable_slot(class_name, index):
    """Locate <len><class> typeinfo-name string → data refs → vtable → slot func."""
    needle = f"{len(class_name)}{class_name}".encode()
    for seg_ea in idautils.Segments():
        seg = ida_segment.getseg(seg_ea)
        if not seg:
            continue
        blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea) or b""
        pos = blob.find(needle)
        while pos != -1:
            str_ea = seg.start_ea + pos
            if blob[pos + len(needle):pos + len(needle) + 1] == b"\x00":
                for ref in idautils.DataRefsTo(str_ea):
                    for vt_ref in idautils.DataRefsTo(ref):
                        fn = ida_bytes.get_qword(vt_ref + 8 * (index + 1))
                        if fn and ida_segment.getseg(fn) and (ida_segment.getseg(fn).perm & ida_segment.SEGPERM_EXEC):
                            return fn, vt_ref
            pos = blob.find(needle, pos + 1)
    return None, None


def emit(repo, gamever, module, symbol, platform, text):
    for root in ("bin", "bin_artifacts"):
        d = os.path.join(repo, root, gamever, module)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{symbol}.{platform}.yaml"), "w", encoding="utf-8") as f:
            f.write(text)


def run():
    if not REPO:
        print("[auto_hunt] repo ikke fundet"); return
    ctx = loaded_context()
    if not ctx:
        print("[auto_hunt] input-path udenfor bin/<ver>/<modul>/ — åbn en modul-binær"); return
    gamever, module, platform, path = ctx
    listfile = os.path.join(REPO, f"missing_{platform}_{gamever}.txt")
    if not os.path.exists(listfile):
        print(f"[auto_hunt] {os.path.basename(listfile)} mangler — kør: uv run missing_report.py -gamever {gamever}"); return

    targets = []
    for line in open(listfile):
        line = line.strip()
        if not line or "/" not in line:
            continue
        mod, rest = line.split("/", 1)
        if mod == module:
            targets.append(rest.split(" ->")[0].split(" ")[0])
    if not targets:
        print(f"[auto_hunt] ingen manglende for modulet {module} ({platform}) ✓"); return

    base = ida_nalt.get_imagebase()
    solved, queue = [], []
    for symbol in targets:
        bl = baseline_artifact(REPO, module, symbol, platform, gamever)
        if not bl:
            queue.append((symbol, "ingen baseline-artefakt"))
            continue
        ver, f = bl
        sig = f.get("func_sig") or f.get("offset_sig")
        done = False
        if sig and "?" in sig or sig:
            data, mask = sig_to_data_mask(sig)
            hits = unique_search(data, mask)
            if len(hits) == 1:
                va = hits[0]
                text = (f"func_name: {symbol}\nfunc_va: '{hex(va)}'\nfunc_rva: '{hex(va - base)}'\n"
                        f"func_size: '{f.get('func_size', '0x0')}'\nfunc_sig: {sig}\n")
                emit(REPO, gamever, module, symbol, platform, text)
                solved.append((symbol, f"reloc {ver} @ {hex(va)}"))
                done = True
        if not done and f.get("vtable_name") and f.get("vfunc_index"):
            fn, vt = find_vtable_slot(f["vtable_name"], int(f["vfunc_index"]))
            if fn:
                text = (f"func_name: {symbol}\nfunc_va: '{hex(fn)}'\nfunc_rva: '{hex(fn - base)}'\n"
                        f"func_size: '0x0'\nfunc_sig: {head_sig(fn)}\n"
                        f"vtable_name: {f['vtable_name']}\nvfunc_offset: '{hex(int(f['vfunc_index']) * 8)}'\n"
                        f"vfunc_index: {f['vfunc_index']}\n")
                emit(REPO, gamever, module, symbol, platform, text)
                solved.append((symbol, f"vtable {f['vtable_name']}[{f['vfunc_index']}] @ {hex(fn)}"))
                done = True
        if not done:
            queue.append((symbol, f"baseline {ver} matchede ikke"))

    print("=" * 66)
    print(f"[auto_hunt] {module}/{platform} ({gamever}): {len(targets)} manglende")
    for s, how in solved:
        print(f"  ✓ AUTO  {s} — {how}")
    for s, why in queue:
        print(f"  ✗ KØ   {s} ({why}) — brug Ctrl-Alt-D batch")
    print("=" * 66)
    print(f"[auto_hunt] husk: git add bin_artifacts/{gamever}/{module}")


class _AutoHuntAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        run()
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


ACTION_ID = "cs2vibe:auto_hunt"
try:
    ida_kernwin.unregister_action(ACTION_ID)
except Exception:
    pass
_desc = ida_kernwin.action_desc_t(
    ACTION_ID, "CS2 auto-hunt missing symbols", _AutoHuntAction(), PLUGIN_HOTKEY,
    "Auto-relocate/vtable-hunt missing artifacts for the loaded module", -1,
)
ida_kernwin.register_action(_desc)
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 auto-hunt", ACTION_ID)

if __name__ == "__main__":
    run()
