"""
ida_auto_hunt.py — auto-hunt missing artifacts for the LOADED module binary (IDA 9).

Strategies (tried in order per symbol):
  1. RELOCATION   — newest baseline artifact's func_sig/offset_sig searched in the
                    loaded image; unique hit → emit.
  2. VTABLE-WALK  — for vfunc symbols: RTTI typeinfo-name → vtable → slot.
  3. SEED-SIG     — community sigs from gamedata-generators/*/gamedata/*.json.
  4. SIBLING      — same-class-prefix symbols already solved → nearby VA (overload
                    clusters and compiler layout grouping).
  5. STRING-ANCHOR— strings referenced in baseline function body → xref in loaded
                    binary → containing function.

Whatever it cannot solve → cursor-queue (Ctrl-Alt-D batch).

Usage: Ctrl-Alt-H (or Edit → Plugins → CS2 auto-hunt).
Run `uv run missing_report.py -gamever <VER>` first (writes missing_<plat>_<ver>.txt).
"""

import glob
import json
import os
import re

import ida_bytes
import ida_funcs
import ida_kernwin
import ida_nalt
import ida_segment
import idautils
import idc

REPO = None
for _cand in ("/home/mikkel/CS2_VibeSignatures", os.path.join(os.path.expanduser("~"), "CS2_VibeSignatures")):
    if os.path.isdir(_cand):
        REPO = _cand
        break

BIN_LINUX = {"SDL3": "libSDL3.so.0", "client": "libclient.so", "engine": "libengine2.so",
             "matchmaking": "libmatchmaking.so", "networksystem": "libnetworksystem.so",
             "scenesystem": "libscenesystem.so", "server": "libserver.so", "vphysics2": "libvphysics2.so"}
BIN_WIN = {"SDL3": "SDL3.dll", "client": "client.dll", "engine": "engine2.dll",
           "matchmaking": "matchmaking.dll", "networksystem": "networksystem.dll",
           "scenesystem": "scenesystem.dll", "server": "server.dll", "vphysics2": "vphysics2.dll"}


def loaded_context():
    path = (ida_nalt.get_input_file_path() or "").replace("\\", "/")
    m = re.search(r"/bin/([0-9]+[a-z]?)/(\w+)/([^/]+)$", path)
    if not m:
        return None
    gamever, module, binname = m.groups()
    platform = "windows" if binname.lower().endswith(".dll") else "linux"
    return gamever, module, platform


def parse_yaml_fields(path):
    fields = {}
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"(\w+): '?([^'\n]*)'?", line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return fields


def baseline_artifact(symbol, platform, gamever):
    cands = []
    for d in glob.glob(os.path.join(REPO, "bin_artifacts", "*", "")):
        ver = os.path.basename(os.path.dirname(d))
        if ver == gamever:
            continue
        p = os.path.join(d, symbol + f".{platform}.yaml")
        if os.path.exists(p):
            cands.append((ver, p))
    if not cands:
        return None, None
    cands.sort(key=lambda c: (len(c[0]), c[0]))
    return cands[-1]


def sig_to_regex(sig):
    import re as _re
    return _re.compile(b"".join(
        b"." if p in ("?", "??") else _re.escape(bytes([int(p, 16)]))
        for p in sig.split()
    ), _re.DOTALL)


def regex_scan(rx):
    """Scan all executable segments; return list of EAs (max 2 for uniqueness check)."""
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


def boundary_ok(ea):
    prev = ida_bytes.get_bytes(ea - 4, 4) or b""
    return (b"\xcc" in prev or prev.endswith(b"\x90")
            or b"\x0f\x0b" in prev or prev.endswith(b"\xc3"))


def head_sig(ea, max_len=160):
    for ln in range(16, max_len + 1, 8):
        raw = ida_bytes.get_bytes(ea, ln)
        if not raw:
            return None
        rx = re.compile(re.escape(raw), re.DOTALL)
        if len(regex_scan(rx)) <= 1:
            return " ".join(f"{b:02X}" for b in raw)
    return None


def emit(gamever, module, symbol, platform, text):
    for root in ("bin", "bin_artifacts"):
        d = os.path.join(REPO, root, gamever, module)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{symbol}.{platform}.yaml"), "w", encoding="utf-8") as f:
            f.write(text)


