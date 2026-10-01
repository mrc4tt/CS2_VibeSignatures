#!/usr/bin/env python3
"""Check every function artifact against the same symbol on the previous gamever.

audit_xref_identity.py only speaks for the ~430 symbols whose finder names an anchor
string. Relocation can put ANY symbol on the wrong function: the previous gamever's
func_sig still matches exactly once, in a different function, and every other check
(validate_artifacts, verify_plugin_gamedata) only re-scans that sig. This audit
needs no hand-written anchor. It takes each function's fingerprint on both builds,
straight from the raw binaries, and compares them:

  strings  the C strings the body references (rip-relative lea into a literal)
  calls    the number of direct calls (e8 rel32)
  size     the body size by control flow (the stored func_size can be short)

A function keeps its strings across builds; code that only moved keeps them all.
When the previous build's function referenced strings and the new one shares none
of them, the artifact names another function - that is exactly the JoinTeam.linux
defect (14182-14188: "HandleCommand_JoinTeam( %d ) - invalid team index." on 14181,
nothing of it on the wrong function).

Verdicts:
  OK     strings carried over (or both have none and size/calls are close)
  DRIFT  the previous function had 2+ strings, the new one shares none of them, and
         one other function now holds most of them with a similar string set - a
         wrong identification, and the line names where the real function likely is
  WARN   weaker evidence: its one string is gone, under half carried over, or no strings on
         either side and size and call count both moved by more than 2x
  SKIP   no previous artifact / binary, or nothing to compare

  uv run audit_identity_drift.py -gamever 14188              # previous = the gamever before it
  uv run audit_identity_drift.py -gamever 14188 -old 14181 -symbol JoinTeam -v

Exit status: 0 when nothing DRIFTs, 1 otherwise, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import struct
import sys

from audit_xref_identity import LEA_RIP, Binary, as_int, find_binary, locate_binary, read_artifact

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CALL_REL32 = re.compile(rb"\xe8")
PRINTABLE = re.compile(rb"[\x20-\x7e\t\r\n]{6,}\x00")
WORDY = re.compile(rb"[A-Za-z]{3}")
# categories that do not describe a function body
NON_FUNC_KEYS = ("vtable_va", "gv_va", "offset", "patch_va")


def gamever_key(v: str):
    m = re.match(r"(\d+)(.*)", v)
    return (int(m.group(1)), m.group(2)) if m else (0, v)


def previous_gamever(artifactdir: str, gamever: str, bindir: str = "bin"):
    """The newest earlier gamever that has both artifacts and binaries."""
    versions = sorted((d for d in os.listdir(artifactdir) if os.path.isdir(os.path.join(artifactdir, d))
                       and (d == gamever or os.path.isdir(os.path.join(bindir, d)))),
                      key=gamever_key)
    if gamever not in versions:
        return None
    i = versions.index(gamever)
    return versions[i - 1] if i > 0 else None


def body_regions(binary: Binary, func_va: int, func_size: int):
    # a measured size is the better bound; control flow only stands in for a missing one
    end = func_va + func_size if func_size > 0 else (binary.flow_end(func_va) or func_va)
    if end <= func_va:
        return []
    return [(func_va, end)] + decoded_chunks(binary, func_va, end)


def decoded_chunks(binary: Binary, func_va: int, end: int):
    """Out-of-body regions the body branches to, from DECODED jmp/jcc instructions.

    Scanning raw bytes for e9 (as cold_chunks does) also hits e9 inside other
    instructions and wanders into random code; for a fingerprint that pulls a
    stranger's strings in. A target that looks like a function head is a tail
    call, not a chunk of this body.
    """
    try:
        import capstone
    except Exception:
        return []
    off = binary.va_to_off(func_va)
    if off is None:
        return []
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    chunks = []
    for insn in md.disasm(binary.data[off : off + (end - func_va)], func_va):
        if not insn.mnemonic.startswith("j") or not insn.op_str.startswith("0x"):
            continue
        try:
            target = int(insn.op_str, 16)
        except ValueError:
            continue
        if func_va <= target < end or looks_like_head(binary, target):
            continue
        tend = binary.flow_end(target, limit=0x2000)
        if tend and tend > target:
            chunks.append((target, tend))
    return chunks


def looks_like_head(binary: Binary, va: int) -> bool:
    """A 16-aligned address right after padding is another function (a tail call), not
    a .cold chunk of this one - following it pulls a stranger's strings in."""
    if va % 16:
        return False
    off = binary.va_to_off(va)
    return off is not None and off > 0 and binary.data[off - 1] in (0xCC, 0x90)


