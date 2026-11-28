#!/usr/bin/env python3
"""Say, for every function record, what proves it is the function its name says.

A unique signature on a clean function head proves PLACEMENT: the record points at a
function. It does not prove IDENTITY: that the function is the one the record is named
after. Every other check re-reads the record from where it already points, so a record
that names the wrong function passes all of them - on 14201 five such records had been
relocated faithfully since 14190 (CCSBot_Idle.linux on EscapeFromBomb's setter). All
five came from an LLM decompile match, and nothing read them, so nothing was lost; the
day a plugin ships such a key it would hook the wrong function.

Evidence that counts, each independent of the record's own signature:

  anchor     the function references the string / byte pattern its finder is anchored
             on (audit_xref_identity's judgement)
  selfname   it references a string that spells its own method name
  slot       it sits in a named class's vtable at a recorded slot (validate_artifacts
             confirms the slot through RTTI, audit_vtable_slots that it did not shift)
  vtable     a plain function record (no slot fields) named Class_Method whose address
             is an entry of Class's RTTI vtable: it is a virtual of that class
  ctor       named Class_Class / Class_ctor, takes the address of Class's RTTI vtable
             and is not itself an entry of it (a destructor is)
  guard      abi_guard.py holds its head bytes and ABI
  xplat      the linux and the windows record, found separately, reference at least
             two of the same strings
  registered the function's address is taken together with a string that is its own
             name: in the same call's arguments, or as the nearest name in a data table.
             A script binding, a ConCommand (`say` beside Say_CommandHandler). Also when
             the function's ONLY caller is registered that way (the binding thunk)
  xcalls     the linux and the windows record directly call at least two of the same
             named functions (records of this build)
  xcallers   ... are directly called from at least two of the same named functions
  xmixed     ... share two things across those kinds (one string and one named caller,
             one named callee and one named caller) without two of any one kind
  carried    only while the other platform has not been analysed yet (the linux-first
             release): the same record had evidence on the previous gamever, and the
             relocation gates (drift, slot, twin) are what carry an identity forward
  confirmed  identity_confirmed.yaml: someone verified it in the binary and wrote down how

A record with none of these is UNCONFIRMED. That is no defect while nothing reads it.
A record an enabled plugin ships must have evidence: `-shipped` exits 1 naming each
shipped unconfirmed record that is not listed as `unproven` in identity_confirmed.yaml
(a debt list that is empty and meant to stay so), and autopilot runs it as a gate before
pack. So a new plugin key cannot start shipping a record nobody ever identified.

The x* kinds prove the two platforms name the same function, which rules out one
platform being wrong - not both being wrong the same way.
To clear one, verify it in the binary on that platform (rule 12: string set, call graph
or decompile - not size, not the signature) and either give its finder an anchor or add
it to identity_confirmed.yaml with the evidence. Once confirmed, the relocation gates
(drift, slot, twin) carry the identity from build to build.

    uv run audit_identity_evidence.py -gamever 14201             # totals per kind
    uv run audit_identity_evidence.py -gamever 14201 -shipped    # the gate
    uv run audit_identity_evidence.py -gamever 14201 -list       # every unconfirmed record

Exit 0, or 1 with -shipped when a shipped record is unconfirmed.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import struct
import sys

import yaml

from audit_identity_drift import NON_FUNC_KEYS, body_regions, fingerprint, previous_gamever
from audit_xref_identity import LEA_RIP, Binary, as_int, find_binary, judge, load_specs, read_artifact

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIRMED = "identity_confirmed.yaml"
XPLAT_MIN_SHARED = 2
SELFNAME_MIN = 6  # "Think", "Spawn", "Init" are in too many strings to name a function


def load_confirmed(path=CONFIRMED):
    """({'Symbol' or 'Symbol.platform': evidence}, {'Symbol.platform' known as unproven})."""
    if not os.path.isfile(path):
        return {}, set()
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    confirmed = {str(key): str(value) for key, value in (data.get("confirmed") or {}).items()}
    return confirmed, {str(item) for item in (data.get("unproven") or [])}


def method_token(symbol: str):
    """The method part of Class_Method, when it is long enough to be telling."""
    token = symbol.rsplit("_", 1)[-1]
    return token if len(token) >= SELFNAME_MIN and not token.isdigit() else None


def names_itself(symbol: str, strings) -> bool:
    token = method_token(symbol)
    if not token:
        return False
    pattern = re.compile(rb"(?<![A-Za-z0-9])" + re.escape(token.encode()) + rb"(?![A-Za-z0-9])")
    return any(pattern.search(text) for text in strings)


REGISTER_RADIUS = 0x60  # bytes of a data table around the pointer, or of code to resynchronise in
IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*\Z")
REL32_BRANCH = re.compile(rb"[\xe8\xe9]")


def registration_names(symbol: str):
    """Exact strings a registration of this function would carry: its method name, and for
    X_CommandHandler the command itself (SayTeam_CommandHandler -> say_team)."""
    names = set()
    token = symbol.rsplit("_", 1)[-1]
    if len(token) >= SELFNAME_MIN:
        names.add(token)
    if symbol.endswith("_CommandHandler"):
        command = symbol[: -len("_CommandHandler")]
        names.add(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", command).lower())
    return {name.encode() for name in names}


def _c_string(binary, va: int):
    off = binary.va_to_off(va)
    if off is None or off == 0:
        return None
    end = binary.data.find(b"\0", off, off + 128)
    return binary.data[off:end] if end > off else None


def _call_setup(binary, site_va: int):
    """Instructions of the argument block the lea at site_va belongs to: from the call
    before it to the call after it. [] without capstone or when no decode lines up."""
    try:
        import capstone
    except ImportError:
        return []
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    # From the head of the enclosing function first: a decode started mid-code can fall
    # into step with the site a few instructions late and miss what stands before it.
    head = binary.enclosing(site_va)[0]
    starts = ([head] if head <= site_va else []) + [site_va - back for back in range(REGISTER_RADIUS, -1, -1)]
    for start in starts:
        off = binary.va_to_off(start)
        if off is None:
            continue
        insns = list(md.disasm(binary.data[off: off + (site_va - start) + REGISTER_RADIUS], start))
        at = next((i for i, insn in enumerate(insns) if insn.address == site_va), None)
        if at is None:
            continue  # this start is not on an instruction boundary that reaches the site
        first = at
        while first > 0 and insns[first - 1].mnemonic != "call":
            first -= 1
        last = at
        while last < len(insns) - 1 and insns[last].mnemonic != "call":
            last += 1
        return insns[first: last + 1]
    return []


def _names_in_call_setup(binary, site_va: int):
    found = set()
    for insn in _call_setup(binary, site_va):
        raw = bytes(insn.bytes)
        if insn.address != site_va and len(raw) == 7 and LEA_RIP.match(raw):
            text = _c_string(binary, insn.address + 7 + struct.unpack_from("<i", raw, 3)[0])
            if text:
                found.add(text)
    return found


def _nearest_name_in_table(binary, off: int):
    """The identifier-like string whose pointer sits closest to the pointer at off."""
    best = None
    for slot in range(max(0, off - REGISTER_RADIUS), off + REGISTER_RADIUS + 8, 8):
        if slot == off or slot + 8 > len(binary.data):
            continue
        text = _c_string(binary, struct.unpack_from("<Q", binary.data, slot)[0])
        if text and IDENTIFIER.match(text) and (best is None or abs(slot - off) < best[0]):
            best = (abs(slot - off), text)
    return best[1] if best else None


def _registered_here(binary, names, func_va: int) -> bool:
    for site in binary.lea_targets().get(func_va, ()):
        if names & _names_in_call_setup(binary, site):
            return True
    needle = struct.pack("<Q", func_va)
    start = 0
    for _ in range(16):
        off = binary.data.find(needle, start)
        if off < 0:
            break
        if off % 8 == 0 and _nearest_name_in_table(binary, off) in names:
            return True
        start = off + 1
    return False


def branch_sources(binary):
    """{target_va: [site_va]} of every call/jmp rel32 in executable code (byte scan: a
    stray E8/E9 inside another instruction only ever ADDS a source, which can cost a
    function its "only caller", never invent one)."""
    table = getattr(binary, "_branch_sources", None)
    if table is None:
        table = {}
        for seg_va, size, seg_off, executable in getattr(binary, "segments", ()):
            if not executable:
                continue
            chunk = binary.data[seg_off: seg_off + size]
            for match in REL32_BRANCH.finditer(chunk):
                pos = match.start()
                if pos + 5 <= len(chunk):
                    table.setdefault(seg_va + pos + 5 + struct.unpack_from("<i", chunk, pos + 1)[0], []).append(seg_va + pos)
        binary._branch_sources = table
    return table


def is_registered(binary, symbol: str, func_va: int) -> bool:
    """The function's address is taken beside its own name - or, when it has exactly one
    caller, that caller's is: a script binding is a thunk registered under the name, and
    the function it alone calls is what the name runs."""
    names = registration_names(symbol)
    if not names or binary is None:
        return False
    if _registered_here(binary, names, func_va):
        return True
    callers = {binary.enclosing(site)[0] for site in branch_sources(binary).get(func_va, ())}
    callers.discard(func_va)
    return len(callers) == 1 and _registered_here(binary, names, next(iter(callers)))


_RTTI = {}


def class_vtables(bindir, gamever, module, platform, class_name):
    """[(vtable_va, [slot targets])] of a class through RTTI, [] when it has none."""
    import validate_artifacts as V
    from auto_hunt_headless import BIN_LINUX, BIN_WIN, load_binary

    key = (module, platform)
    if key not in _RTTI:
        name = (BIN_LINUX if platform == "linux" else BIN_WIN).get(module)
        path = os.path.join(bindir, gamever, module, name) if name else None
        if not path or not os.path.exists(path):
            _RTTI[key] = None
        else:
            blob, info = load_binary(path)
            _RTTI[key] = (blob, info, V.elf_relocations(blob) if info["type"] == "elf" else None, {})
    if _RTTI[key] is None:
        return []
    blob, info, relocs, cache = _RTTI[key]
    if class_name not in cache:
        try:
            cache[class_name] = V.resolve_vtable(blob, info, relocs, class_name)
        except Exception:  # noqa: BLE001 - no RTTI for this name is simply no evidence
            cache[class_name] = []
    return cache[class_name]


def class_evidence(bindir, gamever, module, platform, symbol, func_va, binary, size):
    """'vtable' | 'ctor' | None for a plain function record named Class_Method."""
    class_name, _, method = symbol.rpartition("_")
    if not class_name or not method:
        return None
    is_ctor = method in ("ctor", class_name)
    tables = class_vtables(bindir, gamever, module, platform, class_name)
    if not tables:
        return None
    in_table = any(func_va in slots for _vt, slots in tables)
    if not is_ctor:
        return "vtable" if in_table else None
    if in_table or binary is None or size <= 0:
        return None
    off = binary.va_to_off(func_va)
    body = binary.data[off: off + size] if off is not None else b""
    starts = {vt for vt, _slots in tables}
    for match in LEA_RIP.finditer(body):
        pos = match.start()
        if pos + 7 <= len(body) and func_va + pos + 7 + struct.unpack_from("<i", body, pos + 3)[0] in starts:
            return "ctor"
    return None


def shipped_names(config_path):
    """Symbol names an enabled generator's file ships, with the config's alias map."""
    import ida_analyze_bin as A

    consumed = A.generator_consumed_names(os.path.join(SCRIPT_DIR, A.GENERATORS_DIRNAME))
    aliases = A._load_symbol_alias_map(config_path)

    def is_shipped(symbol):
        names = {symbol} | {alias.replace("::", "_") for alias in aliases.get(symbol, ())}
        return any(name in consumed for name in names)

    return is_shipped


def classify(gamever, platforms, bindir, artifactdir, confirmed, carry=True):
    """{(module, symbol, platform): [evidence kinds]} for every function record."""
    specs, _unreadable = load_specs(None)
    try:
        from abi_guard import ABI_GUARDS
    except Exception:  # noqa: BLE001 - the guard table is evidence, not a requirement
        ABI_GUARDS = {}
    binaries, schemas, strings_of, records, callees_of = {}, {}, {}, {}, {}

    def binary_for(module, platform):
        key = (module, platform)
        if key not in binaries:
            path = find_binary(bindir, gamever, module, platform)
            binaries[key] = Binary(path, platform) if path else None
        return binaries[key]

    for path in sorted(glob.glob(os.path.join(artifactdir, gamever, "*", "*.yaml"))):
        module = os.path.basename(os.path.dirname(path))
        symbol, _, platform = os.path.basename(path)[: -len(".yaml")].rpartition(".")
        if platform not in ("linux", "windows"):
            continue
        doc = read_artifact(path)
        va = as_int(doc.get("func_va"))
        if va is None or any(k in doc for k in NON_FUNC_KEYS):
            continue
        binary = binary_for(module, platform)
        size = as_int(doc.get("func_size")) or 0
        strings = fingerprint(binary, va, size)[0] if binary is not None else set()
        records[(module, symbol, platform)] = (doc, va, size, binary)
        strings_of[(module, symbol, platform)] = strings

    # names of the functions each record calls directly: {(module, platform): {va: symbol}}
    named = {}
    for (module, symbol, platform), (_doc, va, _size, _binary) in records.items():
        named.setdefault((module, platform), {}).setdefault(va, symbol)
    for key, (_doc, va, size, binary) in records.items():
        module, symbol, platform = key
        by_va = named.get((module, platform), {})
        targets = binary.direct_callees(body_regions(binary, va, size)) if binary is not None else []
        callees_of[key] = {by_va[t] for t in targets if t in by_va and by_va[t] != symbol}

    # and of the functions that call it: a call site belongs to the record whose body holds it
    callers_of = {}
    spans = {}
    for (module, symbol, platform), (_doc, va, size, _binary) in records.items():
        if size > 0:
            spans.setdefault((module, platform), []).append((va, va + size, symbol))
    for group in spans.values():
        group.sort()
    import bisect
    for key, (_doc, va, _size, binary) in records.items():
        module, symbol, platform = key
        group = spans.get((module, platform), [])
        starts = [span[0] for span in group]
        found = set()
        for site in (branch_sources(binary).get(va, ()) if binary is not None else ()):
            at = bisect.bisect_right(starts, site) - 1
            if at >= 0 and group[at][0] <= site < group[at][1] and group[at][2] != symbol:
                found.add(group[at][2])
        callers_of[key] = found

    out = {}
    for key, (doc, va, size, binary) in records.items():
        module, symbol, platform = key
        if platform not in platforms:
            continue
        evidence = []
        entry = specs.get(symbol, {}).get(platform)
        if entry and binary is not None:
            primary = entry[0]
            verdict, _message = judge(binary, schemas, gamever, bindir, module, platform, symbol, doc, va, size,
                                      primary["strings"], primary["exclude"], primary["signatures"], entry[1:])
            if verdict == "OK":
                evidence.append("anchor")
        if names_itself(symbol, strings_of[key]):
            evidence.append("selfname")
        if is_registered(binary, symbol, va):
            evidence.append("registered")
        if doc.get("vtable_name") and doc.get("vfunc_index") is not None:
            evidence.append("slot")
        elif not evidence:
            kind = class_evidence(bindir, gamever, module, platform, symbol, va, binary, size)
            if kind:
                evidence.append(kind)
        if symbol in ABI_GUARDS and platform in ABI_GUARDS[symbol]:
            evidence.append("guard")
        other = (module, symbol, "windows" if platform == "linux" else "linux")
        if other in strings_of and len(strings_of[key] & strings_of[other]) >= XPLAT_MIN_SHARED:
            evidence.append("xplat")
        if other in strings_of:
            shared = (len(strings_of[key] & strings_of[other]), len(callees_of[key] & callees_of[other]),
                      len(callers_of[key] & callers_of[other]))
            if shared[1] >= XPLAT_MIN_SHARED:
                evidence.append("xcalls")
            if shared[2] >= XPLAT_MIN_SHARED:
                evidence.append("xcallers")
            if max(shared) < XPLAT_MIN_SHARED <= sum(shared):
                evidence.append("xmixed")
        if confirmed.get(f"{symbol}.{platform}") or confirmed.get(symbol):
            evidence.append("confirmed")
        out[key] = evidence
    # Linux-first: this build has no windows records yet, so nothing can agree across
    # platforms. A record that had evidence on the previous build keeps it until the
    # other platform arrives and the full gate judges it again.
    waiting = [key for key, found in out.items()
               if not found and (key[0], key[1], "windows" if key[2] == "linux" else "linux") not in records]
    if waiting and carry:
        old = previous_gamever(artifactdir, gamever, bindir)
        if old:
            before = classify(old, ["linux", "windows"], bindir, artifactdir, confirmed, carry=False)
            for key in waiting:
                if before.get(key):
                    out[key] = ["carried"]
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-platform", default="linux,windows")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-artifactdir", default="bin_artifacts")
    parser.add_argument("-shipped", action="store_true", help="fail on an unconfirmed record a plugin ships")
    parser.add_argument("-list", action="store_true", help="name every unconfirmed record, shipped or not")
    args = parser.parse_args(argv)
    os.chdir(SCRIPT_DIR)
    platforms = [p.strip() for p in args.platform.split(",") if p.strip() in ("linux", "windows")]
    confirmed, unproven = load_confirmed()
    evidence = classify(args.gamever, platforms, args.bindir, args.artifactdir, confirmed)
    is_shipped = shipped_names(os.path.join("configs", f"{args.gamever}.yaml"))

    kinds = {}
    new_shipped, known_shipped, unread = [], [], []
    for (module, symbol, platform), found in sorted(evidence.items()):
        for kind in found:
            kinds[kind] = kinds.get(kind, 0) + 1
        if found:
            continue
        label = f"{module}/{symbol}.{platform}"
        if not is_shipped(symbol):
            unread.append(label)
        elif f"{symbol}.{platform}" in unproven:
            known_shipped.append(label)
        else:
            new_shipped.append(label)
    for label in new_shipped:
        print(f"  UNCONFIRMED (shipped)  {label}")
    if args.list:
        for label in known_shipped:
            print(f"  unproven (shipped)     {label}")
        for label in unread:
            print(f"  unconfirmed            {label}")
    # an entry that no longer does anything: the record is gone, or has evidence of its own
    records = {f"{symbol}.{platform}": found for (_m, symbol, platform), found in evidence.items()}
    symbols = {key.rsplit(".", 1)[0] for key in records}
    for entry in sorted(confirmed):
        if entry not in records and entry not in symbols:
            print(f"  stale    {entry}: confirmed in {CONFIRMED}, no such function record on {args.gamever}")
    for entry in sorted(unproven):
        if entry.rsplit(".", 1)[-1] not in platforms:
            continue
        if entry not in records:
            print(f"  stale    {entry}: unproven in {CONFIRMED}, no such function record on {args.gamever}")
        elif records[entry]:
            print(f"  stale    {entry}: unproven in {CONFIRMED}, now has evidence ({', '.join(records[entry])}) - remove it")
    total = len(evidence)
    with_evidence = total - len(new_shipped) - len(known_shipped) - len(unread)
    print(f"audit_identity_evidence {args.gamever}: {total} function records, {with_evidence} with evidence "
          f"({', '.join(f'{kind} {count}' for kind, count in sorted(kinds.items()))}); shipped without: "
          f"{len(new_shipped)} new, {len(known_shipped)} known unproven; {len(unread)} unconfirmed that no plugin ships")
    return 1 if args.shipped and new_shipped else 0


if __name__ == "__main__":
    sys.exit(main())