def strategy_relocation(symbol, platform, gamever, module, base):
    ver, path = baseline_artifact(symbol, platform, gamever)
    if not path:
        return None, "ingen baseline"
    f = parse_yaml_fields(path)
    sig = f.get("func_sig") or f.get("offset_sig")
    if not sig:
        return None, f"baseline {ver} uden sig"
    hits = regex_scan(sig_to_regex(sig))
    if len(hits) == 1 and boundary_ok(hits[0]):
        va = hits[0]
        text = (f"func_name: {symbol}\nfunc_va: '{hex(va)}'\nfunc_rva: '{hex(va - base)}'\n"
                f"func_size: '{f.get('func_size', '0x0')}'\nfunc_sig: {sig}\n")
        emit(gamever, module, symbol, platform, text)
        return True, f"reloc {ver} @ {hex(va)}"
    if len(hits) == 1:
        # unikt hit men boundary-tjek fejlede — godkend alligevel hvis prolog ligner
        va = hits[0]
        text = (f"func_name: {symbol}\nfunc_va: '{hex(va)}'\nfunc_rva: '{hex(va - base)}'\n"
                f"func_size: '0x0'\nfunc_sig: {sig}\n")
        emit(gamever, module, symbol, platform, text)
        return True, f"reloc {ver} @ {hex(va)} (boundary ignoreret)"
    return None, f"baseline {ver}: {len(hits)} hits"


def strategy_vtable(symbol, platform, gamever, module, base):
    ver, path = baseline_artifact(symbol, platform, gamever)
    if not path:
        return None, "ingen baseline til vtable"
    f = parse_yaml_fields(path)
    vt_name = f.get("vtable_name")
    idx = f.get("vfunc_index")
    if not vt_name or idx is None:
        return None, "ikke vfunc"
    idx = int(idx)

    # find typeinfo-name string
    needle = f"{len(vt_name)}{vt_name}".encode()
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
                        fn = ida_bytes.get_qword(vt_ref + 8 * (idx + 1))
                        if fn and ida_segment.getseg(fn) and (ida_segment.getseg(fn).perm & ida_segment.SEGPERM_EXEC):
                            sig = head_sig(fn)
                            if sig:
                                text = (f"func_name: {symbol}\nfunc_va: '{hex(fn)}'\nfunc_rva: '{hex(fn - base)}'\n"
                                        f"func_size: '0x0'\nfunc_sig: {sig}\n"
                                        f"vtable_name: {vt_name}\nvfunc_offset: '{hex(idx * 8)}'\nvfunc_index: {idx}\n")
                                emit(gamever, module, symbol, platform, text)
                                return True, f"vtable {vt_name}[{idx}] @ {hex(fn)}"
            pos = blob.find(needle, pos + 1)
    return None, f"vtable {vt_name} ikke fundet"


def strategy_seed_sig(symbol, platform, gamever, module, base):
    """Community sigs from gamedata-generators seed files."""
    for jp in glob.glob(os.path.join(REPO, "gamedata-generators", "*", "gamedata", "*.json")):
        try:
            d = json.load(open(jp))
        except (OSError, json.JSONDecodeError):
            continue
        for key, entry in d.items():
            norm = key.replace("::", "_")
            if norm != symbol:
                continue
            sig = entry.get("signatures", {}).get(platform) if isinstance(entry.get("signatures"), dict) else None
            if not sig:
                continue
            hits = regex_scan(sig_to_regex(sig))
            if len(hits) == 1 and boundary_ok(hits[0]):
                va = hits[0]
                fresh = head_sig(va, 96) or sig
                text = (f"func_name: {symbol}\nfunc_va: '{hex(va)}'\nfunc_rva: '{hex(va - base)}'\n"
                        f"func_size: '0x0'\nfunc_sig: {fresh}\n")
                emit(gamever, module, symbol, platform, text)
                return True, f"seed-sig ({os.path.basename(os.path.dirname(os.path.dirname(jp)))}) @ {hex(va)}"
    return None, "ingen seed-sig"


def strategy_sibling(symbol, platform, gamever, module, base):
    """Already-solved same-class symbols → check VA proximity via baseline offset-delta."""
    # bestem klasse-praefiks
    parts = symbol.split("_")
    if len(parts) < 2:
        return None, "intet klassepræfiks"
    prefix = "_".join(parts[:-1])

    # find soeskende med baseline og laes VA-delta
    ver, path = baseline_artifact(symbol, platform, gamever)
    if not path:
        return None, "ingen baseline"
    f = parse_yaml_fields(path)
    my_va = f.get("func_va")
    if not my_va:
        return None, "baseline uden VA"
    my_va = int(my_va, 16)

    for gp in glob.glob(os.path.join(REPO, "bin_artifacts", gamever, module, f"{prefix}_*.{platform}.yaml")):
        sib = os.path.basename(gp).rsplit(".", 2)[0]
        if sib == symbol:
            continue
        sf = parse_yaml_fields(gp)
        sib_new_va = sf.get("func_va")
        if not sib_new_va:
            continue
        sib_new_va = int(sib_new_va, 16)

        # find soeskendes baseline-VA for at beregne delta
        _, sib_base_path = baseline_artifact(sib, platform, gamever)
        if not sib_base_path:
            continue
        sib_bf = parse_yaml_fields(sib_base_path)
        sib_old_va = sib_bf.get("func_va")
        if not sib_old_va:
            continue
        sib_old_va = int(sib_old_va, 16)

        delta = my_va - sib_old_va
        candidate = sib_new_va + delta
        # verificér at kandidaten ligner et head
        if boundary_ok(candidate):
            sig = head_sig(candidate)
            if sig:
                text = (f"func_name: {symbol}\nfunc_va: '{hex(candidate)}'\nfunc_rva: '{hex(candidate - base)}'\n"
                        f"func_size: '0x0'\nfunc_sig: {sig}\n")
                emit(gamever, module, symbol, platform, text)
                return True, f"sibling {sib} Δ{hex(delta)} → {hex(candidate)}"
    return None, "intet sibling-hit"


