#!/usr/bin/env python3
"""Check that every relocated function still references its own anchor string.

Relocation reuses the previous gamever's func_sig and accepts it when it matches
exactly once. A sig that outlives its function keeps matching uniquely - in a
DIFFERENT function - and nothing downstream complains: validate_artifacts and
verify_plugin_gamedata only re-scan the sig. That is how
CBasePlayerController_HandleCommand_JoinTeam.linux sat on the wrong function from
14182 to 14188 and crashed MatchZy servers.

Most finders already name the string their function references (FUNC_XREFS
xref_strings) or a byte pattern inside it (xref_signatures). This audit reads those
specs straight from the preprocessor scripts (ast, nothing imported), takes each
artifact's func_va/func_size and checks in the raw binary that one of the strings is
referenced from inside the function (or a cold chunk it jumps to), or that every
pattern matches inside it. The body runs at least as far as its control flow goes,
so a stored func_size that is too short does not call the right function wrong.
When several scripts produce one artifact (-noinline / -inlined, a -linux variant),
any one of them holding is enough. Deterministic and IDA-free; the run applies the
same judgement to every fresh relocation (relocation_verdict).

Verdicts:
  OK    an anchor string is referenced inside the function, or - for an anchor that is a
        schema field name (m_*) - the function accesses that member at the schema's offset
  BAD   the strings are referenced in the binary, but never from this function (or a
        byte pattern matches elsewhere in the code but not inside it)
  WARN  the anchor is referenced only from functions the finder excludes, and no schema
        member proves the identity instead
  SKIP  cannot be judged (no artifact, no binary, string or code reference not found)

  uv run audit_xref_identity.py -gamever 14188
  uv run audit_xref_identity.py -gamever 14188 -platform linux -symbol JoinTeam -v

Exit status: 0 when nothing is BAD, 1 otherwise, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import ast
import glob
import os
import re
import struct
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREPROCESSOR_DIR = os.path.join(SCRIPT_DIR, "ida_preprocessor_scripts")
PE_IMAGE_BASE = 0x180000000
COLD_CHUNK_LIMIT = 0x2000

# rip-relative lea r64, [rip+disp32]: REX.W (48) or REX.WR (4C), 8D, modrm mod=00 rm=101
LEA_RIP = re.compile(rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]")
# near jmp rel32 / jcc rel32 - how a hot body reaches its .cold chunk
JMP_REL32 = re.compile(rb"\xe9|\x0f[\x80-\x8f]")


# --- finder specs ------------------------------------------------------------------------


def load_specs(symbol_filter: str | None):
    """{func_name: {platform: {"strings": [...], "exclude": [...]}}} from the preprocessor scripts.

    Reads FUNC_XREFS and FUNC_XREFS_BY_PLATFORM ({platform: [...]}) with ast, nothing
    imported. Platform rules mirror how the scripts are scheduled:
      - a script named ...-linux / ...-windows only speaks for that platform, and when
        such a script exists for a symbol it replaces the generic one there (TraceAttack
        is found by string on windows but by call graph on linux);
      - FUNC_XREFS_BY_PLATFORM keys pick the platform themselves;
      - inline_alias specs are skipped, and an ...-inlined script only ever counts as an
        alternative to the symbol's own finder: its anchor lives in the function the
        body was inlined into, which is the artifact on some builds and not on others.
    The resolved map is keyed by the concrete platform; "*" entries are folded in last.
    """
    raw: dict[str, dict[str, list[dict]]] = {}
    specific: dict[str, set[str]] = {}
    unreadable = []

    def add(spec_list, platform, script_platform, source, inlined):
        for spec in spec_list or []:
            if not isinstance(spec, dict):
                continue
            name = spec.get("func_name")
            if not name:
                continue
            if symbol_filter and symbol_filter.lower() not in name.lower():
                continue
            if script_platform != "*" and not inlined:
                specific.setdefault(name, set()).add(script_platform)
            if spec.get("inline_alias"):
                continue
            strings = [x for x in spec.get("xref_strings") or [] if isinstance(x, str) and x]
            signatures = [x for x in spec.get("xref_signatures") or [] if isinstance(x, str) and x]
            if not strings and not signatures:
                continue
            raw.setdefault(name, {}).setdefault(platform, []).append({
                "strings": strings,
                "signatures": signatures,
                "exclude": [x for x in spec.get("exclude_strings") or [] if isinstance(x, str) and x],
                "source": source,
                "inlined": inlined,
            })

    for path in sorted(glob.glob(os.path.join(PREPROCESSOR_DIR, "find-*.py"))):
        stem = os.path.basename(path)[: -len(".py")]
        # an -inlined script finds the function a body was inlined INTO; it only ever
        # vouches for an artifact as an alternative to the symbol's own finder
        inlined = "inlined" in stem and "noinline" not in stem
        script_platform = "linux" if "-linux" in stem else "windows" if "-windows" in stem else "*"
        try:
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        except SyntaxError:
            unreadable.append(path)
            continue
        found = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("FUNC_XREFS", "FUNC_XREFS_BY_PLATFORM"):
                    try:
                        found[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        found.setdefault(target.id, None)
        if isinstance(found.get("FUNC_XREFS_BY_PLATFORM"), dict):
            for platform, spec_list in found["FUNC_XREFS_BY_PLATFORM"].items():
                add(spec_list, platform, platform, stem, inlined)
        elif "FUNC_XREFS_BY_PLATFORM" in found:
            unreadable.append(path)
        if isinstance(found.get("FUNC_XREFS"), list):
            add(found["FUNC_XREFS"], script_platform, script_platform, stem, inlined)
        elif "FUNC_XREFS" in found and "FUNC_XREFS_BY_PLATFORM" not in found:
            unreadable.append(path)

    specs: dict[str, dict[str, list[dict]]] = {}
    for name, per_platform in raw.items():
        for platform in ("linux", "windows"):
            own = [e for e in per_platform.get(platform, []) if not e["inlined"]]
            generic = [e for e in per_platform.get("*", []) if not e["inlined"]]
            if platform in specific.get(name, set()):
                chosen = own
            else:
                chosen = own or generic
            if not chosen:
                continue  # only -inlined specs: their string lives in the caller
            alternatives = [e for key in (platform, "*") for e in per_platform.get(key, []) if e["inlined"]]
            specs.setdefault(name, {})[platform] = chosen + alternatives
    return specs, unreadable


# --- binaries ----------------------------------------------------------------------------


class Binary:
    """Raw bytes plus VA mapping, its rip-relative lea table and its jmp/jcc table."""

    def __init__(self, path: str, platform: str):
        self.path = path
        self.platform = platform
        with open(path, "rb") as handle:
            self.data = handle.read()
        self.segments = list(self._segments())  # (va, size, file_off, executable)
        self._lea_targets = None

    def _segments(self):
        data = self.data
        if self.platform == "linux":
            phoff = struct.unpack_from("<Q", data, 0x20)[0]
            entsize, count = struct.unpack_from("<HH", data, 0x36)
            for i in range(count):
                off = phoff + i * entsize
                p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from("<IIQQQQ", data, off)
                if p_type == 1:
                    yield p_vaddr, p_filesz, p_offset, bool(p_flags & 1)
        else:
            pe = struct.unpack_from("<I", data, 0x3C)[0]
            count = struct.unpack_from("<H", data, pe + 6)[0]
            opt_size = struct.unpack_from("<H", data, pe + 20)[0]
            sec = pe + 24 + opt_size
            for i in range(count):
                off = sec + i * 40
                _name, _vsize, rva, raw_size, raw_ptr = struct.unpack_from("<8sIIII", data, off)
                flags = struct.unpack_from("<I", data, off + 36)[0]
                yield PE_IMAGE_BASE + rva, raw_size, raw_ptr, bool(flags & 0x20000000)

    def va_to_off(self, va: int):
        for seg_va, size, off, _x in self.segments:
            if seg_va <= va < seg_va + size:
                return va - seg_va + off
        return None

    def off_to_va(self, off: int):
        for seg_va, size, seg_off, _x in self.segments:
            if seg_off <= off < seg_off + size:
                return off - seg_off + seg_va
        return None

    def lea_targets(self) -> dict[int, list[int]]:
        """{target_va: [instruction_va, ...]} for every rip-relative lea in executable code."""
        if self._lea_targets is None:
            table: dict[int, list[int]] = {}
            data = self.data
            for seg_va, size, seg_off, executable in self.segments:
                if not executable:
                    continue
                chunk = data[seg_off : seg_off + size]
                for match in LEA_RIP.finditer(chunk):
                    pos = match.start()
                    if pos + 7 > len(chunk):
                        continue
                    disp = struct.unpack_from("<i", chunk, pos + 3)[0]
                    insn_va = seg_va + pos
                    table.setdefault(insn_va + 7 + disp, []).append(insn_va)
            self._lea_targets = table
        return self._lea_targets

    def string_ref_sites(self, xref_string: str) -> list[int]:
        """Code addresses that reference a string, IDA xref_strings semantics.

        Default is substring mode (any string containing the text), FULLMATCH: is exact.
        A lea may point at the string's start or, after tail merging, into a longer one.
        """
        exact = xref_string.startswith("FULLMATCH:")
        text = xref_string[len("FULLMATCH:"):] if exact else xref_string
        if not text:
            return []
        data = self.data
        leas = self.lea_targets()
        sites: set[int] = set()
        encodings = [text.encode("utf-8")]
        if self.platform == "windows":
            encodings.append(text.encode("utf-16-le"))
        for needle in encodings:
            unit = 2 if len(encodings) > 1 and needle == encodings[-1] else 1
            terminator = b"\0" * unit
            for match in re.finditer(re.escape(needle), data):
                start = match.start()
                end = match.end()
                if exact and data[end : end + unit] != terminator:
                    continue
                # walk back to the literal's first character (previous terminator)
                head = start
                while head >= unit and data[head - unit : head] != terminator and start - head < 4096:
                    head -= unit
                candidates = {start} if exact else {start, head}
                if exact and head != start:
                    # exact text sitting at the tail of a longer literal: only a lea to
                    # `start` itself is a reference to this exact string
                    candidates = {start}
                for off in candidates:
                    va = self.off_to_va(off)
                    if va is not None:
                        sites.update(leas.get(va, ()))
        return sorted(sites)

    def enclosing(self, va: int, limit: int = 0x8000) -> tuple[int, int]:
        """Rough bounds of the function holding *va*: padding before it to padding after it."""
        off = self.va_to_off(va)
        if off is None:
            return va, va + 1
        data = self.data
        lo = off
        while lo > 0 and off - lo < limit and data[lo - 2 : lo] != b"\xcc\xcc":
            lo -= 1
        hi_pad = re.search(rb"\xcc\xcc", data[off : off + limit])
        hi = off + (hi_pad.start() if hi_pad else limit)
        return self.off_to_va(lo), self.off_to_va(lo) + (hi - lo)

    def flow_end(self, func_va: int, limit: int = 0x8000):
        """End of the body by following its control flow, or None without capstone.

        A stored func_size can be short (an old measurement stopped at the first
        ret and missed a tail block reached by a forward branch), and judging by it
        calls the right function wrong. Linear sweep from the head, remembering the
        farthest in-body branch target; the body ends at the first ret/jmp/int3 with
        no pending target beyond it. A jump past inter-function padding (int3 int3)
        is a tail call, not part of the body.
        """
        try:
            import capstone
        except Exception:
            return None
        off = self.va_to_off(func_va)
        if off is None:
            return None
        window = self.data[off : off + limit]
        pad = re.search(rb"\xcc\xcc", window)
        hard_end = func_va + (pad.start() if pad else len(window))
        md = getattr(self, "_md", None)
        if md is None:
            md = self._md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        farthest = func_va
        pos = func_va
        while pos < hard_end:
            o = pos - func_va
            insn = next(md.disasm(window[o : o + 16], pos, 1), None)
            if insn is None:
                break
            nxt = pos + insn.size
            mnem = insn.mnemonic
            if mnem.startswith("j") and insn.op_str.startswith("0x"):
                try:
                    target = int(insn.op_str, 16)
                except ValueError:
                    target = None
                if target is not None and func_va <= target < hard_end:
                    farthest = max(farthest, target)
            if mnem in ("ret", "int3", "ud2", "hlt", "jmp") and farthest < nxt:
                return nxt
            pos = nxt
        return min(pos, hard_end)

    def cold_chunks(self, func_va: int, func_size: int) -> list[tuple[int, int]]:
        """(start_va, end_va) regions the body jumps out to - a GCC .cold / MSVC chunk."""
        off = self.va_to_off(func_va)
        if off is None:
            return []
        body = self.data[off : off + func_size]
        chunks = []
        for match in JMP_REL32.finditer(body):
            pos = match.start()
            width = 5 if body[pos] == 0xE9 else 6
            if pos + width > len(body):
                continue
            disp = struct.unpack_from("<i", body, pos + width - 4)[0]
            target = func_va + pos + width + disp
            if func_va <= target < func_va + func_size:
                continue
            target_off = self.va_to_off(target)
            if target_off is None:
                continue
            # the chunk runs until inter-function padding
            tail = self.data[target_off : target_off + COLD_CHUNK_LIMIT]
            pad = re.search(rb"\xcc\xcc|\x90\x90\x90", tail)
            chunks.append((target, target + (pad.start() if pad else len(tail))))
        return chunks


def locate_binary(folder: str, platform: str):
    """(path, gamever, module, bindir) of the binary for an artifact folder <x>/<ver>/<module>.

    Tries the folder's own tree first (a run against bin/), then the repo's bin/ - a
    run with -artifactdir in a scratch tree writes there, but its binaries stay in
    bin/<ver>/<module>, and without this fallback every check silently found nothing.
    """
    folder = os.path.abspath(os.fspath(folder))
    module = os.path.basename(folder)
    gamever = os.path.basename(os.path.dirname(folder))
    for bindir in (os.path.dirname(os.path.dirname(folder)), os.path.join(SCRIPT_DIR, "bin")):
        path = find_binary(bindir, gamever, module, platform)
        if path:
            return path, gamever, module, bindir
    return None, gamever, module, None


def find_binary(bindir: str, gamever: str, module: str, platform: str):
    folder = os.path.join(bindir, gamever, module)
    if not os.path.isdir(folder):
        return None
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        if platform == "linux" and (name.endswith(".so") or re.search(r"\.so\.\d+$", name)):
            return full
        if platform == "windows" and name.endswith(".dll"):
            return full
    return None


def read_artifact(path: str) -> dict:
    import yaml

    with open(path, encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}
    return doc if isinstance(doc, dict) else {}


def as_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 16) if str(value).lower().startswith("0x") else int(str(value))
    except ValueError:
        return None


# --- schema fallback ---------------------------------------------------------------------

SCHEMA_FIELD = re.compile(r"^m_[A-Za-z0-9_]+$")


def schema_member_proof(schemas, gamever, bindir, module, platform, name, doc, strings, binary, regions):
    """Second identity signal for an anchor that is a schema field name, or None.

    A finder anchored on a member name ('FULLMATCH:m_pBulletServices') relied on the
    NetworkStateChanged call that used to carry the literal. When the compiler stops
    emitting it, the literal survives only in the schema registration and the xref
    check has nothing to see - CCSPlayerPawn_CreatePlayerPawnServices from 14182 on.
    The member itself is still written: the function accesses
    <class>::<field> at the schema's offset (linux 0x10f0, windows 0xe28 on 14188).
    Class comes from vtable_name, else the symbol's prefix; needs capstone.
    """
    try:
        import capstone
        import schema_dump
    except Exception:
        return None
    fields = [s.split(":", 1)[-1] for s in strings]
    fields = [f for f in fields if SCHEMA_FIELD.match(f)]
    if not fields:
        return None
    key = (module, platform)
    if key not in schema_dump.BINARY_NAMES:
        return None
    if key not in schemas:
        try:
            schemas[key] = schema_dump.load_or_dump(gamever, module, platform, bindir)
        except Exception:
            schemas[key] = None
    classes = schemas[key]
    if not classes:
        return None
    vtable = str(doc.get("vtable_name") or "")
    cls = vtable[: -len("_vtable")] if vtable.endswith("_vtable") else vtable or name.split("_", 1)[0]
    wanted = {}
    for field in fields:
        hit = schema_dump.field_offset(classes, cls, field)
        if hit:
            wanted[hit[1]] = f"{hit[0]}::{field}"
    if not wanted:
        return None
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    for lo, hi in regions:
        off = binary.va_to_off(lo)
        if off is None:
            continue
        for insn in md.disasm(binary.data[off : off + (hi - lo)], lo):
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.mem.base not in (0, capstone.x86.X86_REG_RIP) \
                        and op.mem.disp in wanted:
                    return f"it accesses {wanted[op.mem.disp]} (schema offset {op.mem.disp:#x}) at {insn.address:#x}"
    return None


# --- audit -------------------------------------------------------------------------------


SEVERITY = {"OK": 0, "WARN": 1, "SKIP": 2, "BAD": 3}


def judge(binary, schemas, gamever, bindir, module, platform, name, doc, func_va, func_size,
          strings, excludes, signatures=(), alternatives=()):
    """(verdict, message) for one function against its finder's anchors.

    verdict is OK, BAD, WARN or SKIP (see the module docstring). Shared by the audit
    and by the run itself (relocation_verdict), so both judge a relocation the same way.
    alternatives are the anchors of other scripts that produce the same artifact
    (a -noinline / -inlined pair, a -linux variant): any one holding is enough,
    because on a given build only one of them describes the function.
    """
    verdict, message = _judge_one(binary, schemas, gamever, bindir, module, platform, name, doc,
                                  func_va, func_size, strings, excludes, signatures)
    if verdict == "OK":
        return verdict, message
    for alt in alternatives:
        v, m = _judge_one(binary, schemas, gamever, bindir, module, platform, name, doc, func_va,
                          func_size, alt["strings"], alt["exclude"], alt["signatures"])
        if v == "OK":
            return v, f"{m} (via {alt['source']})"
    return verdict, message


def _judge_one(binary, schemas, gamever, bindir, module, platform, name, doc, func_va, func_size,
               strings, excludes, signatures=()):
    """(verdict, message) for one function against its finder's anchor strings.

    verdict is OK, BAD, WARN or SKIP (see the module docstring). Shared by the audit
    and by the run itself (relocation_verdict), so both judge a relocation the same way.
    """
    if func_size <= 0:
        # artifact without a size (e.g. abi_guard could not measure it): bound the
        # body at the first inter-function padding instead
        off = binary.va_to_off(func_va)
        tail = binary.data[off : off + 0x8000] if off is not None else b""
        pad = re.search(rb"\xc3\xcc|\xcc\xcc", tail)
        func_size = pad.start() + 1 if pad else len(tail)
    flow_end = binary.flow_end(func_va)
    body_end = max(func_va + func_size, flow_end or 0)
    regions = [(func_va, body_end)] + binary.cold_chunks(func_va, body_end - func_va)
    size_note = ""
    if flow_end and flow_end > func_va + func_size:
        size_note = f" [func_size {func_size:#x} is short: control flow runs to +{flow_end - func_va:#x}]"

    if not strings:
        verdict, message = judge_signatures(binary, func_va, func_size, regions, signatures)
        return verdict, message + (size_note if verdict == "OK" else "")

    referenced = {s: binary.string_ref_sites(s) for s in strings}
    if not any(referenced.values()):
        return "SKIP", f"- no code reference to {strings[0]!r} found"

    for s, sites in referenced.items():
        for site in sites:
            if any(lo <= site < hi for lo, hi in regions):
                return "OK", f"@ {func_va:#x}: {s!r} at {site:#x}{size_note}"

    # A reference inside a function the finder itself excludes (exclude_strings)
    # does not point at the target; drop those before calling it BAD.
    if excludes:
        exclude_sites = sorted({x for e in excludes for x in binary.string_ref_sites(e)})
        for xref_string, sites in referenced.items():
            kept = []
            for site in sites:
                lo, hi = binary.enclosing(site)
                if not any(lo <= x < hi for x in exclude_sites):
                    kept.append(site)
            referenced[xref_string] = kept

    proof = schema_member_proof(schemas, gamever, bindir, module, platform, name, doc,
                                strings, binary, regions)
    if not any(referenced.values()):
        if proof:
            return "OK", (f"@ {func_va:#x}: anchor {strings[0]!r} no longer referenced from code, but "
                          f"{proof} - identity holds; the finder's xref fallback is dead")
        return "WARN", (f"@ {func_va:#x}: its anchor {strings[0]!r} is only referenced from excluded "
                        f"functions now - relocation is unverified and the xref fallback would fail")
    if proof:
        return "OK", f"@ {func_va:#x}: anchor {strings[0]!r} not referenced from it, but {proof}"

    s, sites = next((s, v) for s, v in referenced.items() if v)
    shown = ", ".join(f"{v:#x}" for v in sites[:4]) + (" ..." if len(sites) > 4 else "")
    return "BAD", (f"@ {func_va:#x} (size {func_size:#x}): {s!r} is never referenced from it; "
                   f"referenced at {shown} - the artifact names another function")


def sig_regex(signature: str):
    """IDA-style hex pattern ('48 8B ?? E8') as a bytes regex, or None."""
    parts = []
    for token in signature.split():
        if token in ("?", "??"):
            parts.append(b".")
        elif re.fullmatch(r"[0-9A-Fa-f]{2}", token):
            parts.append(re.escape(bytes([int(token, 16)])))
        else:
            return None
    return re.compile(b"".join(parts), re.S) if parts else None


def judge_signatures(binary, func_va, func_size, regions, signatures):
    """Same question for a finder anchored on byte patterns (xref_signatures).

    The xref path keeps a function only when EVERY pattern matches inside it, so a
    relocated body missing one that still occurs elsewhere in the code is not the
    function the finder describes.
    """
    found = []
    for signature in signatures:
        rx = sig_regex(signature)
        if rx is None:
            return "SKIP", f"- unparsable xref_signature {signature!r}"
        hit = None
        for lo, hi in regions:
            off = binary.va_to_off(lo)
            if off is None:
                continue
            m = rx.search(binary.data, off, off + (hi - lo))
            if m:
                hit = binary.off_to_va(m.start())
                break
        if hit is None:
            elsewhere = None
            for seg_va, size, seg_off, executable in binary.segments:
                if executable:
                    m = rx.search(binary.data, seg_off, seg_off + size)
                    if m:
                        elsewhere = m.start() - seg_off + seg_va
                        break
            if elsewhere is None:
                return "SKIP", f"- xref_signature {signature!r} matches nowhere in the code"
            return "BAD", (f"@ {func_va:#x} (size {func_size:#x}): xref_signature {signature!r} does not "
                           f"match inside it (first match {elsewhere:#x}) - the artifact names another function")
        found.append((signature, hit))
    signature, hit = found[0]
    return "OK", f"@ {func_va:#x}: xref_signature {signature!r} at {hit:#x}"


_BINARY_CACHE: dict = {}


def relocation_verdict(func_name, platform, func_va, func_size, new_binary_dir, xref_strings,
                       exclude_strings=(), vtable_name=None, xref_signatures=()):
    """Judge a fresh relocation inside a run: 'ok' | 'bad' | 'warn' | None (cannot judge).

    new_binary_dir is bin/<VER>/<module>. Only 'bad' is meant to reject: the anchor
    is referenced in the binary, never from this function, and no schema member
    vouches for it - the sig outlived its function and landed in another one.
    """
    strings = [s for s in xref_strings or [] if isinstance(s, str) and s]
    signatures = [s for s in xref_signatures or [] if isinstance(s, str) and s]
    va = as_int(func_va)
    if not (strings or signatures) or va is None or not new_binary_dir:
        return None
    path, gamever, module, bindir = locate_binary(new_binary_dir, platform)
    if not path:
        return None
    key = (path, platform)
    if key not in _BINARY_CACHE:
        _BINARY_CACHE.clear()  # one binary at a time: a run walks one module per process
        _BINARY_CACHE[key] = (Binary(path, platform), {})
    binary, schemas = _BINARY_CACHE[key]
    doc = {"vtable_name": vtable_name} if vtable_name else {}
    verdict, _message = judge(binary, schemas, gamever, bindir, module, platform, func_name, doc,
                              va, as_int(func_size) or 0, strings, list(exclude_strings or []), signatures)
    return {"OK": "ok", "BAD": "bad", "WARN": "warn"}.get(verdict)


def audit(gamever, platforms, bindir, artifactdir, symbol_filter, verbose):
    specs, unreadable = load_specs(symbol_filter)
    binaries: dict[str, Binary | None] = {}
    schemas: dict = {}
    counts = {"OK": 0, "BAD": 0, "WARN": 0, "SKIP": 0}
    bad_lines = []

    for name in sorted(specs):
        for platform in platforms:
            entry = specs[name].get(platform)
            if not entry:
                continue
            primary, alternatives = entry[0], entry[1:]
            strings, excludes, signatures = primary["strings"], primary["exclude"], primary["signatures"]
            pattern = os.path.join(artifactdir, gamever, "*", f"{name}.{platform}.yaml")
            artifacts = sorted(glob.glob(pattern))
            if not artifacts:
                continue  # not produced for this platform/build - not ours to judge
            artifact = artifacts[0]
            module = os.path.basename(os.path.dirname(artifact))
            label = f"{module}/{name}.{platform}"
            doc = read_artifact(artifact)
            func_va = as_int(doc.get("func_va"))
            func_size = as_int(doc.get("func_size")) or 0
            if func_va is None:
                counts["SKIP"] += 1
                if verbose:
                    print(f"  SKIP {label}: no func_va")
                continue

            key = f"{module}:{platform}"
            if key not in binaries:
                path = find_binary(bindir, gamever, module, platform)
                binaries[key] = Binary(path, platform) if path else None
            binary = binaries[key]
            if binary is None:
                counts["SKIP"] += 1
                if verbose:
                    print(f"  SKIP {label}: no {platform} binary under {bindir}/{gamever}/{module}")
                continue

            verdict, message = judge(binary, schemas, gamever, bindir, module, platform, name, doc,
                                     func_va, func_size, strings, excludes, signatures, alternatives)
            counts[verdict] += 1
            if verdict == "BAD":
                bad_lines.append(f"  BAD  {label} {message}")
            if verdict in ("BAD", "WARN") or verbose or ", but " in message:
                print(f"  {verdict:<4} {label} {message}")

    print(f"audit_xref_identity {gamever}: {counts['OK']} ok, {counts['BAD']} bad, "
          f"{counts['WARN']} warn, {counts['SKIP']} skipped ({len(specs)} anchored symbols, platforms {','.join(platforms)})")
    if unreadable:
        print(f"  note: {len(unreadable)} preprocessor script(s) had an unreadable FUNC_XREFS", file=sys.stderr)
    return counts["BAD"]


def newest_gamever(artifactdir: str):
    versions = [d for d in os.listdir(artifactdir) if os.path.isdir(os.path.join(artifactdir, d))]
    numeric = sorted(versions, key=lambda v: (int(re.match(r"\d+", v).group()) if re.match(r"\d+", v) else 0, v))
    return numeric[-1] if numeric else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", help="game version (default: newest in bin_artifacts/)")
    parser.add_argument("-platform", default="linux,windows")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-artifactdir", default="bin_artifacts")
    parser.add_argument("-symbol", help="only symbols whose name contains this text")
    parser.add_argument("-v", "--verbose", action="store_true", help="print OK and SKIP lines too")
    args = parser.parse_args(argv)

    os.chdir(SCRIPT_DIR)
    gamever = args.gamever or newest_gamever(args.artifactdir)
    if not gamever or not os.path.isdir(os.path.join(args.artifactdir, gamever)):
        print(f"audit_xref_identity: no artifacts for {gamever!r} under {args.artifactdir}/", file=sys.stderr)
        return 2
    platforms = [p.strip() for p in args.platform.split(",") if p.strip() in ("linux", "windows")]
    if not platforms:
        print("audit_xref_identity: -platform must be linux, windows or both", file=sys.stderr)
        return 2
    bad = audit(gamever, platforms, args.bindir, args.artifactdir, args.symbol, args.verbose)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
