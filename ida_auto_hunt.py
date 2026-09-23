"""ida_auto_hunt.py - resolve every missing artifact of the LOADED binary, no cursor involved.

Ctrl-Alt-H in IDA (or `uv run auto_hunt_ida.py ...` headless on a copy of the IDB).

For each artifact the previous gamever has and this one lacks, the hunter tries,
in order, and VERIFIES every candidate against the baseline facts before it
emits (baseline_facts/<prev>/<module>.<platform>.json, from baseline_facts.py):

  reloc     the baseline signature still lands exactly once
  vtable    RTTI vtable of the class, with the SLOT SHIFT MEASURED by aligning the
            baseline vtable neighbourhood against the new one (never the old index)
  strings   the baseline function's own string set, voted across referencing functions
  callgraph the N-th direct call (or tail jump) inside a caller that is already resolved
            on this build, and functions that call the same resolved callees
  neighbour the function between the nearest already-resolved neighbours, by similarity

Verification is a similarity score over masked head bytes, mnemonic sequence,
size ratio and string overlap; a candidate needs the score or two independent
strategies agreeing. Struct members, globals and patches are located inside
their OWNER function (resolved the same way) by instruction shape near the
baseline ordinal; a patch whose instruction changed shape is reported, never
emitted. Emission goes through ida_sig_maker.emit_symbol, so the output is the
same YAML the hotkeys and the CLI produce. Whatever remains is listed with its
best candidates and the reason, so a human starts from a shortlist, not from zero.
"""
import difflib
import json
import os
import re

import ida_bytes
import ida_funcs
import ida_idaapi
import ida_kernwin
import ida_nalt
import ida_segment
import idautils
import idc

REPO = None
for _cand in (os.environ.get("CS2VIBE_REPO"), os.path.join(os.path.expanduser("~"), "CS2_VibeSignatures"),
              "/home/mikkel/CS2_VibeSignatures", "/root/CS2_VibeSignatures"):
    if _cand and os.path.isdir(_cand):
        REPO = _cand
        break

MIN_SCORE = 0.55
GENERIC_STRINGS = {"%s", "%d", "true", "false", "undefined", "count", "slot%d"}

_NS = {}


def _load(script):
    if script not in _NS:
        ns = {"__name__": "cs2_auto_hunt_" + script[:-3]}
        with open(os.path.join(REPO, script), "r", encoding="utf-8") as handle:
            exec(compile(handle.read(), script, "exec"), ns)
        _NS[script] = ns
    return _NS[script]


def version_key(name):
    m = re.match(r"^(\d+)([a-z]*)$", name)
    return (int(m.group(1)), m.group(2)) if m else (0, name)


def loaded_context():
    path = (ida_nalt.get_input_file_path() or "").replace("\\", "/")
    m = re.search(r"/bin/([A-Za-z0-9_.\-]+)/(\w+)/([^/]+)$", path)
    if not m:
        return None
    gamever, module, binname = m.groups()
    return gamever, module, ("windows" if binname.lower().endswith(".dll") else "linux")


def parse_yaml(path):
    data = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if ":" in line and not line.startswith((" ", "#")):
                key, _, value = line.partition(":")
                data[key.strip()] = value.strip().strip("'\"")
    return data


def to_int(value):
    if value in (None, ""):
        return None
    text = str(value)
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def is_code(ea):
    seg = ida_segment.getseg(ea)
    return bool(seg and (seg.perm & ida_segment.SEGPERM_EXEC))


# ----------------------------------------------------------------------------- similarity