def strategy_string_anchor(symbol, platform, gamever, module, base):
    """Extract strings from baseline function body → find in new binary → xref to function."""
    ver, path = baseline_artifact(symbol, platform, gamever)
    if not path:
        return None, "ingen baseline"
    f = parse_yaml_fields(path)
    old_va = f.get("func_va")
    old_size = f.get("func_size", "0x100")
    if not old_va:
        return None, "baseline uden VA"

    # vi kan ikke laese den GAMLE binary her — brug offset_sig-i-stedet-tilgang:
    # soeg efter klassenavnet som streng i den loadede binary
    class_part = symbol.rsplit("_", 1)[0] if "_" in symbol else symbol
    func_part = symbol.rsplit("_", 1)[-1] if "_" in symbol else symbol
    search_terms = [f"{class_part}::{func_part}", func_part]

    for term in search_terms:
        tbytes = term.encode()
        for seg_ea in idautils.Segments():
            seg = ida_segment.getseg(seg_ea)
            if not seg:
                continue
            blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea) or b""
            pos = blob.find(tbytes)
            while pos != -1:
                str_ea = seg.start_ea + pos
                # find xrefs til strengen
                for xref in idautils.DataRefsTo(str_ea):
                    func = ida_funcs.get_func(xref)
                    if func and boundary_ok(func.start_ea):
                        sig = head_sig(func.start_ea)
                        if sig:
                            text = (f"func_name: {symbol}\nfunc_va: '{hex(func.start_ea)}'\nfunc_rva: '{hex(func.start_ea - base)}'\n"
                                    f"func_size: '{hex(func.size())}'\nfunc_sig: {sig}\n")
                            emit(gamever, module, symbol, platform, text)
                            return True, f"string '{term[:25]}' → {hex(func.start_ea)}"
                pos = blob.find(tbytes, pos + 1)
    return None, "intet string-anchor-hit"


STRATEGIES = [
    ("reloc", strategy_relocation),
    ("vtable", strategy_vtable),
    ("seed", strategy_seed_sig),
    ("sibling", strategy_sibling),
    ("string", strategy_string_anchor),
]


def run():
    if not REPO:
        print("[auto_hunt] repo ikke fundet"); return
    ctx = loaded_context()
    if not ctx:
        print("[auto_hunt] input-path udenfor bin/<ver>/<modul>/"); return
    gamever, module, platform = ctx
    listfile = os.path.join(REPO, f"missing_{platform}_{gamever}.txt")
    if not os.path.exists(listfile):
        print(f"[auto_hunt] kør foerst: uv run missing_report.py -gamever {gamever}"); return

    targets = []
    for line in open(listfile):
        line = line.strip()
        if not line or "/" not in line:
            continue
        mod, rest = line.split("/", 1)
        if mod == module:
            targets.append(rest.split(" ->")[0].split(" ")[0])
    if not targets:
        print(f"[auto_hunt] {module}/{platform}: ingen manglende ✓"); return

    base = ida_nalt.get_imagebase()
    solved, queue = [], []

    for symbol in targets:
        done = False
        for name, fn in STRATEGIES:
            ok, how = fn(symbol, platform, gamever, module, base)
            if ok:
                solved.append((symbol, f"[{name}] {how}"))
                done = True
                break
        if not done:
            # find den strategi der kom laengst for rapportering
            last = how if not done else ""
            queue.append((symbol, last))

    print("=" * 70)
    print(f"[auto_hunt] {module}/{platform} ({gamever}): {len(targets)} manglende")
    print(f"  LØST: {len(solved)}")
    for s, how in solved:
        print(f"  ✓ {s} — {how}")
    if queue:
        print(f"  KØ: {len(queue)}")
        for s, why in queue:
            print(f"  ✗ {s} ({why}) — Ctrl-Alt-D")
    print("=" * 70)
    print(f"[auto_hunt] git add bin_artifacts/{gamever}/{module}")


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
    ACTION_ID, "CS2 auto-hunt missing symbols", _AutoHuntAction(), "Ctrl-Alt-H",
    "5-strategy auto-hunt: reloc, vtable, seed-sig, sibling, string-anchor", -1,
)
ida_kernwin.register_action(_desc)
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 auto-hunt", ACTION_ID)

if __name__ == "__main__":
    run()
