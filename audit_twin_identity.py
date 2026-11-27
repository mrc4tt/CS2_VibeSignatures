#!/usr/bin/env python3
"""Check that a function with a twin is still the same twin as on the previous gamever.

Some functions exist several times over with one instruction stream and different
operands: CCSBot::Idle and CCSBot::EscapeFromBomb are both
`mov rax,[rip+x]; lea rsi,[rdi+STATE]; mov [rdi+0x5c8],rax; jmp SetState`, and the two
registry loops in CSource2Server::Shutdown differ only in `call [rax+0x58]` against
`call [rax+0x60]`. A signature wildcards exactly those operands (they move with the
class layout), so it tells the twins apart by what follows the function, and a record
can slide from one twin to the other on a rebuild. Nothing else notices: the signature
is unique, the head is a function head, there is no string to carry over and no vtable
slot. CCSBot_Idle.linux named EscapeFromBomb's setter and
CEngineServiceRegistry_UnregisterEngineServices.linux the register loop from 14190 to
14201, until upstream's artifacts disagreed.

For every function artifact that also exists on the previous gamever, up to
MAX_TWIN_SIZE bytes:

  skeleton   the instruction bytes with every displacement and immediate masked
  operands   the masked values that are not addresses: struct displacements, vtable
             offsets, constants (rip-relative displacements and branch targets move on
             every build and are left out)
  twins      every other place in the new binary where the skeleton matches

Verdicts:
  OK       no twin, or the operands are the ones the previous build's function had
  SWAPPED  the operands changed AND exactly one twin carries the previous operands: the
           function the old record named still exists, and the new record is not it.
           The run applies the same judgement to every relocation and moves the record
           to that twin (CS2VIBE_RELOC_TWIN_CHECK=0 off), so this gate is the backstop
           for records that came from an agent or the hunter
  MOVED    the operands changed and no twin has the old ones (a layout change moved
           them all) - reported with -v, never a failure
  SKIP     no previous artifact, unknown size, too long, or the skeleton itself changed

A SWAPPED line names both addresses. Decide which build is right in the binary (the
previous one may be the wrong one - fixing a swapped record reports SWAPPED once, against
the wrong baseline), then rebuild the artifact with emit_artifact.py at the right address.

    uv run audit_twin_identity.py -gamever 14202
    uv run audit_twin_identity.py -gamever 14202 -symbol CCSBot_Idle -v

Exit 0 nothing swapped, 1 a SWAPPED record, 2 no previous gamever.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

from audit_identity_drift import NON_FUNC_KEYS, previous_gamever
from audit_xref_identity import Binary, as_int, find_binary, locate_binary, read_artifact

try:
    import capstone
    from capstone import x86 as cs_x86
except ImportError:  # pragma: no cover - the battery checks for capstone first
    capstone = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_TWIN_SIZE = 0x100   # twins are small; a long body has strings or calls of its own
MIN_FIXED_BYTES = 6     # a skeleton with fewer literal bytes matches by accident
MAX_MATCHES = 256       # more places than this is a code idiom, not a set of twins
# Accepted findings for one gamever pair: "<new>:<old>" -> {"module/Symbol.platform": why}.
# Only for a build where the PREVIOUS record was the wrong twin and this build fixed it.
ACCEPTED = {
    "14201:14200": {
        "server/CCSBot_Idle.linux": "14200 named EscapeFromBombState's setter (+0x498); IdleState is at +0x210 "
                                    "(CCSBot's constructor stores its vtable there)",
        "server/CEngineServiceRegistry_UnregisterEngineServices.linux":
            "14200 named the loop calling slot 11; IEngineServiceMgr_UnregisterEngineService is slot 12",
    },
}


def decode(code: bytes, va: int):
    """(skeleton, operands) of a function body, or None when it does not decode to its end.

    skeleton: bytes with None at every displacement/immediate byte.
    operands: tuple of (instruction index, kind, value bytes) for the non-address fields.
    """
    if capstone is None:
        return None
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    skeleton: list = []
    operands = []
    consumed = 0
    for index, insn in enumerate(md.disasm(code, va)):
        raw = bytes(insn.bytes)
        mask = [False] * len(raw)
        rip_relative = any(op.type == cs_x86.X86_OP_MEM and op.mem.base == cs_x86.X86_REG_RIP for op in insn.operands)
        branch = insn.group(capstone.CS_GRP_JUMP) or insn.group(capstone.CS_GRP_CALL)
        if insn.disp_size:
            span = range(insn.disp_offset, insn.disp_offset + insn.disp_size)
            for i in span:
                mask[i] = True
            if not rip_relative:
                operands.append((index, "disp", raw[span.start:span.stop]))
        if insn.imm_size:
            span = range(insn.imm_offset, insn.imm_offset + insn.imm_size)
            for i in span:
                mask[i] = True
            if not branch:
                operands.append((index, "imm", raw[span.start:span.stop]))
        skeleton.extend(None if masked else byte for byte, masked in zip(raw, mask))
        consumed += len(raw)
    if consumed != len(code):
        return None
    return tuple(skeleton), tuple(operands)


def skeleton_regex(skeleton):
    return re.compile(b"".join(b"." if byte is None else re.escape(bytes([byte])) for byte in skeleton), re.DOTALL)


def read_body(binary: Binary, va: int, size: int):
    off = binary.va_to_off(va)
    if off is None or size <= 0 or off + size > len(binary.data):
        return None
    return binary.data[off:off + size]


def twin_addresses(binary: Binary, skeleton, own_va: int):
    """Every other executable address where the skeleton matches; None when it is an idiom."""
    pattern = skeleton_regex(skeleton)
    found = []
    for seg_va, seg_size, seg_off, executable in binary.segments:
        if not executable:
            continue
        for match in pattern.finditer(binary.data, seg_off, seg_off + seg_size):
            va = seg_va + match.start() - seg_off
            if va != own_va:
                found.append(va)
                if len(found) > MAX_MATCHES:
                    return None
    return found


def twin_verdict(new_bin: Binary, new_va: int, new_size: int, old_bin: Binary, old_va: int, old_size: int):
    """-> (verdict, why)."""
    if not new_size or not old_size or new_size > MAX_TWIN_SIZE or old_size > MAX_TWIN_SIZE:
        return "SKIP", "unknown size or too long for a twin"
    new_code, old_code = read_body(new_bin, new_va, new_size), read_body(old_bin, old_va, old_size)
    if new_code is None or old_code is None:
        return "SKIP", "body not in the binary"
    new, old = decode(new_code, new_va), decode(old_code, old_va)
    if new is None or old is None:
        return "SKIP", "body does not decode to its end"
    (new_skeleton, new_operands), (old_skeleton, old_operands) = new, old
    if new_skeleton != old_skeleton:
        return "SKIP", "instruction stream changed"
    if new_operands == old_operands:
        return "OK", "same operands"
    if sum(byte is not None for byte in new_skeleton) < MIN_FIXED_BYTES:
        return "SKIP", "too few literal bytes to look for twins"
    twins = twin_addresses(new_bin, new_skeleton, new_va)
    if twins is None:
        return "SKIP", "a code idiom, not a set of twins"
    for twin in twins:
        code = read_body(new_bin, twin, new_size)
        decoded = decode(code, twin) if code is not None else None
        if decoded and decoded[1] == old_operands:
            changed = [f"{kind} {old_value.hex()} -> {new_value.hex()}"
                       for (_i, kind, old_value), (_j, _k, new_value) in zip(old_operands, new_operands)
                       if old_value != new_value]
            holders = [t for t in twins
                       if (decode(read_body(new_bin, t, new_size) or b"", t) or (None, None))[1] == old_operands]
            if len(holders) != 1:
                return "MOVED", f"operands changed, {len(holders)} twins carry the previous ones - undecided"
            return "SWAPPED", (f"the previous build's function is at {twin:#x} (same operands); "
                               f"this record differs in {', '.join(changed[:4])}")
    return "MOVED", f"operands changed, none of {len(twins)} twin(s) has the previous ones"


def swapped_twin_address(why: str):
    """The address a SWAPPED verdict names as the previous build's function."""
    found = re.search(r"function is at (0x[0-9a-f]+)", why)
    return int(found.group(1), 16) if found else None


