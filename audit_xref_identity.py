#!/usr/bin/env python3
"""Check that every relocated function still references its own anchor string.

Relocation reuses the previous gamever's func_sig and accepts it when it matches
exactly once. A sig that outlives its function keeps matching uniquely - in a
DIFFERENT function - and nothing downstream complains: validate_artifacts and
verify_plugin_gamedata only re-scan the sig. That is how
CBasePlayerController_HandleCommand_JoinTeam.linux sat on the wrong function from
14182 to 14188 and crashed MatchZy servers.

Most finders already name the string their function references (FUNC_XREFS
xref_strings). This audit reads those specs straight from the preprocessor scripts
(ast, nothing imported), takes each artifact's func_va/func_size and checks in the
raw binary that at least one of the strings is referenced from inside the function
(or from a cold chunk the function jumps to). Deterministic and IDA-free.

Verdicts:
  OK    an anchor string is referenced inside the function
  BAD   the strings are referenced in the binary, but never from this function
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
      - ...-inlined scripts and inline_alias specs are skipped: their string lives in the
        caller the function was inlined into, not in the function itself.
    The resolved map is keyed by the concrete platform; "*" entries are folded in last.
    """
    raw: dict[str, dict[str, dict[str, list[str]]]] = {}
    specific: dict[str, set[str]] = {}
    unreadable = []

    def add(spec_list, platform, script_platform):
        for spec in spec_list or []:
            if not isinstance(spec, dict):
                continue
            name = spec.get("func_name")
            if not name:
                continue
            if symbol_filter and symbol_filter.lower() not in name.lower():
                continue
            if script_platform != "*":
                specific.setdefault(name, set()).add(script_platform)
            if spec.get("inline_alias"):
                continue
            strings = [x for x in spec.get("xref_strings") or [] if isinstance(x, str) and x]
            if not strings:
                continue
            entry = raw.setdefault(name, {}).setdefault(platform, {"strings": [], "exclude": []})
            entry["strings"].extend(x for x in strings if x not in entry["strings"])
            excludes = [x for x in spec.get("exclude_strings") or [] if isinstance(x, str) and x]
            entry["exclude"].extend(x for x in excludes if x not in entry["exclude"])

    for path in sorted(glob.glob(os.path.join(PREPROCESSOR_DIR, "find-*.py"))):
        stem = os.path.basename(path)[: -len(".py")]
        if "inlined" in stem:
            continue
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
                add(spec_list, platform, platform)
        elif "FUNC_XREFS_BY_PLATFORM" in found:
            unreadable.append(path)
        if isinstance(found.get("FUNC_XREFS"), list):
            add(found["FUNC_XREFS"], script_platform, script_platform)
        elif "FUNC_XREFS" in found and "FUNC_XREFS_BY_PLATFORM" not in found:
            unreadable.append(path)

    specs: dict[str, dict[str, dict[str, list[str]]]] = {}
    for name, per_platform in raw.items():
        for platform in ("linux", "windows"):
            if platform in specific.get(name, set()):
                entry = per_platform.get(platform)
            else:
                entry = per_platform.get(platform) or per_platform.get("*")
            if entry:
                specs.setdefault(name, {})[platform] = entry
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


# --- audit -------------------------------------------------------------------------------


def audit(gamever, platforms, bindir, artifactdir, symbol_filter, verbose):
    specs, unreadable = load_specs(symbol_filter)
    binaries: dict[str, Binary | None] = {}
    counts = {"OK": 0, "BAD": 0, "WARN": 0, "SKIP": 0}
    bad_lines = []

    for name in sorted(specs):
        for platform in platforms:
            entry = specs[name].get(platform)
            if not entry:
                continue
            strings, excludes = entry["strings"], entry["exclude"]
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

            if func_size <= 0:
                # artifact without a size (e.g. abi_guard could not measure it): bound the
                # body at the first inter-function padding instead
                off = binary.va_to_off(func_va)
                tail = binary.data[off : off + 0x8000] if off is not None else b""
                pad = re.search(rb"\xc3\xcc|\xcc\xcc", tail)
                func_size = pad.start() + 1 if pad else len(tail)
            regions = [(func_va, func_va + func_size)] + binary.cold_chunks(func_va, func_size)

            referenced = {}
            for xref_string in strings:
                referenced[xref_string] = binary.string_ref_sites(xref_string)
            if not any(referenced.values()):
                counts["SKIP"] += 1
                if verbose:
                    print(f"  SKIP {label}: no code reference to {strings[0]!r} found")
                continue

            inside = [
                (s, site) for s, sites in referenced.items() for site in sites
                if any(lo <= site < hi for lo, hi in regions)
            ]
            if inside:
                counts["OK"] += 1
                if verbose:
                    s, site = inside[0]
                    print(f"  OK   {label} @ {func_va:#x}: {s!r} at {site:#x}")
                continue

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
                if not any(referenced.values()):
                    counts["WARN"] += 1
                    print(f"  WARN {label} @ {func_va:#x}: its anchor {strings[0]!r} is only referenced from "
                          f"excluded functions now - relocation is unverified and the xref fallback would fail")
                    continue

            counts["BAD"] += 1
            s, sites = next((s, v) for s, v in referenced.items() if v)
            shown = ", ".join(f"{v:#x}" for v in sites[:4]) + (" ..." if len(sites) > 4 else "")
            line = (f"  BAD  {label} @ {func_va:#x} (size {func_size:#x}): {s!r} is never referenced "
                    f"from it; referenced at {shown} - the artifact names another function")
            bad_lines.append(line)
            print(line)

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
