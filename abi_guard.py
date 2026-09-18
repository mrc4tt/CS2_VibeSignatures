#!/usr/bin/env python3
"""ABI-identity guard for gamedata symbols whose *identity* (not uniqueness) has been wrong.

Background: the pipeline relocates the previous gamever's ``func_sig`` on every new
build. That keeps a sig fresh and unique, but it also faithfully propagates a wrong
*identification*: on 14176 the LLM fallback picked a ``this``-method for
``CBaseEntity_EmitSoundFilter`` and a wrapper method for ``NetworkStateChanged``; the
xref finder picked a non-virtual helper for ``CCSPlayer_MovementServices_ProcessMovement``.
All relocated cleanly through 14181 and crashed / silently broke consumers, because
callers use a different ABI. ``audit_duplicate_va.py`` cannot see this - the sigs are
unique and valid.

A second gap: for vfunc artifacts without ``func_sig`` (``CBaseTrigger_EndTouch``) the
CounterStrikeSharp generator silently keeps the *template* sig, which may resolve to a
different function than the vtable-derived ``func_va``.

This guard is deterministic (raw bytes, no IDA):
  * check  - for each guarded symbol/platform read ``bin_artifacts/<VER>/server/<sym>.<plat>.yaml``,
    map ``func_va`` into ``bin/<VER>/server/{libserver.so,server.dll}`` and verify the
    function head matches an accepted pattern and no known-bad one; verify ``func_sig``
    exists and resolves uniquely to ``func_va``; verify the CS# template sig (when the
    symbol has one) resolves to an accepted head.
  * --fix  - rewrite the failing yaml (keeping vtable_* / vfunc_* fields) and/or the
    template sig from the accepted sig.

Run it after ``sync_upstream.sh`` (upstream still carries the wrong artifacts) and before
``gamesymbol_snapshot.py pack``:

    uv run abi_guard.py                      # newest gamever, report only
    uv run abi_guard.py -gamever 14181 --fix

Finder scripts can also use ``make_llm_result_validator`` so the LLM fallback cannot
re-select a known-bad function.

Exit code 1 when a guard fails and ``--fix`` was not given (or could not fix).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import struct
import sys

CSS_TEMPLATE = os.path.join("gamedata-generators", "CounterStrikeSharp", "templates", "gamedata.json")

# One `?`/`??` per wildcard byte. Sigs below are written in gamedata style (`?`).
# `css_template_key`: key in the CounterStrikeSharp template whose sig must also land on an
# accepted head (the generator keeps the template sig when the artifact has no func_sig).
ABI_GUARDS = {
    # SndOpEventGuid_t / StartSoundEventInfo (>16 bytes) => sret. Correct target writes the
    # out-struct through the first argument before anything else.
    "CBaseEntity_EmitSoundFilter": {
        "css_template_key": "CBaseEntity_EmitSoundFilter",
        "linux": {
            "good_sig": "48 B8 00 00 00 00 FF FF FF FF 55 48 89 E5 41 57 41 56 41 55 41 54 53 48 89 FB "
            "48 81 EC ? ? ? ? 48 89 07 48 8D 05 ? ? ? ? 48 C7 47 08 00 00 00 00",
            "accept_heads": [
                "48 B8 00 00 00 00 FF FF FF FF 55 48 89 E5",  # real function
                "55 48 89 E5 53 48 89 FB 48 83 EC ? E8 ? ? ? ? 48 89 D8",  # sret thunk (upstream CS#)
            ],
            "bad_heads": ["55 48 89 E5 41 57 41 56 49 89 F6 BE"],  # `this`-method (14176-14181)
        },
        "windows": {
            "good_sig": "40 53 48 83 EC ? 4C 89 4C 24 ? 48 8B D9 45 8B C8",
            "accept_heads": ["40 53 48 83 EC ? 4C 89 4C 24 ? 48 8B D9 45 8B C8"],
            "bad_heads": ["48 89 74 24 ? 57 41 56 41 57 48 83 EC ? BE"],
        },
    },
    # void* NetworkStateChanged(void* chainEntity, CNetworkStateChangedInfo& info)
    # == CEntityInstance::NetworkStateChanged: checks entity identity flags, then reads
    # info.m_nPathIndex at +0x38.
    "NetworkStateChanged": {
        "css_template_key": "NetworkStateChanged",
        "linux": {
            "good_sig": "48 8B 07 48 85 C0 74 ? 48 8B 50",
            "accept_heads": ["48 8B 07 48 85 C0 74 ? 48 8B 50"],
            "bad_heads": ["55 48 89 E5 41 56 49 89 F6 41 55 4C 8D 2D"],  # wrapper method (14176-14181)
        },
        "windows": {
            "good_sig": "4C 8B C2 48 8B D1 48 8B 09",
            "accept_heads": ["4C 8B C2 48 8B D1 48 8B 09"],
            "bad_heads": ["48 89 5C 24 ? 48 89 6C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8B 42"],
        },
    },
    # Virtual CCSPlayer_MovementServices::ProcessMovement (vtable slot 29 linux / 28 windows on
    # 14181). The xref finder (s_pRunCommandPawn + floats) picked a non-virtual helper instead.
    "CCSPlayer_MovementServices_ProcessMovement": {
        "linux": {
            "good_sig": "55 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 53 48 89 FB 48 83 EC ? 48 8B 7F",
            "accept_heads": ["55 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 53 48 89 FB 48 83 EC ? 48 8B 7F"],
            "bad_heads": ["55 48 89 E5 41 57 49 89 FF 41 56 41 55 41 54 49 89 F4 53"],
        },
        "windows": {
            "good_sig": "40 57 41 57 48 81 EC ? ? ? ? 48 83 79",
            "accept_heads": ["40 57 41 57 48 81 EC ? ? ? ? 48 83 79"],
            "bad_heads": ["48 8B C4 48 89 58 ? 55 56 57 41 54 41 55 41 56 41 57"],
        },
    },
    # CCSPlayer_MovementServices::WalkMove(CMoveData*). Three consumers (swiftlys2, cs2kz, modsharp)
    # agree on the 0xfce-byte SIMD body; our finder's "PlayerMove_PostMove" string anchor selected a
    # small 3-argument helper instead (IDA-verified 14181).
    "CCSPlayer_MovementServices_WalkMove": {
        "linux": {
            "good_sig": "48 B8 ? ? ? ? ? ? ? ? 55 66 0F EF C0 48 89 E5 41 57 41 56 4C 8D B5 ? ? ? ? 41 55 41 BD",
            "accept_heads": ["48 B8 ? ? ? ? ? ? ? ? 55 66 0F EF C0 48 89 E5 41 57 41 56"],
            "bad_heads": ["55 48 89 E5 41 55 41 89 D5 41 54 49 89 F4 53"],
        },
        "windows": {
            "good_sig": "48 8B C4 48 89 70 ? 48 89 78 ? 55 41 54 41 55 41 56 41 57 48 8D A8 ? ? ? ? 48 81 EC ? ? ? ? 0F 29 70 ? 48 8B F1",
            "accept_heads": ["48 8B C4 48 89 70 ? 48 89 78 ? 55 41 54 41 55 41 56 41 57"],
            "bad_heads": ["40 53 56 57 48 83 EC ? 48 83 79 38 00"],
        },
    },
    # ModSharp-only overload CBaseEntity::EmitSoundFilter(filter, int, const char* soundname, float, ...).
    # Must NOT be the sret/EmitSound_t& function that CS#/CS2Fixes/plugify use.
    "CBaseEntity_EmitSoundFilter_SoundName": {
        "linux": {
            "good_sig": "55 48 89 E5 41 57 66 41 0F 7E C7 41 56 4D 89 C6",
            "accept_heads": ["55 48 89 E5 41 57 66 41 0F 7E C7 41 56 4D 89 C6"],
            "bad_heads": [
                "48 B8 00 00 00 00 FF FF FF FF 55 48 89 E5",
                "55 48 89 E5 53 48 89 FB 48 83 EC ? E8",
                "55 48 89 E5 41 57 41 56 49 89 F6 BE",
            ],
        },
        "windows": {
            "good_sig": "48 89 5C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8B DA 49 8B F9",
            "accept_heads": ["48 89 5C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8B DA 49 8B F9"],
            "bad_heads": [
                "40 53 48 83 EC ? 4C 89 4C 24 ? 48 8B D9 45 8B C8",
                "48 89 74 24 ? 57 41 56 41 57 48 83 EC ? BE",
            ],
        },
    },
    # CCSPlayer_MovementServices::FullWalkMove(CMoveData*, bool). Small dispatcher (`test dl`), NOT the
    # ~4 KB SIMD WalkMove body the pipeline shipped under this name (swiftlys2 + cs2kz agree).
    "CCSPlayer_MovementServices_FullWalkMove": {
        "linux": {
            "good_sig": "55 48 89 E5 41 54 49 89 F4 53 48 89 FB 84 D2",
            "accept_heads": ["55 48 89 E5 41 54 49 89 F4 53 48 89 FB 84 D2"],
            "bad_heads": ["48 B8 ? ? ? ? ? ? ? ? 55 66 0F EF C0 48 89 E5 41 57 41 56"],
        },
        "windows": {
            "good_sig": "48 89 5C 24 ? 57 48 83 EC ? 48 8B FA 48 8B D9 45 84 C0 75",
            "accept_heads": ["48 89 5C 24 ? 57 48 83 EC ? 48 8B FA 48 8B D9 45 84 C0 75"],
            "bad_heads": ["48 8B C4 48 89 70 ? 48 89 78 ? 55 41 54 41 55 41 56 41 57"],
        },
    },
    # Virtual CBaseTrigger::EndTouch (vtable slot 149 linux / 150 windows on 14181). The artifact
    # is vtable-derived and had no func_sig, so the CS# generator kept the stale template sig
    # (windows resolved to an unrelated function).
    "CBaseTrigger_EndTouch": {
        "css_template_key": "CBaseTrigger_EndTouch",
        "linux": {
            "good_sig": "55 BA ? ? ? ? 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 49 89 FC",
            "accept_heads": [
                "55 BA ? ? ? ? 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 49 89 FC",  # real function
                "48 85 F6 74 ? E9",  # null-check thunk in the vtable
            ],
            "bad_heads": [],
        },
        "windows": {
            "good_sig": "48 85 D2 0F 84 ? ? ? ? 53 41 57 48 83 EC ? 4C 8B 42 10",
            "accept_heads": ["48 85 D2 0F 84 ? ? ? ? 53 41 57 48 83 EC ? 4C 8B 42"],
            "bad_heads": ["40 53 41 55 48 83 EC ? 83 BA"],  # stale template target (14181)
        },
    },
}

BINARY = {"linux": "libserver.so", "windows": "server.dll"}
PE_IMAGE_BASE = 0x180000000
PLATFORMS = ("linux", "windows")


def sig_regex(sig: str) -> re.Pattern:
    parts = []
    for tok in sig.split():
        parts.append(b"." if tok in ("?", "??") else re.escape(bytes([int(tok, 16)])))
    return re.compile(b"".join(parts), re.S)


def to_yaml_sig(sig: str) -> str:
    return " ".join("??" if t in ("?", "??") else t for t in sig.split())


def to_css_sig(sig: str) -> str:
    return " ".join("?" if t in ("?", "??") else t for t in sig.split())


def sig_hits(sig: str, data: bytes) -> list[int]:
    return [m.start() for m in sig_regex(sig).finditer(data)]


# --- VA <-> file-offset mapping -------------------------------------------------------


def elf_sections(data: bytes):
    """Yield (vaddr, size, file_offset) for ELF64 PT_LOAD segments."""
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    e_phoff = struct.unpack_from("<Q", data, 0x20)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from("<IIQQQQ", data, off)
        if p_type == 1:  # PT_LOAD
            yield p_vaddr, p_filesz, p_offset


def pe_sections(data: bytes):
    """Yield (rva, raw_size, raw_offset) for PE sections."""
    if data[:2] != b"MZ":
        raise ValueError("not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise ValueError("bad PE header")
    num_sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    sec = pe + 24 + opt_size
    for i in range(num_sections):
        off = sec + i * 40
        _name, _vsize, rva, raw_size, raw_ptr = struct.unpack_from("<8sIIII", data, off)
        yield rva, raw_size, raw_ptr


def va_to_offset(data: bytes, platform: str, va: int):
    if platform == "linux":
        for vaddr, size, foff in elf_sections(data):
            if vaddr <= va < vaddr + size:
                return va - vaddr + foff
    else:
        rva = va - PE_IMAGE_BASE if va >= PE_IMAGE_BASE else va
        for srva, size, raw in pe_sections(data):
            if srva <= rva < srva + size:
                return rva - srva + raw
    return None


def offset_to_va(data: bytes, platform: str, off: int):
    if platform == "linux":
        for vaddr, size, foff in elf_sections(data):
            if foff <= off < foff + size:
                return off - foff + vaddr
    else:
        for srva, size, raw in pe_sections(data):
            if raw <= off < raw + size:
                return off - raw + srva + PE_IMAGE_BASE
    return None


def head_matches(data: bytes, off: int, patterns) -> bool:
    head = data[off : off + 64]
    return any(sig_regex(p).match(head) for p in patterns)


# --- yaml (tiny flat format used by the artifacts) --------------------------------------


def read_flat_yaml(path: str) -> dict:
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if ":" not in line or line.startswith("#"):
                continue
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def write_func_yaml(
    path: str, name: str, va: int, platform: str, size: int, sig: str, extra: dict | None = None
) -> None:
    """Write a func artifact; `extra` keeps fields we do not own (vtable_name, vfunc_index, ...)."""
    rva = va - PE_IMAGE_BASE if platform == "windows" else va
    owned = {"func_name", "func_va", "func_rva", "func_size", "func_sig"}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"func_name: {name}\n")
        f.write(f"func_va: '{va:#x}'\n")
        f.write(f"func_rva: '{rva:#x}'\n")
        f.write(f"func_size: '{size:#x}'\n")
        f.write(f"func_sig: {to_yaml_sig(sig)}\n")
        for k, v in (extra or {}).items():
            if k in owned:
                continue
            quoted = f"'{v}'" if re.fullmatch(r"0x[0-9a-fA-F]+", str(v)) else str(v)
            f.write(f"{k}: {quoted}\n")


def guess_func_size(data: bytes, off: int, limit: int = 0x2000) -> int:
    """Bytes from *off* to the end of its function, or 0 when that cannot be told.

    Scanning for the first ``ret; int3; int3`` alone over-measures: a function that
    ends on a tail ``jmp`` has no such tail of its own, so the scan runs THROUGH the
    functions after it until one does end that way. That is where 14181's
    NetworkStateChanged.linux 0xca5 (IDA: 0x55), CCSPlayer_MovementServices_
    FullWalkMove.linux 0xd23 (IDA: 0x170) and CCSPlayer_MovementServices_
    ProcessMovement.windows 0x785 (IDA: 0x67e) came from -- each swallowed at least
    one whole following function.

    An inter-function gap is padding, so a run of two or more 0xCC/0x90 bytes reached
    before the ``ret`` means the function already ended and this measurement would
    span a boundary. func_size is internal metadata that never reaches a plugin, so
    reporting 0x0 (unknown) costs nothing while a wrong value is a live defect.
    """
    end = min(len(data), off + limit)
    i = off
    while i < end - 2:
        b = data[i]
        if b == 0xC3 and data[i + 1] == 0xCC and data[i + 2] == 0xCC:
            return i + 1 - off
        if b in (0xCC, 0x90) and data[i + 1] == b and i > off:
            return 0            # padding first: another function ended here
        i += 1
    return 0


# --- LLM finder validator ---------------------------------------------------------------


def make_llm_result_validator(symbol: str, platform: str, new_binary_dir):
    """Return a synchronous `result_validator(parsed_result) -> [issues]` for preprocess_common_skill.

    Decodes each `found_call` entry's direct `call rel32` at `insn_va` in the raw binary and
    rejects targets whose head is a known-bad pattern (or, when accept patterns exist, is not
    accepted). Indirect calls cannot be decoded here and pass through unchanged.
    """
    rule = (ABI_GUARDS.get(symbol) or {}).get(platform)
    binary = os.path.join(os.fspath(new_binary_dir), BINARY.get(platform, ""))
    if not rule or not os.path.exists(binary):
        return lambda parsed_result: []
    with open(binary, "rb") as f:
        data = f.read()

    def _to_int(value):
        try:
            text = str(value).strip().replace("_", "")
            return int(text, 16) if text.lower().startswith("0x") else int(text)
        except (TypeError, ValueError):
            return None

    def validator(parsed_result):
        issues = []
        for entry in parsed_result.get("found_call", []) or []:
            if entry.get("func_name") != symbol:
                continue
            insn_va = _to_int(entry.get("insn_va"))
            off = va_to_offset(data, platform, insn_va) if insn_va is not None else None
            if off is None or data[off : off + 1] != b"\xe8":
                continue  # indirect / undecodable: leave to the MCP resolver
            rel = struct.unpack_from("<i", data, off + 1)[0]
            target_off = off + 5 + rel
            if not 0 <= target_off < len(data):
                continue
            target_va = offset_to_va(data, platform, target_off)
            if head_matches(data, target_off, rule["bad_heads"]):
                issues.append(
                    f"{symbol}: the call at {insn_va:#x} targets {target_va:#x}, a KNOWN-BAD function for this "
                    f"symbol (wrong ABI: {symbol} must be the {platform} function whose head matches "
                    f"{rule['accept_heads'][0]}). Choose the call to that function instead."
                )
            elif rule["accept_heads"] and not head_matches(data, target_off, rule["accept_heads"]):
                issues.append(
                    f"{symbol}: the call at {insn_va:#x} targets {target_va:#x} whose head does not match any "
                    f"accepted pattern ({'; '.join(rule['accept_heads'])}). Re-check the callee."
                )
        return issues

    return validator


# --- core -------------------------------------------------------------------------------


def newest_gamever(artifactdir: str):
    vers = [
        os.path.basename(p)
        for p in glob.glob(os.path.join(artifactdir, "*"))
        if re.fullmatch(r"\d+[a-z]?", os.path.basename(p))
    ]
    if not vers:
        return None

    def key(v):
        num = re.match(r"\d+", v).group(0)
        return (int(num), v[len(num) :])

    return max(vers, key=key)


def _load_binary(bindir: str, gamever: str, platform: str):
    binary = os.path.join(bindir, gamever, "server", BINARY[platform])
    if not os.path.exists(binary):
        return binary, None
    with open(binary, "rb") as f:
        return binary, f.read()


def _parse_hex(value):
    """Hex string (or int) -> int, or None when it is neither."""
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip(), 16)
    except (TypeError, ValueError):
        return None


def check_symbol(symbol, platform, rule, gamever, bindir, artifactdir, fix) -> tuple[bool, str]:
    binary, data = _load_binary(bindir, gamever, platform)
    if data is None:
        return True, f"skip {symbol}.{platform}: no binary {binary}"
    yaml_rel = os.path.join(gamever, "server", f"{symbol}.{platform}.yaml")
    art_yaml = os.path.join(artifactdir, yaml_rel)
    bin_yaml = os.path.join(bindir, yaml_rel)

    good_hits = sig_hits(rule["good_sig"], data)
    if len(good_hits) != 1:
        return (
            False,
            f"BAD {symbol}.{platform}: good_sig has {len(good_hits)} hits on {binary} - guard table needs updating",
        )
    good_off = good_hits[0]
    good_va = offset_to_va(data, platform, good_off)

    problems = []
    extra = {}
    cur_va = None
    if not os.path.exists(art_yaml):
        problems.append(f"missing {art_yaml}")
    else:
        y = read_flat_yaml(art_yaml)
        extra = y
        try:
            cur_va = int(y.get("func_va", "0"), 16)
        except ValueError:
            cur_va = None
        cur_off = va_to_offset(data, platform, cur_va) if cur_va else None
        if cur_off is None:
            problems.append(f"func_va {y.get('func_va')} not mappable into {BINARY[platform]}")
        elif head_matches(data, cur_off, rule["bad_heads"]):
            problems.append(f"func_va {cur_va:#x} has a KNOWN-BAD head (wrong function, wrong ABI)")
        elif not head_matches(data, cur_off, rule["accept_heads"]):
            problems.append(
                f"func_va {cur_va:#x} head matches no accepted pattern: {data[cur_off : cur_off + 16].hex(' ')}"
            )
        sig = y.get("func_sig")
        if not sig:
            problems.append("no func_sig (generators fall back to the template sig)")
        else:
            sh = sig_hits(sig, data)
            if len(sh) != 1:
                problems.append(f"func_sig has {len(sh)} hits")
            elif cur_off is not None and sh[0] != cur_off:
                problems.append(f"func_sig resolves to {offset_to_va(data, platform, sh[0]):#x}, not func_va")

        # A func_size written by the old guess_func_size can span a function
        # boundary even when func_va and func_sig are right, because that scan
        # ran past a tail jmp into the next function. Rule 14: an unknown size
        # costs nothing (it never reaches a plugin) and a wrong one is a defect.
        recorded_size = _parse_hex(y.get("func_size"))
        if recorded_size and cur_off is not None:
            honest_size = guess_func_size(data, cur_off)
            if honest_size != recorded_size:
                problems.append(
                    f"func_size {recorded_size:#x} is not measurable from {cur_va:#x}"
                    f" (honest measurement: {honest_size:#x})"
                )

    if not problems:
        return True, f"ok  {symbol}.{platform} @ {cur_va:#x}"

    msg = f"BAD {symbol}.{platform}: " + "; ".join(problems) + f" (correct: {good_va:#x})"
    if not fix:
        return False, msg

    size = guess_func_size(data, good_off)
    write_func_yaml(art_yaml, symbol, good_va, platform, size, rule["good_sig"], extra)
    if os.path.isdir(os.path.dirname(bin_yaml)):
        write_func_yaml(bin_yaml, symbol, good_va, platform, size, rule["good_sig"], extra)
    return True, msg + f" -> FIXED (rewrote {art_yaml})"


def check_template(symbol, rule_all, gamever, bindir, template_path, fix) -> list[tuple[bool, str]]:
    """The CS# generator keeps the template sig when the artifact lacks func_sig - keep it correct."""
    key = rule_all.get("css_template_key")
    if not key or not os.path.exists(template_path):
        return []
    with open(template_path, "r", encoding="utf-8") as f:
        raw = f.read()
    template = json.loads(raw)
    entry = template.get(key) or {}
    sigs = entry.get("signatures") or {}
    results = []
    changed = False
    for platform in PLATFORMS:
        rule = rule_all.get(platform)
        sig = sigs.get(platform)
        if not rule or not sig:
            continue
        _binary, data = _load_binary(bindir, gamever, platform)
        if data is None:
            continue
        hits = sig_hits(sig, data)
        ok = (
            len(hits) == 1
            and head_matches(data, hits[0], rule["accept_heads"])
            and not head_matches(data, hits[0], rule["bad_heads"])
        )
        if ok:
            results.append((True, f"ok  template {key}.{platform}"))
            continue
        where = (
            f"{len(hits)} hits"
            if len(hits) != 1
            else f"lands on {offset_to_va(data, platform, hits[0]):#x} (not an accepted head)"
        )
        msg = f"BAD template {key}.{platform}: {where}"
        if not fix:
            results.append((False, msg))
            continue
        sigs[platform] = to_css_sig(rule["good_sig"])
        changed = True
        results.append((True, msg + " -> FIXED"))
    if changed:
        # Rewrite only the changed values textually so the template keeps its formatting.
        for platform in PLATFORMS:
            rule = rule_all.get(platform)
            if not rule:
                continue
            block = re.search(r'"%s": \{.*?\n  \}' % re.escape(key), raw, re.S)
            if not block:
                continue
            new_block = re.sub(
                r'"%s": "[^"]*"' % platform, f'"{platform}": "{to_css_sig(rule["good_sig"])}"', block.group(0)
            )
            raw = raw.replace(block.group(0), new_block)
        json.loads(raw)
        with open(template_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(raw)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-gamever", help="game version (default: newest in bin_artifacts/)")
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-artifactdir", default="bin_artifacts")
    ap.add_argument("-template", default=CSS_TEMPLATE, help="CounterStrikeSharp template gamedata.json")
    ap.add_argument("-platform", default="windows,linux")
    ap.add_argument("--fix", action="store_true", help="rewrite failing yaml / template sig from the accepted sig")
    args = ap.parse_args(argv)

    gamever = args.gamever or newest_gamever(args.artifactdir)
    if not gamever:
        print("abi_guard: no gamever found", file=sys.stderr)
        return 2
    platforms = [p.strip() for p in args.platform.split(",") if p.strip()]

    failed = 0
    print(f"abi_guard: gamever {gamever}")
    for symbol, per_plat in ABI_GUARDS.items():
        for platform in platforms:
            rule = per_plat.get(platform)
            if not rule:
                continue
            ok, msg = check_symbol(symbol, platform, rule, gamever, args.bindir, args.artifactdir, args.fix)
            print("  " + msg)
            failed += 0 if ok else 1
        for ok, msg in check_template(symbol, per_plat, gamever, args.bindir, args.template, args.fix):
            print("  " + msg)
            failed += 0 if ok else 1
    if failed:
        print(f"abi_guard: {failed} guard(s) failed" + ("" if args.fix else " - rerun with --fix"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