_BIN_CACHE: dict = {}


def _cached_binary(path, platform):
    key = (path, platform)
    if key not in _BIN_CACHE:
        if len(_BIN_CACHE) >= 2:  # the run compares one module, old and new
            _BIN_CACHE.clear()
        _BIN_CACHE[key] = Binary(path, platform)
    return _BIN_CACHE[key]


def relocation_twin_verdict(platform, func_va, func_size, new_binary_dir, old_yaml_path):
    """Judge a fresh relocation against the previous gamever's artifact, inside a run.

    ('swapped', twin_va) when the relocated function is a twin of the one the previous
    record named and exactly one other twin still carries that record's operands -
    twin_va is where the function really is. Otherwise (verdict, None) with 'ok',
    'moved' or 'skip', or (None, None) when it cannot be judged.
    """
    va = as_int(func_va)
    if va is None or not new_binary_dir or not old_yaml_path or not os.path.exists(old_yaml_path):
        return None, None
    old_doc = read_artifact(old_yaml_path)
    old_va = as_int(old_doc.get("func_va"))
    if old_va is None or any(k in old_doc for k in NON_FUNC_KEYS):
        return None, None
    new_path, *_ = locate_binary(new_binary_dir, platform)
    old_path, *_ = locate_binary(os.path.dirname(os.path.abspath(old_yaml_path)), platform)
    if not new_path or not old_path:
        return None, None
    verdict, why = twin_verdict(_cached_binary(new_path, platform), va, as_int(func_size) or 0,
                                _cached_binary(old_path, platform), old_va, as_int(old_doc.get("func_size")) or 0)
    return verdict.lower(), swapped_twin_address(why) if verdict == "SWAPPED" else None