def token_match(a, b):
    """Fraction of compared positions that agree, '??' matching anything."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    ok = sum(1 for x, y in zip(a[:n], b[:n]) if x == "??" or y == "??" or x == y)
    return ok / n


def similarity(base, live):
    """0..1 how much a live function looks like the baseline entry."""
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


# ----------------------------------------------------------------------------- hunter

class Hunter:
    def __init__(self, gamever, module, platform, facts, out_dir, dry_run=False, min_score=MIN_SCORE, log=print):
        self.gamever, self.module, self.platform = gamever, module, platform
        self.facts = facts
        self.out_dir = out_dir
        self.dry_run = dry_run
        self.min_score = min_score
        self.log = log
        self.sm = _load("ida_sig_maker.py")
        # every emitter in ida_sig_maker writes through write_yaml when these are set,
        # never through the GUI path that mirrors into bin/ and bin_artifacts/ itself
        self.sm["_OUTPUT_DIR_OVERRIDE"] = out_dir
        self.sm["_PLATFORM_OVERRIDE"] = platform
        self.bf = _load("ida_baseline_facts.py")
        self.live = self.bf["Facts"](self.sm)
        self.scan = self.sm["Scan"]()
        self.resolved = {}       # symbol -> va on THIS build (existing artifacts + this session's finds)
        self.resolved_va = {}    # va -> symbol
        self._vt_cache = {}
        self._live_cache = {}
        self._string_cache = {}
        self.report = {"solved": [], "unresolved": [], "changed": [], "skipped": []}
        for name in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
            if name.endswith(f".{platform}.yaml"):
                rec = parse_yaml(os.path.join(out_dir, name))
                va = to_int(rec.get("func_va"))
                if va is not None:
                    symbol = name[: -len(f".{platform}.yaml")]
                    self.resolved[symbol] = va
                    self.resolved_va.setdefault(va, symbol)

    # -- live facts ---------------------------------------------------------------
    def live_facts(self, ea):
        func = ida_funcs.get_func(ea)
        if not func:
            return None
        if func.start_ea not in self._live_cache:
            self._live_cache[func.start_ea] = self.live.function_facts(func.start_ea, self.resolved_va)
        return self._live_cache[func.start_ea]

    def score(self, base, ea):
        live = self.live_facts(ea)
        return similarity(base, live) if live else 0.0

    # -- strategies (return list of (va, how)) ------------------------------------
    def s_reloc(self, symbol, base, artifact):
        sig = artifact.get("func_sig")
        if not sig:
            return []
        hits = self.scan.matches(sig, limit=2)
        return [(hits[0], "reloc")] if len(hits) == 1 else []

    def s_headreloc(self, symbol, base, artifact):
        """The baseline's masked head, grown token by token until it lands once on this build."""
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

    def s_calleeheads(self, symbol, base, artifact):
        """Relocate the baseline's unnamed callees by head, then vote for functions calling them."""
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
            for xref in idautils.CodeRefsTo(target, 0):
                func = ida_funcs.get_func(xref)
                if func:
                    votes[func.start_ea] = votes.get(func.start_ea, 0) + 1
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        if not ranked:
            return []
        top, count = ranked[0]
        if count < max(2, len(located) // 2) or (len(ranked) > 1 and ranked[1][1] == count):
            return []
        return [(top, f"callee-heads {count}/{len(located)}")]

    def vtable_live(self, class_name):
        if class_name in self._vt_cache:
            return self._vt_cache[class_name]
        rtti = class_name[: -len("_vtable")] if class_name.endswith("_vtable") else class_name
        tables = [ap for ap, ott in self.sm["rtti_vtables"](rtti) if ott == 0]
        slots = []
        if len(tables) == 1:
            ap = tables[0]
            for index in range(1024):
                fn = ida_bytes.get_qword(ap + 8 * index)
                if not fn or not is_code(fn):
                    break
                slots.append(fn)
        self._vt_cache[class_name] = (tables[0] if len(tables) == 1 else None, slots)
        return self._vt_cache[class_name]

    def measure_shift(self, class_name, index):
        """Best shift aligning the baseline vtable neighbourhood onto the live vtable."""
        base_vt = (self.facts.get("vtables") or {}).get(class_name) or {}
        base_slots = base_vt.get("slots") or []
        ap, live_slots = self.vtable_live(class_name)
        if ap is None or not base_slots or not live_slots:
            return None, "vtable not resolvable"
        best = (None, -1)
        for shift in range(-12, 13):
            agree = total = 0
            for i in range(max(0, index - 8), min(len(base_slots), index + 9)):
                j = i + shift
                if not (0 <= j < len(live_slots)):
                    continue
                total += 1
                live_head = self.live.masked_head(live_slots[j], limit=16)
                if token_match(base_slots[i][1], live_head) >= 0.9:
                    agree += 1
            if total and agree > best[1]:
                best = (shift, agree)
        shift, agree = best
        if shift is None or agree < 3:
            return None, f"neighbourhood agreement too low ({agree})"
        return shift, f"shift {shift:+d} ({agree} neighbours agree)"

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
        # a slot may hold a null-check thunk in front of the real body; follow one jmp
        target = fn
        if idc.print_insn_mnem(fn) == "test" and idc.print_insn_mnem(idc.next_head(fn)) in ("jz", "je"):
            after = idc.next_head(idc.next_head(fn))
            if idc.print_insn_mnem(after) == "jmp":
                target = idc.get_operand_value(after, 0)
        self._vt_index = new_index
        return [(target, f"vtable {class_name}[{new_index}] {why}")]

    def string_refs(self, text):
        if text in self._string_cache:
            return self._string_cache[text]
        needle = text.encode("utf-8", "replace")
        funcs = set()
        for seg_ea in idautils.Segments():
            seg = ida_segment.getseg(seg_ea)
            if not seg or (seg.perm & ida_segment.SEGPERM_EXEC):
                continue
            blob = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea) or b""
            pos = blob.find(needle)
            while pos != -1:
                str_ea = seg.start_ea + pos
                if pos == 0 or blob[pos - 1] == 0:
                    for xref in idautils.XrefsTo(str_ea, 0):
                        func = ida_funcs.get_func(xref.frm)
                        if func:
                            funcs.add(func.start_ea)
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
        need = min(2, len(strings))
        if count < need or (len(ranked) > 1 and ranked[1][1] == count):
            return []
        return [(top, f"strings {count}/{len(strings)}")]

    def s_callgraph(self, symbol, base, artifact):
        out = []
        for caller in base.get("callers") or []:
            name, ordinal = caller.get("name"), caller.get("ordinal")
            if not name or ordinal is None or name not in self.resolved:
                continue
            live_caller = ida_funcs.get_func(self.resolved[name])
            if not live_caller:
                continue
            calls = self.live.direct_calls(live_caller)
            if not calls:
                continue
            # same ordinal first, then the nearest ones when a call was added/removed
            for k in (ordinal, ordinal - 1, ordinal + 1):
                if 0 <= k < len(calls):
                    out.append((calls[k][1], f"callgraph {name}#{k}"))
        callees = [c["name"] for c in (base.get("callees") or []) if c.get("name") in self.resolved]
        if callees:
            votes = {}
            for name in callees[:6]:
                for xref in idautils.CodeRefsTo(self.resolved[name], 0):
                    func = ida_funcs.get_func(xref)
                    if func:
                        votes[func.start_ea] = votes.get(func.start_ea, 0) + 1
            for fn, count in sorted(votes.items(), key=lambda kv: -kv[1])[:3]:
                if count >= min(2, len(callees)):
                    out.append((fn, f"calls {count} known callees"))
        return out

    def s_neighbour(self, symbol, base, artifact):
        va = to_int(base.get("va"))
        if va is None:
            return []
        base_syms = sorted(((to_int(e.get("va")), n) for n, e in self.facts["symbols"].items()
                            if e.get("va") and n in self.resolved and e.get("category") in ("func", "vfunc")), key=lambda t: t[0])
        before = [t for t in base_syms if t[0] < va]
        after = [t for t in base_syms if t[0] > va]
        if not before or not after:
            return []
        lo, hi = self.resolved[before[-1][1]], self.resolved[after[0][1]]
        if hi <= lo or hi - lo > 0x40000:
            return []
        best = []
        ea = ida_funcs.get_next_func(lo)
        while ea and ea.start_ea < hi:
            best.append((self.score(base, ea.start_ea), ea.start_ea))
            ea = ida_funcs.get_next_func(ea.start_ea)
        best.sort(reverse=True)
        return [(fn, f"neighbour score {s:.2f}") for s, fn in best[:2] if s >= self.min_score]

    # -- resolution ---------------------------------------------------------------
    def resolve_function(self, symbol, base, artifact):
        """(va, how, score, candidates) for a func/vfunc entry."""
        candidates = []
        for strat in (self.s_reloc, self.s_headreloc, self.s_vtable, self.s_strings, self.s_callgraph, self.s_calleeheads, self.s_neighbour):
            try:
                for va, how in strat(symbol, base, artifact):
                    func = ida_funcs.get_func(va)
                    if not func:
                        continue
                    head = func.start_ea
                    candidates.append((head, how, self.score(base, head)))
            except Exception as error:
                self.log(f"    {strat.__name__} failed: {error}")
        if not candidates:
            return None, "no candidate", 0.0, []
        by_va = {}
        for va, how, sc in candidates:
            by_va.setdefault(va, {"how": [], "score": sc})["how"].append(how)
        ranked = sorted(by_va.items(), key=lambda kv: (len(kv[1]["how"]), kv[1]["score"]), reverse=True)
        va, info = ranked[0]
        agree = len(info["how"])
        if agree >= 2 and info["score"] >= 0.35 or info["score"] >= self.min_score:
            return va, " + ".join(info["how"]), info["score"], ranked
        return None, f"best {hex(va)} score {info['score']:.2f} via {info['how'][0]}", info["score"], ranked

    def find_site(self, owner_va, base, exact_bytes=False):
        """Instruction inside the resolved owner that matches the baseline site.

        Match on the register-agnostic instruction shape (mnemonic, operand kinds,
        small immediates) plus the shapes of the surrounding instructions, then the
        nearest ordinal. ``exact_bytes`` (patches) additionally demands the very
        same bytes: a patch is defined by what it overwrites.
        Returns (ea, context_agreement) or (None, best_agreement).
        """
        func = ida_funcs.get_func(owner_va)
        if not func:
            return None, 0.0
        items = list(idautils.FuncItems(func.start_ea))
        ordinal = base.get("site_ordinal") or 0
        want_shape, want_ctx, want_raw = base.get("site_shape"), base.get("site_context") or [], base.get("site_raw") or []
        want_mnem, want_head = base.get("site_mnem"), base.get("site_head") or []
        scored, best_ctx = [], 0.0
        for i, ea in enumerate(items):
            if want_shape:
                if self.bf["Facts"].insn_shape(ea) != want_shape:
                    continue
            elif idc.print_insn_mnem(ea) != want_mnem:
                continue
            try:
                masked, insn, raw = self.sm["masked_instruction"](ea)
            except ValueError:
                continue
            if exact_bytes and want_raw and [f"{b:02X}" for b in raw] != want_raw:
                continue
            if not want_shape and token_match(want_head, masked) < 0.99:
                continue
            live_ctx = self.live.context_shapes(func, ea)
            agree = (sum(1 for a, b in zip(want_ctx, live_ctx) if a == b) / len(want_ctx)) if want_ctx else 1.0
            best_ctx = max(best_ctx, agree)
            distance = abs(i - ordinal) / max(len(items), 1)
            scored.append((-agree, distance, ea))
        scored.sort()
        if not scored:
            return None, best_ctx
        # a single instruction of this exact shape in the owner is an identification on its
        # own (a distinctive immediate such as 100.0f); several need the context to agree
        if len(scored) == 1 and want_shape:
            return scored[0][2], max(-scored[0][0], 0.51)
        good = [row for row in scored if -row[0] >= 0.5]
        return (good[0][2], -good[0][0]) if good else (None, best_ctx)

    def s_thunk(self, owner):
        """A tiny owner that tail-jumps: find thunks of the same shape whose target looks like the baseline target."""
        target = owner.get("thunk_target")
        head = owner.get("head") or []
        if not target or not head:
            return []
        pattern = " ".join(head[:6])
        out = []
        for ea in self.scan.matches(pattern, limit=400):
            func = ida_funcs.get_func(ea)
            if not func or func.start_ea != ea or func.size() > 32:
                continue
            last = None
            for item in idautils.FuncItems(ea):
                last = item
            if last is None or idc.print_insn_mnem(last) != "jmp":
                continue
            jt = idc.get_operand_value(last, 0)
            if not ida_funcs.get_func(jt):
                continue
            sc = self.score(target, jt)
            if sc >= self.min_score:
                out.append((sc, ea, jt))
        out.sort(reverse=True)
        if not out or (len(out) > 1 and out[0][0] - out[1][0] < 0.05):
            return []
        return [(out[0][1], f"thunk -> target score {out[0][0]:.2f}")]

    def resolve_owner(self, base):
        owner = base.get("owner")
        if not owner:
            return None, "no owner function in baseline"
        name = self.resolved_va_by_baseline(owner.get("va"))
        if name and name in self.resolved:
            return self.resolved[name], f"owner {name}"
        if owner.get("thunk_target"):
            found = self.s_thunk(owner)
            if found:
                return found[0][0], f"owner via {found[0][1]}"
        va, how, score, _ = self.resolve_function("(owner)", owner, {})
        return va, (f"owner via {how}" if va else how)

    def resolved_va_by_baseline(self, base_va):
        va = to_int(base_va)
        for name, entry in self.facts["symbols"].items():
            if to_int(entry.get("va")) == va and entry.get("category") in ("func", "vfunc"):
                return name
        return None

    def emit(self, symbol, rule):
        if self.dry_run:
            return f"(dry-run) {rule}"
        out = self.sm["emit_symbol"](symbol, rule, {}, self.scan)
        # bin/ mirrors bin_artifacts/ so the IDA session sees its own output - only
        # when writing to the real artifact directory, never from a scratch outdir
        real = os.path.join(REPO, "bin_artifacts", self.gamever, self.module)
        if out and os.path.normpath(self.out_dir) == os.path.normpath(real):
            try:
                mirror = os.path.join(REPO, "bin", self.gamever, self.module)
                if os.path.isdir(mirror):
                    with open(out, "r", encoding="utf-8") as src, open(os.path.join(mirror, os.path.basename(out)), "w", encoding="utf-8") as dst:
                        dst.write(src.read())
            except OSError:
                pass
        return out

    def hunt(self, symbol, base, artifact):
        category = base.get("category", "func")
        if category == "vtable":
            self.report["skipped"].append({"symbol": symbol, "why": "vtable artifacts come from their own task"})
            return
        if category in ("func", "vfunc"):
            va, how, score, ranked = self.resolve_function(symbol, base, artifact)
            if va is None:
                self.report["unresolved"].append({"symbol": symbol, "category": category, "why": how,
                                                  "candidates": [{"va": hex(v), "score": round(i["score"], 2), "how": i["how"]} for v, i in ranked[:4]]})
                return
            if category == "vfunc":
                class_name = base.get("vtable_name")
                shift, _ = self.measure_shift(class_name, base.get("vfunc_index"))
                if shift is None:
                    self.report["unresolved"].append({"symbol": symbol, "category": category, "why": f"function found at {hex(va)} but the {class_name} slot could not be measured", "candidates": [{"va": hex(va), "score": round(score, 2), "how": [how]}]})
                    return
                index = base["vfunc_index"] + shift
                rule = {"kind": "vfunc", "class": class_name[: -len("_vtable")] if class_name.endswith("_vtable") else class_name,
                        "index": index, "vtable_name": class_name}
            else:
                rule = {"kind": "func", "ea": va}
            out = self.emit(symbol, rule)
            self.resolved[symbol] = va
            self.resolved_va.setdefault(va, symbol)
            self.report["solved"].append({"symbol": symbol, "category": category, "va": hex(va), "how": how, "score": round(score, 2), "output": out})
            return
        # site-based kinds: locate the owner, then the instruction
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
            found = self.bf["Facts"] and None
            rule = {"kind": "structmember", "ea": site, "struct_name": base.get("struct_name"), "member_name": base.get("member_name"), "size": base.get("size") or 4}
        elif category == "gv":
            rule = {"kind": "gv", "ea": site}
        else:
            rule = {"kind": "patch", "ea": site, "patch_bytes": base.get("patch_bytes")}
        out = self.emit(symbol, rule)
        self.report["solved"].append({"symbol": symbol, "category": category, "va": hex(site), "how": f"{how}, site shape+context {agree:.2f}", "output": out})

    def run(self, symbols=None):
        have = {n[: -len(f".{self.platform}.yaml")] for n in os.listdir(self.out_dir)} if os.path.isdir(self.out_dir) else set()
        targets = [s for s in self.facts["symbols"] if s not in have and (not symbols or s in symbols)]
        self.log(f"[auto_hunt] {self.module}/{self.platform} {self.gamever}: {len(targets)} missing vs {self.facts.get('gamever')}")
        base_dir = os.path.join(REPO, "bin_artifacts", self.facts.get("gamever", ""), self.module)
        # functions first so call-graph and neighbour strategies see them; then sites
        order = sorted(targets, key=lambda s: 0 if self.facts["symbols"][s].get("category") in ("func", "vfunc") else 1)
        for n, symbol in enumerate(order, 1):
            base = self.facts["symbols"][symbol]
            path = os.path.join(base_dir, f"{symbol}.{self.platform}.yaml")
            artifact = parse_yaml(path) if os.path.isfile(path) else {}
            try:
                self.hunt(symbol, base, artifact)
            except Exception as error:
                self.report["unresolved"].append({"symbol": symbol, "category": base.get("category"), "why": f"error: {error}", "candidates": []})
            if n % 25 == 0:
                self.log(f"[auto_hunt] {n}/{len(order)} ... solved {len(self.report['solved'])}")
        return self.report