def fingerprint(binary: Binary, func_va: int, func_size: int):
    """(strings, calls, size) of the body at func_va."""
    regions = body_regions(binary, func_va, func_size)
    strings: set[bytes] = set()
    calls = 0
    size = 0
    for lo, hi in regions:
        off = binary.va_to_off(lo)
        if off is None:
            continue
        body = binary.data[off : off + (hi - lo)]
        size += hi - lo
        for m in LEA_RIP.finditer(body):
            pos = m.start()
            if pos + 7 > len(body):
                continue
            target = lo + pos + 7 + struct.unpack_from("<i", body, pos + 3)[0]
            toff = binary.va_to_off(target)
            if toff is None:
                continue
            # a literal's first byte, not a pointer into the middle of data
            if toff == 0 or binary.data[toff - 1] != 0:
                continue
            s = PRINTABLE.match(binary.data, toff, toff + 512)
            if s and WORDY.search(s.group()):
                strings.add(s.group()[:-1])
        calls += len(CALL_REL32.findall(body))
    return strings, calls, size


def branch_targets(binary: Binary, func_va: int, func_size: int) -> set[int]:
    """Targets of every decoded direct call / jmp in the body."""
    try:
        import capstone
    except Exception:
        return set()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    out = set()
    for lo, hi in body_regions(binary, func_va, func_size):
        off = binary.va_to_off(lo)
        if off is None:
            continue
        for insn in md.disasm(binary.data[off : off + (hi - lo)], lo):
            if (insn.mnemonic == "call" or insn.mnemonic.startswith("j")) and insn.op_str.startswith("0x"):
                try:
                    out.add(int(insn.op_str, 16))
                except ValueError:
                    pass
    return out


def string_present(binary: Binary, text: bytes) -> bool:
    return binary.data.find(text + b"\x00") != -1


def where_strings_went(binary: Binary, strings: set[bytes]):
    """(function_va, how_many, similarity) of the one function that now holds most of
    `strings`, or None when they scattered.

    This is what separates a wrong identification from a function that changed:
    after JoinTeam.linux was relocated onto the wrong function, all 14 of its
    strings were still referenced - together, from the real one. When strings were
    inlined into callers or only survive in a schema registration table, no single
    function with a similar string set holds them.
    """
    holders: dict[int, set[bytes]] = {}
    for text in strings:
        for site in binary.string_ref_sites("FULLMATCH:" + text.decode("latin-1")):
            lo, _hi = binary.enclosing(site)
            holders.setdefault(lo, set()).add(text)
    if not holders:
        return None
    va, held = max(holders.items(), key=lambda item: len(item[1]))
    if len(held) * 2 < len(strings) or len(held) < 3:
        return None
    their_strings, _calls, _size = fingerprint(binary, va, 0)
    similarity = len(their_strings & strings) / len(their_strings | strings) if their_strings else 0.0
    if similarity < 0.7:
        return None
    return va, len(held), similarity


def compare(old_fp, new_fp, new_binary: Binary, new_fp_targets=frozenset()):
    old_s, old_calls, old_size = old_fp
    new_s, new_calls, new_size = new_fp
    if old_s:
        kept = old_s & new_s
        # strings the new build dropped from the binary altogether say nothing
        # about identity; only judge by the ones that still exist somewhere
        alive = {s for s in old_s if string_present(new_binary, s)}
        if not alive:
            return "SKIP", "previous strings are gone from the binary"
        if not kept & alive and len(alive) >= 2:
            sample = sorted(alive, key=len, reverse=True)[0].decode("latin-1")[:70]
            holder = where_strings_went(new_binary, alive)
            if holder and holder[0] in new_fp_targets:
                # the new function calls (or tail-jumps to) the one holding the strings:
                # the body was outlined into a helper, as CLoopModeGame_LoopInit became a
                # thin slot-0 wrapper around LoopInitInternal on 14182
                return "OK", f"body outlined into {holder[0]:#x}, which it calls"
            if holder:
                va, share, similarity = holder
                return "DRIFT", (f"none of its {len(alive)} previous strings is referenced any more; "
                                 f"{share}/{len(alive)} of them now sit together in {va:#x} "
                                 f"(string-set similarity {similarity:.0%}) - one of the two builds names the wrong function; compare both with a third build")
            return "WARN", (f"none of its {len(alive)} previous strings is referenced any more, and no single "
                            f"function took them over (inlined, or moved into a registration table; "
                            f"e.g. {sample!r})")
        if not kept & alive:
            return "WARN", f"its one previous string {next(iter(alive)).decode('latin-1')[:60]!r} is not referenced any more"
        if len(kept & alive) * 2 < len(alive):
            return "WARN", f"only {len(kept & alive)}/{len(alive)} previous strings carried over"
        return "OK", f"{len(kept & alive)}/{len(alive)} strings carried over"
    if new_s:
        return "OK", "gained strings (previous body had none)"

    def far(a, b):
        return a and b and max(a, b) > 2 * min(a, b) and abs(a - b) > 0x40

    if far(old_size, new_size) and (old_calls != new_calls and far(old_calls * 0x40, new_calls * 0x40)):
        return "WARN", f"no strings; size {old_size:#x} -> {new_size:#x}, calls {old_calls} -> {new_calls}"
    return "OK", "no strings; size and calls close"