def audit(gamever, old, platforms, bindir, artifactdir, symbol_filter, verbose):
    binaries: dict = {}

    def binary_for(ver, module, platform):
        key = (ver, module, platform)
        if key not in binaries:
            path = find_binary(bindir, ver, module, platform)
            binaries[key] = Binary(path, platform) if path else None
        return binaries[key]

    accepted = ACCEPTED.get(f"{gamever}:{old}", {})
    counts = {"OK": 0, "SWAPPED": 0, "MOVED": 0, "SKIP": 0, "ACCEPTED": 0}
    for path in sorted(glob.glob(os.path.join(artifactdir, gamever, "*", "*.yaml"))):
        module = os.path.basename(os.path.dirname(path))
        base = os.path.basename(path)[: -len(".yaml")]
        name, _, platform = base.rpartition(".")
        if platform not in platforms or (symbol_filter and symbol_filter.lower() not in name.lower()):
            continue
        doc = read_artifact(path)
        va = as_int(doc.get("func_va"))
        if va is None or any(k in doc for k in NON_FUNC_KEYS):
            continue
        label = f"{module}/{base}"
        old_path = os.path.join(artifactdir, old, module, os.path.basename(path))
        old_doc = read_artifact(old_path) if os.path.exists(old_path) else {}
        old_va = as_int(old_doc.get("func_va"))
        new_bin, old_bin = binary_for(gamever, module, platform), binary_for(old, module, platform)
        if old_va is None or new_bin is None or old_bin is None:
            counts["SKIP"] += 1
            continue
        verdict, why = twin_verdict(new_bin, va, as_int(doc.get("func_size")) or 0,
                                    old_bin, old_va, as_int(old_doc.get("func_size")) or 0)
        if verdict == "SWAPPED" and label in accepted:
            verdict, why = "ACCEPTED", f"{why} [{accepted[label]}]"
        counts[verdict] += 1
        if verdict == "SWAPPED" or verbose and verdict != "SKIP":
            print(f"  {verdict:<8} {label} @ {va:#x} (was {old_va:#x} on {old}): {why}")
    print(f"audit_twin_identity {gamever} vs {old}: {counts['OK']} ok, {counts['SWAPPED']} swapped, "
          f"{counts['MOVED']} moved, {counts['ACCEPTED']} accepted, {counts['SKIP']} skipped")
    return counts["SWAPPED"]


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
    if capstone is None:
        print("audit_twin_identity: capstone is not installed", file=sys.stderr)
        return 2
    old = args.old or previous_gamever(args.artifactdir, args.gamever, args.bindir)
    if not old:
        print(f"audit_twin_identity: no gamever before {args.gamever!r}", file=sys.stderr)
        return 2
    platforms = [p.strip() for p in args.platform.split(",") if p.strip() in ("linux", "windows")]
    return 1 if audit(args.gamever, old, platforms, args.bindir, args.artifactdir, args.symbol, args.verbose) else 0


if __name__ == "__main__":
    sys.exit(main())