def print_report(report, log=print):
    log("=" * 78)
    log(f"[auto_hunt] solved {len(report['solved'])}, unresolved {len(report['unresolved'])}, changed {len(report['changed'])}, skipped {len(report['skipped'])}")
    for row in report["solved"]:
        log(f"  OK   {row['category']:12} {row['symbol']:55} {row['va']:12} {row['how']}")
    for row in report["changed"]:
        log(f"  CHG  {row['category']:12} {row['symbol']:55} {row['why']}")
    for row in report["unresolved"]:
        cands = ", ".join(f"{c['va']}({c.get('score', '?')})" for c in row.get("candidates", [])[:3])
        log(f"  ??   {row['category']:12} {row['symbol']:55} {row['why']}" + (f"  candidates: {cands}" if cands else ""))
    log("=" * 78)


def facts_for(gamever, module, platform):
    root = os.path.join(REPO, "baseline_facts")
    if not os.path.isdir(root):
        return None, None
    versions = sorted((d for d in os.listdir(root) if version_key(d) < version_key(gamever)), key=version_key, reverse=True)
    for version in versions:
        path = os.path.join(root, version, f"{module}.{platform}.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                return version, json.load(handle)
    return None, None


def run(symbols=None, dry_run=False, out_dir=None, report_path=None, min_score=MIN_SCORE, log=print):
    if not REPO:
        log("[auto_hunt] repo not found (set CS2VIBE_REPO)"); return None
    ctx = loaded_context()
    if not ctx:
        log("[auto_hunt] load the binary from bin/<gamever>/<module>/"); return None
    gamever, module, platform = ctx
    baseline, facts = facts_for(gamever, module, platform)
    if not facts:
        log(f"[auto_hunt] no baseline facts: run  uv run baseline_facts.py -gamever <prev> -module {module} -platform {platform}")
        return None
    out_dir = out_dir or os.path.join(REPO, "bin_artifacts", gamever, module)
    os.makedirs(out_dir, exist_ok=True)
    hunter = Hunter(gamever, module, platform, facts, out_dir, dry_run=dry_run, min_score=min_score, log=log)
    report = hunter.run(symbols)
    report.update({"gamever": gamever, "baseline": baseline, "module": module, "platform": platform})
    print_report(report, log)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return report


def run_batch_job():
    with open(os.environ["CS2_AUTO_HUNT_JOB"], "r", encoding="utf-8") as handle:
        job = json.load(handle)
    import ida_auto
    ida_auto.auto_wait()
    try:
        run(symbols=job.get("symbols"), dry_run=job.get("dry_run", False), out_dir=job.get("out_dir"),
            report_path=job.get("report_path"), min_score=job.get("min_score", MIN_SCORE))
    finally:
        idc.qexit(0)


class _AutoHuntAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        try:
            run()
        except Exception as error:
            print(f"[auto_hunt] failed: {error}")
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


ACTION_ID = "cs2vibe:auto_hunt"
try:
    ida_kernwin.unregister_action(ACTION_ID)
except Exception:
    pass
ida_kernwin.register_action(ida_kernwin.action_desc_t(
    ACTION_ID, "CS2 auto-hunt (baseline facts)", _AutoHuntAction(), "Ctrl-Alt-H",
    "Resolve every missing artifact of the loaded binary, verified against baseline facts", -1,
))
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 auto-hunt (baseline facts)", ACTION_ID)

if __name__ == "__main__" and os.environ.get("CS2_AUTO_HUNT_JOB"):
    run_batch_job()