_BIN_CACHE: dict = {}


def _cached_binary(path, platform):
    key = (path, platform)
    if key not in _BIN_CACHE:
        if len(_BIN_CACHE) >= 2:  # the run compares one module, old and new
            _BIN_CACHE.clear()
        _BIN_CACHE[key] = Binary(path, platform)
    return _BIN_CACHE[key]


def relocation_drift_verdict(platform, func_va, func_size, new_binary_dir, old_yaml_path):
    """Judge a fresh relocation against the previous gamever's artifact, inside a run.

    'drift' | 'ok' | 'warn' | None (cannot judge). Only 'drift' is meant to reject:
    the previous function's strings all still exist, none is referenced from the
    relocated body, and one other function now holds them together.
    """
    va = as_int(func_va)
    if va is None or not new_binary_dir or not old_yaml_path or not os.path.exists(old_yaml_path):
        return None
    old_doc = read_artifact(old_yaml_path)
    if any(k in old_doc for k in NON_FUNC_KEYS):
        return None
    old_va = as_int(old_doc.get("func_va"))
    if old_va is None:
        return None
    new_path, *_ = locate_binary(new_binary_dir, platform)
    old_path, *_ = locate_binary(os.path.dirname(os.path.abspath(old_yaml_path)), platform)
    if not new_path or not old_path:
        return None
    new_bin = _cached_binary(new_path, platform)
    old_bin = _cached_binary(old_path, platform)
    size = as_int(func_size) or 0
    old_fp = fingerprint(old_bin, old_va, as_int(old_doc.get("func_size")) or 0)
    new_fp = fingerprint(new_bin, va, size)
    verdict, _why = compare(old_fp, new_fp, new_bin, branch_targets(new_bin, va, size))
    return {"OK": "ok", "DRIFT": "drift", "WARN": "warn"}.get(verdict)


def audit(gamever, old, platforms, bindir, artifactdir, symbol_filter, verbose):
    binaries: dict = {}

    def binary_for(ver, module, platform):
        key = (ver, module, platform)
        if key not in binaries:
            path = find_binary(bindir, ver, module, platform)
            binaries[key] = Binary(path, platform) if path else None
        return binaries[key]

    counts = {"OK": 0, "DRIFT": 0, "WARN": 0, "SKIP": 0}
    for path in sorted(glob.glob(os.path.join(artifactdir, gamever, "*", "*.yaml"))):
        module = os.path.basename(os.path.dirname(path))
        base = os.path.basename(path)[: -len(".yaml")]
        name, _, platform = base.rpartition(".")
        if platform not in platforms or (symbol_filter and symbol_filter.lower() not in name.lower()):
            continue
        doc = read_artifact(path)
        if any(k in doc for k in NON_FUNC_KEYS):
            continue
        va = as_int(doc.get("func_va"))
        if va is None:
            continue
        label = f"{module}/{base}"
        old_path = os.path.join(artifactdir, old, module, os.path.basename(path))
        if not os.path.exists(old_path):
            counts["SKIP"] += 1
            continue
        old_doc = read_artifact(old_path)
        old_va = as_int(old_doc.get("func_va"))
        new_bin = binary_for(gamever, module, platform)
        old_bin = binary_for(old, module, platform)
        if old_va is None or new_bin is None or old_bin is None:
            counts["SKIP"] += 1
            continue
        new_fp = fingerprint(new_bin, va, as_int(doc.get("func_size")) or 0)
        old_fp = fingerprint(old_bin, old_va, as_int(old_doc.get("func_size")) or 0)
        targets = branch_targets(new_bin, va, as_int(doc.get("func_size")) or 0)
        verdict, why = compare(old_fp, new_fp, new_bin, targets)
        counts[verdict] += 1
        if verdict in ("DRIFT", "WARN") or verbose:
            print(f"  {verdict:<5} {label} @ {va:#x} (was {old_va:#x} on {old}): {why}")
    print(f"audit_identity_drift {gamever} vs {old}: {counts['OK']} ok, {counts['DRIFT']} drift, "
          f"{counts['WARN']} warn, {counts['SKIP']} skipped")
    return counts["DRIFT"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-old", help="gamever to compare against (default: the one before -gamever)")
    parser.add_argument("-platform", default="linux,windows")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-artifactdir", default="bin_artifacts")
    parser.add_argument("-symbol", help="only symbols whose name contains this text")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    os.chdir(SCRIPT_DIR)
    old = args.old or previous_gamever(args.artifactdir, args.gamever, args.bindir)
    if not old:
        print(f"audit_identity_drift: no gamever before {args.gamever!r}", file=sys.stderr)
        return 2
    platforms = [p.strip() for p in args.platform.split(",") if p.strip() in ("linux", "windows")]
    drift = audit(args.gamever, old, platforms, args.bindir, args.artifactdir, args.symbol, args.verbose)
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
