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
  guard      abi_guard.py holds its head bytes and ABI
  xplat      the linux and the windows record, found separately, reference at least
             two of the same strings
  registered the function's address is taken (a rip-relative lea, or a pointer in data)
             right beside a string that is its own name: a script binding, a ConCommand
             (`say` beside Say_CommandHandler), a registration table
  xcalls     the linux and the windows record directly call at least two of the same
             named functions (records of this build)
  confirmed  identity_confirmed.yaml: someone verified it in the binary and wrote down how

A record with none of these is UNCONFIRMED. That is no defect while nothing reads it.
A record an enabled plugin ships must have evidence: `-shipped` exits 1 naming each
shipped unconfirmed record that is not already listed as `unproven` in
identity_confirmed.yaml (the debt known when the gate was introduced, 37 records on
14201), and autopilot runs it as a gate before pack. So a new plugin key cannot start
shipping a record nobody ever identified.
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

from audit_identity_drift import NON_FUNC_KEYS, body_regions, fingerprint
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


REGISTER_RADIUS = 0x60  # bytes of code, or of a data table, around the place the address is taken


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


def _c_string(binary: Binary, va: int):
    off = binary.va_to_off(va)
    if off is None or off == 0:
        return None
    end = binary.data.find(b"\0", off, off + 128)
    return binary.data[off:end] if end > off else None


def _strings_around_code(binary: Binary, site_va: int):
    lo = site_va - REGISTER_RADIUS
    off = binary.va_to_off(lo)
    if off is None:
        return set()
    chunk = binary.data[off: off + 2 * REGISTER_RADIUS]
    found = set()
    for match in LEA_RIP.finditer(chunk):
        pos = match.start()
        if pos + 7 <= len(chunk):
            text = _c_string(binary, lo + pos + 7 + struct.unpack_from("<i", chunk, pos + 3)[0])
            if text:
                found.add(text)
    return found


def _strings_around_pointer(binary: Binary, off: int):
    found = set()
    for slot in range(max(0, off - REGISTER_RADIUS), off + REGISTER_RADIUS, 8):
        if slot + 8 <= len(binary.data):
            text = _c_string(binary, struct.unpack_from("<Q", binary.data, slot)[0])
            if text:
                found.add(text)
    return found


def is_registered(binary: Binary, symbol: str, func_va: int) -> bool:
    names = registration_names(symbol)
    if not names or binary is None:
        return False
    for site in binary.lea_targets().get(func_va, ()):
        if names & _strings_around_code(binary, site):
            return True
    needle = struct.pack("<Q", func_va)
    start = 0
    for _ in range(16):
        off = binary.data.find(needle, start)
        if off < 0:
            break
        if off % 8 == 0 and names & _strings_around_pointer(binary, off):
            return True
        start = off + 1
    return False


def shipped_names(config_path):
    """Symbol names an enabled generator's file ships, with the config's alias map."""
    import ida_analyze_bin as A

    consumed = A.generator_consumed_names(os.path.join(SCRIPT_DIR, A.GENERATORS_DIRNAME))
    aliases = A._load_symbol_alias_map(config_path)

    def is_shipped(symbol):
        names = {symbol} | {alias.replace("::", "_") for alias in aliases.get(symbol, ())}
        return any(name in consumed for name in names)

    return is_shipped


def classify(gamever, platforms, bindir, artifactdir, confirmed):
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
        if symbol in ABI_GUARDS and platform in ABI_GUARDS[symbol]:
            evidence.append("guard")
        other = (module, symbol, "windows" if platform == "linux" else "linux")
        if other in strings_of and len(strings_of[key] & strings_of[other]) >= XPLAT_MIN_SHARED:
            evidence.append("xplat")
        if other in callees_of and len(callees_of[key] & callees_of[other]) >= XPLAT_MIN_SHARED:
            evidence.append("xcalls")
        if confirmed.get(f"{symbol}.{platform}") or confirmed.get(symbol):
            evidence.append("confirmed")
        out[key] = evidence
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
