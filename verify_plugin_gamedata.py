#!/usr/bin/env python3
"""Verify a plugin's shipped gamedata.json against the binaries and this analysis.

validate_artifacts.py answers "are OUR artifacts right". This answers the question a
server owner actually has: "is every entry in the file my plugin loads still correct".
Two independent checks per entry, because they catch different failures:

  signatures  scanned against the platform binary. Exactly one match is healthy;
              zero means the pattern no longer resolves and the plugin will fail to
              find the function; more than one means it is ambiguous and the plugin
              may hook the wrong address. A match that does not land on a function
              head is reported too - it resolves today but is anchored mid-function.

  offsets     an integer cannot be scanned for, so it is compared against this
              repo's record for the same symbol, and where that record names a
              class the vtable slot is re-read from the binary via RTTI. Names are
              folded (A::b, A.b and A_b are one key) because plugins and the
              analysis spell them differently.

  vtable      a signature entry's "vtable" slot (CounterStrikeSharp) is re-read from the
              class's PRIMARY vtable and must hold the function the signature resolves to.

Exit code is non-zero when anything is broken or ambiguous, so it can gate a deploy.

  uv run verify_plugin_gamedata.py -gamever 14181 \
      -gamedata gamedata/14181/CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json
"""

import argparse
import json
import os
import re
import struct
import sys
import zlib

import validate_artifacts as V

# CSS spells the library the way the module is named here; a few plugins use the
# binary's own name instead, so both spellings map to one module.
LIBRARY_TO_MODULE = {
    "server": "server", "engine": "engine", "engine2": "engine",
    "client": "client", "networksystem": "networksystem",
    "scenesystem": "scenesystem", "matchmaking": "matchmaking",
    "vphysics2": "vphysics2", "sdl3": "SDL3", "SDL3": "SDL3",
    "worldrenderer": "worldrenderer", "tier0": "tier0",
}

BIN_LINUX = {"server": "libserver.so", "engine": "libengine2.so", "client": "libclient.so",
             "networksystem": "libnetworksystem.so", "scenesystem": "libscenesystem.so",
             "matchmaking": "libmatchmaking.so", "vphysics2": "libvphysics2.so",
             "SDL3": "libSDL3.so.0", "worldrenderer": "libworldrenderer.so",
             "tier0": "libtier0.so"}
BIN_WIN = {"server": "server.dll", "engine": "engine2.dll", "client": "client.dll",
           "networksystem": "networksystem.dll", "scenesystem": "scenesystem.dll",
           "matchmaking": "matchmaking.dll", "vphysics2": "vphysics2.dll",
           "SDL3": "SDL3.dll", "worldrenderer": "worldrenderer.dll",
           "tier0": "tier0.dll"}

PLATFORMS = ("linux", "windows")

# Plugins spell the platform three ways; plugify uses the Source 2 directory names.
# Wrapper keys that name a KIND rather than a symbol.
KIND_WORDS = {"signature", "signatures", "offset", "offsets", "patch", "patches",
              "address", "addresses", "games", "csgo", "library"}

PLATFORM_ALIASES = {"linux": "linux", "windows": "windows",
                    "linuxsteamrt64": "linux", "win64": "windows",
                    "linux64": "linux", "win32": "windows"}


def fold(name):
    """A::b, A.b and A_b are one key."""
    return re.sub(r"[^a-z0-9]", "", str(name).replace("::", "_").replace(".", "_").lower())


def load_alias_map(config_path):
    """{folded downstream key: canonical symbol name} from the analysis config.

    A symbol's own name and every entry in its `alias` list are downstream gamedata
    keys, so a plugin can legitimately ship a key that no artifact is named after -
    GameEntitySystem is CGameResourceService_m_pEntitySystem, SetStateChanged is
    CEntityInstance_NetworkStateChanged. Without this the entry reads as
    no-reference even though the analysis covers it.
    """
    from gamedata_symbol_data import load_config
    config = load_config(config_path)
    out = {}
    for module in config.get("modules", []) or []:
        blocks = list(module.get("stages") or []) + [module]
        for block in blocks:
            for symbol in (block.get("symbols") or []):
                name = symbol.get("name")
                if not name:
                    continue
                for key in [name] + list(symbol.get("alias") or []):
                    out.setdefault(fold(key), name)
    return out


def load_snapshot_index(path):
    """{folded symbol name: {platform: payload}} from a packed snapshot.

    The snapshot keys every record by "<module>/<Symbol>.<platform>.yaml", and the
    module matters: a vtable can only be re-read from the binary that holds the class,
    so CEntityResourceManifest has to be looked up in engine, not server. The module
    is carried on the payload as _module rather than guessed later.
    """
    import yaml
    with open(path, "r", encoding="utf-8") as handle:
        files = yaml.safe_load(handle).get("files") or {}
    index = {}
    for artifact_path, payload in files.items():
        parts = artifact_path.split("/")
        base = parts[-1]
        module = parts[-2] if len(parts) > 1 else None
        for platform in PLATFORMS:
            suffix = f".{platform}.yaml"
            if base.endswith(suffix):
                if isinstance(payload, dict) and module:
                    payload = dict(payload, _module=module, _symbol=base[: -len(suffix)])
                index.setdefault(fold(base[: -len(suffix)]), {})[platform] = payload
    return index


# -- gamedata formats -------------------------------------------------------
# Four shapes are in the wild, and the tool must not guess:
#   1. flat JSON            {"Key": {"signatures": {"library", "linux", "windows"}}}
#   2. sectioned JSONC      {"Signatures": {...}, "Offsets": {...}, "Patches": {...}}
#   3. Valve KeyValues .txt "Games" { "csgo" { "Signatures" { "Key" { ... } } } }
#   4. flat key=value       recipient_slot_offset_windows=576   (CS2FOW)
# Shape 4 is not symbol-keyed at all - the platform is a name suffix and the values
# are sizes, CRC32s and module RVAs - so it cannot be checked against symbol records
# and is reported rather than half-verified.

def _strip_jsonc(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(^|\s)//[^\n]*", "", text)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _kv_wildcards(raw):
    r"""Valve KV sigs are \xAA escapes, and \x2A is their wildcard convention.

    Note this is the opposite of an artifact, where 2A is the literal byte 0x2A.
    """
    out = []
    for byte in re.findall(r"\\x([0-9A-Fa-f]{2})", str(raw)):
        out.append("??" if byte.upper() == "2A" else byte.upper())
    return " ".join(out)


def _parse_kv(text):
    """Minimal Valve KeyValues -> nested dicts. Quoted keys, braces, // comments."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack, root, pending = [{}], {}, None
    stack[0] = root
    for quoted, brace in tokens:
        if brace == "{":
            child = {}
            if pending is not None:
                stack[-1][pending] = child
                pending = None
            stack.append(child)
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif pending is None:
            pending = quoted
        else:
            stack[-1][pending] = quoted
            pending = None
    return root


def _walk_entries(node, path=()):
    """Every dict that names platform keys directly is one gamedata entry.

    Going by shape rather than by section name is what makes this work across the
    formats in the wild: flat JSON, "Signatures"/"Offsets"/"Patches" sections, the
    singular "Offset" cs2surf uses, and Valve KeyValues nested under Games > csgo.
    The entry's kind comes from the VALUE type - an int is an offset, a string is a
    byte pattern - because the section name is not reliable and is sometimes absent.
    """
    if not isinstance(node, dict):
        return
    platform_values = {}
    for key, value in node.items():
        platform = PLATFORM_ALIASES.get(str(key).lower())
        if platform and not isinstance(value, dict):
            platform_values[platform] = value
    if platform_values:
        # The node holding the platform keys may itself be a wrapper - CSS nests them
        # under "signatures", CS2Fixes under a "Signatures" section, cs2surf under
        # "Offset" - so the entry name is the nearest ancestor key that is not one of
        # those kind words, and the kind word (when present) is only a hint.
        # The kind word can sit ABOVE the name as well as below it: CSS nests
        # platforms under "signatures" (Key > signatures > linux) while CS2Fixes
        # sections them above (Patches > Key > linux). Stopping at the name found
        # the first shape and missed the second, so every CS2Fixes patch was
        # scanned as a signature and reported broken for carrying replacement
        # bytes that are not supposed to occur in the binary.
        name, hint = "?", None
        for key in reversed(path):
            lowered = str(key).lower()
            if lowered in KIND_WORDS:
                if hint is None:
                    hint = lowered
                continue
            if name == "?":
                name = key
        sample = next(iter(platform_values.values()))
        kind = "offset" if isinstance(sample, (int, float)) and not isinstance(sample, bool) else "signature"
        if kind == "signature" and isinstance(sample, str) and re.fullmatch(r"\s*\d+\s*", sample):
            kind = "offset"
        if hint and "patch" in hint:
            kind = "patch"
        elif hint and "sig" in hint:
            kind = "signature" if kind == "signature" else kind
        yield name, {"kind": kind,
                     # SwiftlyS2 spells it "lib"
                     "library": node.get("library") or node.get("Library") or node.get("lib"),
                     "values": platform_values}
        return
    for key, value in node.items():
        yield from _walk_entries(value, path + (key,))


def load_gamedata(path):
    """-> (entries, note). entries: {key: {kind, library, values{platform: value}}}."""
    text = open(path, "r", encoding="utf-8-sig").read()
    data = None
    for parse in (json.loads, lambda t: json.loads(_strip_jsonc(t))):
        try:
            data = parse(text)
            break
        except Exception:
            continue
    if data is None and '"' in text and "{" in text:
        data = _parse_kv(text)
    if not isinstance(data, dict) or not data:
        if re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=", text, re.M):
            return {}, ("flat key=value file: the platform is a name suffix and the "
                        "values are sizes, CRC32s and module RVAs, so there are no "
                        "symbol keys to check against the analysis")
        return {}, "unrecognised format (not JSON, JSONC or KeyValues)"

    entries = {}
    for name, entry in _walk_entries(data):
        values = {}
        for platform, value in entry["values"].items():
            if entry["kind"] == "signature" and isinstance(value, str) and "\\x" in value:
                value = _kv_wildcards(value)
            values[platform] = value
        entry["values"] = values
        entries.setdefault(name, entry)
    if not entries:
        return {}, "parsed, but no entry names a linux/windows value"
    return entries, None


class Binaries:
    """Lazily opened binaries, one per module and platform."""

    def __init__(self, bindir, gamever):
        self.bindir, self.gamever = bindir, str(gamever)
        self.root = os.path.join(bindir, gamever)
        self.cache = {}
        self.schemas = {}

    def schema(self, module, platform):
        """The game's schema classes for a module, or None when it has none here."""
        key = (module, platform)
        if key not in self.schemas:
            try:
                import schema_dump
                self.schemas[key] = (schema_dump.load_or_dump(self.gamever, module, platform, self.bindir)
                                     if key in schema_dump.BINARY_NAMES else None)
            except Exception:  # noqa: BLE001 - no schema is "cannot confirm", not a failure
                self.schemas[key] = None
        return self.schemas[key]

    def get(self, module, platform):
        key = (module, platform)
        if key not in self.cache:
            names = BIN_LINUX if platform == "linux" else BIN_WIN
            name = names.get(module)
            path = os.path.join(self.root, module, name) if name else None
            if not path or not os.path.isfile(path):
                self.cache[key] = (None, None, None)
            else:
                blob, info = V.load_binary(path)
                relocs = V.elf_relocations(blob) if info["type"] == "elf" else None
                self.cache[key] = (blob, info, relocs)
        return self.cache[key]


def _rip_target(blob, info, va):
    """The global a RIP-relative instruction at `va` addresses, or None."""
    try:
        import capstone
    except ImportError:
        return None
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    off = V.va_to_off(info, va)
    if off is None:
        return None
    for ins in md.disasm(blob[off:off + 16], va):
        for operand in ins.operands:
            if (operand.type == capstone.x86.X86_OP_MEM
                    and operand.mem.base == capstone.x86.X86_REG_RIP):
                return ins.address + ins.size + operand.mem.disp
        return None  # only the matched instruction counts
    return None


# -- flat key=value files (CS2FOW) ------------------------------------------
# The platform is a name suffix and the values are integers, so there are no symbol
# names to fold. That turns out not to matter: an RVA or a vtable index can be looked
# up in our own records BY VALUE, and a hit both identifies the symbol and verifies
# it, with no name mapping to guess. Binary size and CRC32 need no analysis at all -
# they are checked against the file, and they are the strongest statement in any
# gamedata file: this data was made for exactly this build.

def parse_keyvalue_file(text):
    """-> {name: {kind, values{platform: int}}} for `name_<platform>=<int>` lines."""
    entries = {}
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        platform = None
        for suffix, canonical in (("_windows", "windows"), ("_linux", "linux")):
            if key.endswith(suffix):
                platform, key = canonical, key[: -len(suffix)]
                break
        if platform is None or not re.fullmatch(r"-?\d+", value):
            continue
        if key.endswith("_rva"):
            kind = "rva"
        elif key.endswith("_index"):
            kind = "vfunc-index"
        elif key.endswith("_crc32"):
            kind = "crc32"
        elif key.endswith("_size"):
            kind = "size"
        else:
            kind = "offset-int"
        entries.setdefault(key, {"kind": kind, "values": {}})["values"][platform] = int(value)
    return entries


def _value_index(index, field_names):
    """{(value, platform): [names]} over the given numeric fields of every record."""
    out = {}
    for name, per_platform in index.items():
        for platform, payload in per_platform.items():
            if not isinstance(payload, dict):
                continue
            for field in field_names:
                raw = payload.get(field)
                if raw in (None, ""):
                    continue
                try:
                    value = int(str(raw), 16) if str(raw).startswith("0x") else int(raw)
                except (TypeError, ValueError):
                    continue
                label = (payload.get("func_name") or payload.get("gv_name")
                         or payload.get("patch_name"))
                if not label and payload.get("struct_name"):
                    label = f"{payload['struct_name']}::{payload.get('member_name','?')}"
                if not label and payload.get("vtable_class"):
                    label = f"{payload['vtable_class']}_vtable"
                label = label or name
                out.setdefault((value, platform), []).append(f"{label}.{field}")
    return out


# A generator's own field name -> the snapshot record field holding that value.
_RECORD_FIELD = {"struct_member_offset": "offset", "func_rva": "func_rva", "vtable_rva": "vtable_rva",
                 "gv_rva": "gv_rva", "vfunc_index": "vfunc_index"}


def generator_keyvalue_bindings(plugin, modules_dir="gamedata-generators"):
    """{key: (module, symbol, record field)} from the generator that writes a key=value
    file (CS2FOW's SYMBOL_FIELDS). With it each key is checked against the ONE symbol it
    was generated from; without it the value is looked up among every record, and small
    numbers collide - smoke_storage_offset=112 matched three members and proved nothing."""
    path = os.path.join(modules_dir, plugin or "", "gamedata.py")
    if not plugin or not os.path.isfile(path):
        return {}
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"_gen_{plugin}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - an unloadable generator just means no bindings
        return {}
    out = {}
    for key, spec_tuple in (getattr(module, "SYMBOL_FIELDS", None) or {}).items():
        lib, symbol, field = spec_tuple
        out[key] = (lib, symbol, _RECORD_FIELD.get(field, field))
    return out


def plugin_of(gamedata_path):
    """'CS2FOW' for gamedata/<VER>/CS2FOW/gamedata/cs2fow.games.txt, else None."""
    parts = os.path.normpath(gamedata_path).split(os.sep)
    for i, part in enumerate(parts[:-2]):
        if part == "gamedata" and re.fullmatch(r"\d+[a-z]?", parts[i + 1]):
            return parts[i + 2]
    return None


def check_keyvalue_entries(entries, index, binaries, module="server", bindings=None):
    """Verify an RVA/index/fingerprint file; returns rows shaped like the rest."""
    bindings = bindings or {}
    rvas = _value_index(index, ("func_rva", "vtable_rva", "gv_rva"))
    idxs = _value_index(index, ("vfunc_index",))
    offs = _value_index(index, ("offset",))
    rows = []
    for name in sorted(entries):
        entry = entries[name]
        row = {"name": name, "kind": entry["kind"], "module": module, "platforms": {}}
        for platform in PLATFORMS:
            value = entry["values"].get(platform)
            if value is None:
                row["platforms"][platform] = {"status": "not-shipped"}
                continue
            if entry["kind"] in ("size", "crc32"):
                blob, _, _ = binaries.get(module, platform)
                if blob is None:
                    row["platforms"][platform] = {"status": "no-binary"}
                    continue
                actual = len(blob) if entry["kind"] == "size" else zlib.crc32(blob)
                # computed from the file itself, so a match IS the confirmation
                row["platforms"][platform] = ({"status": "match", "value": value, "binary": "ok"}
                                              if actual == value else
                                              {"status": "mismatch", "reference": actual, "binary": "mismatch"})
                continue
            if name in bindings:
                lib, symbol, field = bindings[name]
                record = (index.get(fold(symbol)) or {}).get(platform)
                reference = _int(record.get(field)) if record else None
                if reference is None:
                    row["platforms"][platform] = {"status": "no-reference", "resolved": symbol}
                    continue
                info = ({"status": "match", "value": value, "resolved": symbol}
                        if int(reference) == int(value) else
                        {"status": "mismatch", "reference": int(reference), "resolved": symbol})
                if info["status"] == "match":
                    info.update(confirm_record(binaries, dict(record, _module=record.get("_module") or lib),
                                               platform))
                row["platforms"][platform] = info
                continue
            table = {"rva": rvas, "vfunc-index": idxs}.get(entry["kind"], offs)
            names = table.get((value, platform)) or []
            if not names:
                row["platforms"][platform] = {"status": "no-reference"}
            elif len(names) == 1:
                row["platforms"][platform] = {"status": "match", "resolved": names[0]}
            else:
                # Small integers collide: many members share offset 112. Say so rather
                # than picking one and calling it verified.
                row["platforms"][platform] = {"status": "ambiguous-reference",
                                              "count": len(names),
                                              "resolved": ", ".join(sorted(names)[:3])}
        rows.append(row)
    return rows


MIN_LITERAL_BYTES = 4

# CounterStrikeSharp's CModule::IsStubAddress: a hit in one of these ELF sections is a
# linker stub, not code, so the scanner skips it and keeps looking.
STUB_SECTIONS = {".init", ".plt", ".plt.got", ".plt.sec", ".fini", ".got", ".got.plt"}
_STUB_RANGES = {}


def elf_stub_ranges(blob):
    """[(file offset, size)] of the linker-stub sections of an ELF64 image; [] otherwise."""
    cached = _STUB_RANGES.get(id(blob))
    if cached is not None and cached[0] is blob:
        return cached[1]
    ranges = []
    if blob[:4] == b"\x7fELF" and blob[4] == 2:
        shoff = struct.unpack_from("<Q", blob, 0x28)[0]
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", blob, 0x3A)
        if shoff and shnum and shstrndx < shnum and shoff + shnum * shentsize <= len(blob):
            def header(i):
                # sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size
                return struct.unpack_from("<IIQQQQ", blob, shoff + i * shentsize)
            strtab = header(shstrndx)[4]
            for i in range(shnum):
                name_off, _type, _flags, _addr, offset, size = header(i)
                end = blob.find(b"\x00", strtab + name_off)
                name = blob[strtab + name_off:end].decode("latin-1", "replace")
                if name in STUB_SECTIONS and size:
                    ranges.append((offset, size))
    _STUB_RANGES[id(blob)] = (blob, ranges)
    return ranges


def check_signature(binaries, module, platform, pattern, record=None):
    """record: this repo's payload for the same symbol, when we have one."""
    blob, info, _ = binaries.get(module, platform)
    if blob is None:
        return {"status": "no-binary"}
    # A value may name an exported symbol instead of a byte pattern (modsharp writes
    # "@_ZN9CVProfile12OutputReportE..."). That is a different resolution method, not
    # a defect, so it is reported rather than scanned.
    if isinstance(pattern, str) and pattern.startswith("@"):
        return {"status": "symbol-name", "value": pattern[:48]}
    # Parsed the way CounterStrikeSharp's CGameConfig::HexToByte does: every byte exactly
    # two hex digits ("488B" or "4" makes it discard the WHOLE pattern, where V.parse_sig
    # would read a number), and at least MIN_LITERAL_BYTES literal bytes, below which
    # CModule::ScanSignature refuses the pattern rather than resolve its first hit.
    tokens = str(pattern).split()
    if any(tok not in ("?", "??") and len(tok) != 2 for tok in tokens):
        return {"status": "unparsable", "value": str(pattern)[:40]}
    parsed = V.parse_sig(pattern)
    if not parsed:
        return {"status": "unparsable", "value": str(pattern)[:40]}
    literals = sum(b is not None for b in parsed)
    if literals < MIN_LITERAL_BYTES:
        return {"status": "too-few-literals", "literals": literals}
    # Only executable memory is scanned at runtime (CSS walks the module's code segments)
    # and a hit in a linker stub is skipped (STUB_SECTIONS), so neither one resolves the
    # entry nor makes it ambiguous.
    all_hits = V.find_all(blob, parsed)
    stubs = elf_stub_ranges(blob)
    hits = [h for h in all_hits if V.is_exec(info, h)
            and not any(start <= h < start + size for start, size in stubs)]
    if not hits:
        return {"status": "broken", **({"outside_code": len(all_hits)} if all_hits else {})}
    if len(hits) > 1:
        return {"status": "ambiguous", "count": len(hits),
                "at": [hex(V.off_to_va(info, h) or 0) for h in hits[:4]]}
    va = V.off_to_va(info, hits[0])
    if V.is_boundary(blob, info, va):
        return {"status": "ok", "at": hex(va or 0)}
    # A global-variable entry anchors the instruction that REFERENCES the global, so
    # landing mid-function is correct for it rather than a weakness. Resolving where
    # that instruction actually points turns "it resolves" into "it resolves at OUR
    # global" — the same upgrade the RTTI re-read gives an offset.
    if record and record.get("gv_va"):
        out = {"status": "ok-globalref", "at": hex(va or 0)}
        target = _rip_target(blob, info, va)
        if target is not None:
            expected = V._hexint(record.get("gv_va"))
            out["gv"] = "ok" if target == expected else "mismatch"
            if out["gv"] == "mismatch":
                out["points_at"] = hex(target)
                out["expected"] = hex(expected or 0)
        return out
    return {"status": "ok-midfunction", "at": hex(va or 0)}


# A signature entry may carry the vtable slot of its function (the CounterStrikeSharp
# generator writes it for virtual functions):
#   "vtable": {"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152}
# CounterStrikeSharp cross-checks the signature against that slot and, when the file is
# verified for the running build, uses the slot if the signature fails. A wrong slot would
# then hook the wrong function, so the slot must name the signature's function here.
VTABLE_BAD = ("mismatch", "out-of-range", "ambiguous", "unresolved")


_PRIMARY_CACHE = {}


def primary_vtables(blob, info, relocs, class_name):
    """[(vtable_va, slots)] for the class's PRIMARY vtable, found the way CounterStrikeSharp's
    CModule::FindVirtualTable finds it: by the literal RTTI name, and only the table whose
    offset-to-top (ELF) / COL offset (MSVC) is 0. verify_vfunc_slot passes a hit in ANY of a
    multiple-inheritance class's tables and resolves template names by their identifiers, so
    an index it accepts can be one the runtime cannot read or reads as another function.
    Cached per binary and class: one class usually carries several keys.
    """
    key = (id(blob), relocs is None, class_name)
    cached = _PRIMARY_CACHE.get(key)
    if cached is not None and cached[0] is blob:
        return cached[1]
    tables = V.resolve_vtable(blob, info, relocs, class_name, primary_only=True, literal_name=True)
    _PRIMARY_CACHE[key] = (blob, tables)
    return tables


def check_vtable_slot(binaries, module, platform, block, expected_va):
    """Verdict for a "vtable" block on one platform, or None when it ships no index.

    expected_va: where the entry's signature matches (CounterStrikeSharp compares the slot
    with the scanned address itself, head or not), else this repo's func_va.
    """
    if not isinstance(block, dict):
        return None
    index = block.get(f"{platform}_index")
    class_name = block.get("class")
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    if not isinstance(class_name, str) or not class_name or index < 0:
        return "unresolved"
    blob, info, relocs = binaries.get(module, platform)
    if blob is None:
        return "no-binary"
    tables = primary_vtables(blob, info, relocs, class_name)
    if not tables:
        return "unresolved"
    if len(tables) > 1:
        return "ambiguous"
    slots = tables[0][1]
    if index >= len(slots):
        return "out-of-range"
    got = slots[index]
    if got is None:
        return "unresolved"
    if expected_va is None:
        return "unverified"
    # Raw pointer compare, as ApplyVtableFallback does: a slot holding a thunk to the
    # function is a different address to the runtime, which then warns on every load and,
    # as a fallback, would hook the thunk instead of the body.
    if got == expected_va:
        return "ok"
    return "mismatch"


def load_vtable_blocks(path):
    """{entry key: its "vtable" block} for a JSON/JSONC gamedata file; {} otherwise."""
    text = open(path, "r", encoding="utf-8-sig").read()
    for parse in (json.loads, lambda t: json.loads(_strip_jsonc(t))):
        try:
            data = parse(text)
        except Exception:
            continue
        if isinstance(data, dict):
            return {k: v["vtable"] for k, v in data.items()
                    if isinstance(v, dict) and isinstance(v.get("vtable"), dict)}
    return {}


def generator_offset_divisors(modules_dir="gamedata-generators"):
    """
    {symbol: divisor} declared by the generators themselves.

    A plugin may index a struct by element rather than by byte -
    CS2Fixes ships CNetworkGameServer_ClientList as 584/8 = 73 - and its
    generator says so in STRUCT_MEMBER_OFFSET_DIVISOR. Without reading that, this
    tool compares 73 against the analysed 584 and calls a correct file broken,
    which is exactly what it did until now.
    """
    divisors = {}
    if not os.path.isdir(modules_dir):
        return divisors
    pattern = re.compile(r'^\s*"([^"]+)":\s*(\d+)\s*,?\s*$')
    for entry in sorted(os.listdir(modules_dir)):
        path = os.path.join(modules_dir, entry, "gamedata.py")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            inside = False
            for line in handle:
                if line.startswith("STRUCT_MEMBER_OFFSET_DIVISOR"):
                    inside = True
                    continue
                if inside:
                    if line.startswith("}"):
                        break
                    found = pattern.match(line)
                    if found:
                        divisors[found.group(1)] = int(found.group(2))
    return divisors


OFFSET_DIVISORS = None


def generator_key_overrides(plugin, modules_dir="gamedata-generators"):
    """{folded key: symbol} from one generator's KEY_SYMBOL_OVERRIDES.

    A key a plugin means as a different function than the config's alias says (SwiftlyS2's
    CCSPlayer_WeaponServices::DropWeapon is the non-virtual HandleDropWeapon). It is
    per-plugin, so only the generator that owns the file being checked is read.
    """
    path = os.path.join(modules_dir, plugin or "", "gamedata.py")
    if not plugin or not os.path.isfile(path):
        return {}
    text = open(path, encoding="utf-8").read()
    block = re.search(r"^KEY_SYMBOL_OVERRIDES\s*=\s*\{(.*?)^\}", text, re.S | re.M)
    if not block:
        return {}
    return {fold(key): symbol for key, symbol in re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', block.group(1))}


GENERATOR_ALIASES = {}
_SNAPSHOT_INDEX = {}


def load_generator_aliases(config_path):
    """{folded key: symbol} exactly as the generators resolve a key: aliases only, the
    last declaration winning (gamedata_symbol_data.build_alias_to_name_map)."""
    from gamedata_symbol_data import build_alias_to_name_map, load_config
    return {fold(alias): name for alias, name in build_alias_to_name_map(load_config(config_path)).items()}


def resolve_record(index, name, platform, aliases=None):
    """The record a generator wrote `name` from. Its alias target comes FIRST
    (normalize_func_name_colons_to_underscore's order), then the name itself, then the
    looser alias map. Name-first judged the ClientPrint key against the ClientPrint
    record while the generator writes it from ClientPrintToController, whose alias it is
    (CLAUDE.md rule 15)."""
    for candidate in (GENERATOR_ALIASES.get(fold(name)), name, (aliases or {}).get(fold(name))):
        if candidate:
            record = (index.get(fold(candidate)) or {}).get(platform)
            if record is not None:
                return record
    return None


def check_offset(index, binaries, name, platform, value, aliases=None):
    record = resolve_record(index, name, platform, aliases)
    if record is None:
        return {"status": "no-reference"}
    reference = record.get("vfunc_index")
    if reference is None and record.get("offset") is not None:
        reference = V._hexint(record.get("offset"))
    if reference is None:
        return {"status": "no-reference", "reason": "record carries no index or offset"}
    global OFFSET_DIVISORS
    if OFFSET_DIVISORS is None:
        OFFSET_DIVISORS = generator_offset_divisors()
    divisor = OFFSET_DIVISORS.get(name)
    if divisor and int(reference) % divisor == 0 and int(reference) // divisor == int(value):
        return {"status": "match", "value": int(value), "scaled_by": divisor,
                "reference": int(reference)}
    if int(reference) != int(value):
        return {"status": "mismatch", "reference": int(reference)}
    out = {"status": "match", "value": int(value)}
    out.update(confirm_record(binaries, record, platform))
    return out


# -- independent confirmation -----------------------------------------------
# "match" alone only says the plugin file equals what this pipeline produced, which is
# circular: a wrong analysis matches itself. Each method below re-reads the value from
# the binary (or the game's schema) by a route of its own; a key is VERIFIED when at
# least one confirms it and none contradicts it.
CONFIRM_METHODS = ("func", "sig", "rtti", "callsite", "inherit", "insn", "anchor", "xplat", "schema", "gv",
                   "binary", "align", "width", "unique")

# Plain reads/writes/compares of a field: when one of them touches FEWER bytes than the
# field has, it is touching a different, narrower field. Partial updates (or/and/bt...)
# and wider combined copies (movups over two qwords) are left alone.
PLAIN_ACCESS = ("mov", "movzx", "movsx", "movsxd", "cmp", "test")
_MEMBERS = {}


def _members(platform):
    """{(module, struct): {offset: {member,...}}} and {(module, struct, member): size} for
    one platform, over every struct-member record of this build."""
    if platform in _MEMBERS:
        return _MEMBERS[platform]
    by_offset, sizes = {}, {}
    for per_platform in _SNAPSHOT_INDEX.values():
        for plat, record in per_platform.items():
            if not isinstance(record, dict) or not record.get("struct_name") or record.get("offset") is None:
                continue
            key = (record.get("_module") or "server", record["struct_name"])
            if plat == platform:
                by_offset.setdefault(key, {}).setdefault(_int(record["offset"]), set()).add(record.get("member_name"))
            sizes[(plat,) + key + (record.get("member_name"),)] = _int(record.get("size"))
    _MEMBERS[platform] = (by_offset, sizes)
    return _MEMBERS[platform]
# Methods that only re-read a value from the instruction it was taken from. They catch a
# stale or misread value, not a wrong identification (CEntityIdentity::m_designerName
# shipped the neighbouring EHandle's 0x10 from a correctly matching instruction), so a
# value they alone confirm is reported as instruction-only.
INSTRUCTION_ONLY = {"insn", "callsite"}

_FUNC_RANGES = {}


def _identified_functions(binaries, module, platform):
    """[(start, end, symbol)] of this build's function records whose own signature still
    lands on their address - the functions an instruction can be anchored in."""
    key = (module, platform)
    if key in _FUNC_RANGES:
        return _FUNC_RANGES[key]
    blob, info, _ = binaries.get(module, platform)
    out = []
    if blob is not None:
        for name, per_platform in _SNAPSHOT_INDEX.items():
            record = per_platform.get(platform)
            if not isinstance(record, dict) or (record.get("_module") or "server") != module:
                continue
            start, size = _int(record.get("func_va")), _int(record.get("func_size"))
            if not start or not size or not record.get("func_sig"):
                continue
            hits = [V.off_to_va(info, h) for h in _code_hits(blob, info, record["func_sig"])]
            if hits == [start]:
                out.append((start, start + size, record.get("func_name") or name))
    _FUNC_RANGES[key] = out
    return out

_INHERITS = None


def inherit_bases(scripts_dir="ida_preprocessor_scripts"):
    """{target symbol: base vfunc symbol} from every preprocessor's INHERIT_VFUNCS - the
    record a slot-only virtual took its index from."""
    global _INHERITS
    if _INHERITS is not None:
        return _INHERITS
    import ast
    _INHERITS = {}
    if not os.path.isdir(scripts_dir):
        return _INHERITS
    for name in sorted(os.listdir(scripts_dir)):
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(open(os.path.join(scripts_dir, name), encoding="utf-8").read())
        except (OSError, SyntaxError, ValueError):
            continue
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "INHERIT_VFUNCS" for t in node.targets)):
                try:
                    for spec in ast.literal_eval(node.value):
                        _INHERITS.setdefault(fold(spec[0]), spec[2])
                except (ValueError, IndexError, TypeError):
                    pass
    return _INHERITS


def _int(value):
    return V._hexint(value) if isinstance(value, str) else value


def _code_hits(blob, info, sig):
    pattern = V.parse_sig(sig)
    if not pattern:
        return []
    return [h for h in V.find_all(blob, pattern) if V.is_exec(info, h)]


def confirm_record(binaries, record, platform):
    """{method: 'ok' | 'mismatch' | 'ambiguous'} for what a snapshot record can prove
    from the binary on its own. Methods that do not apply are left out."""
    out = {}
    if not record:
        return out
    module = record.get("_module") or "server"
    blob, info, relocs = binaries.get(module, platform)
    if blob is None:
        return out

    func_va = _int(record.get("func_va"))
    # sig: the record's own function signature lands exactly on its address.
    if record.get("func_sig") and func_va is not None:
        hits = [V.off_to_va(info, h) for h in _code_hits(blob, info, record["func_sig"])]
        if func_va in hits:
            out["sig"] = "ok" if len(hits) == 1 else "ambiguous"
        elif hits:
            out["sig"] = "mismatch"

    # rtti: a virtual sits in that slot of the class's primary vtable (thunks followed -
    # calling a thunk reaches the function).
    index = record.get("vfunc_index")
    if record.get("vtable_name") and func_va is not None and index is not None:
        verdict = V.verify_vfunc_slot(blob, info, relocs, record["vtable_name"], int(index),
                                      func_va, primary_only=True)
        if verdict:
            out["rtti"] = verdict
        if verdict == "mismatch":
            # where the function really sits, for auto_repair: its slot in the primary vtable
            tables = primary_vtables(blob, info, relocs, record["vtable_name"])
            if len(tables) == 1:
                slots = [i for i, got in enumerate(tables[0][1])
                         if got == func_va or (got is not None and V._thunk_target(blob, info, got) == func_va)]
                if len(slots) == 1:
                    out["slot_found"] = slots[0]
                    # independent evidence for that slot: the function's own signature lands
                    # on it, or a call site of this virtual uses exactly that slot's offset
                    if record.get("func_sig"):
                        hits = [V.off_to_va(info, h) for h in _code_hits(blob, info, record["func_sig"])]
                        if hits == [func_va]:
                            out["slot_evidence"] = "sig"
                    if "slot_evidence" not in out and record.get("vfunc_sig"):
                        if V.vfunc_sig_calls_offset(blob, info, record["vfunc_sig"], 8 * slots[0],
                                                    record.get("vfunc_sig_disp")) == "ok":
                            out["slot_evidence"] = "callsite"
            out["vrecord"] = {"module": module, "class": record["vtable_name"], "func_va": func_va,
                              "index": int(index), "symbol": record.get("_symbol")}

    # callsite: a slot-only record's index is the displacement of the call it came from.
    if record.get("vfunc_sig") and func_va is None and index is not None:
        verdict = V.vfunc_sig_calls_offset(blob, info, record["vfunc_sig"], 8 * int(index),
                                           record.get("vfunc_sig_disp"))
        if verdict:
            out["callsite"] = verdict

    # inherit: a slot-only virtual (an empty stub with no address of its own) took its
    # index from a base virtual that has one, so the base class's primary vtable must
    # hold that function at the same slot, and the record's own class must reach it.
    if func_va is None and index is not None and record.get("vtable_name") and record.get("func_name"):
        base_name = inherit_bases().get(fold(record["func_name"]))
        base = (_SNAPSHOT_INDEX.get(fold(base_name)) or {}).get(platform) if base_name else None
        base_va = _int(base.get("func_va")) if base else None
        if base and base_va is not None and base.get("vtable_name") and _int(base.get("vfunc_index")) == int(index):
            own = V.resolve_vtable(blob, info, relocs, record["vtable_name"], primary_only=True)
            if own and int(index) >= len(own[0][1]):
                out["inherit"] = "mismatch"
            else:
                verdict = V.verify_vfunc_slot(blob, info, relocs, base["vtable_name"], int(index),
                                              base_va, primary_only=True)
                if verdict:
                    out["inherit"] = verdict

    # insn: a struct offset is read back out of the instruction it was taken from.
    offset = _int(record.get("offset"))
    if record.get("offset_sig") and offset is not None:
        try:
            max_match = max(1, int(record.get("offset_sig_max_match") or 1))
        except (TypeError, ValueError):
            max_match = 1
        verdict = V.sig_holds_value(blob, info, record["offset_sig"], offset,
                                    record.get("offset_sig_disp"), allow_imm=True, max_match=max_match)
        if verdict:
            out["insn"] = verdict
        # anchor: that instruction sits inside a function this repo has identified on its
        # own (strings, callers, vtable - and its signature still lands on it), so the
        # value is tied to a known function, not to any instruction that happens to match.
        if verdict == "ok":
            hits = _code_hits(blob, info, record["offset_sig"])
            if len(hits) == 1:
                at = V.off_to_va(info, hits[0])
                owner = next((n for a, b, n in _identified_functions(binaries, module, platform) if a <= at < b), None)
                if owner:
                    out["anchor"] = "ok"
                    out["anchored_in"] = owner

    size = _int(record.get("size"))
    # align: a 2/4/8-byte scalar sits on a multiple of its size - unless the compiler itself
    # addresses it there (CServerSideClient is packed: both builds store a qword at 0xb3),
    # so it only speaks when the instruction does not confirm the value. Contradicts only.
    if offset is not None and size in (2, 4, 8) and offset % size and out.get("insn") != "ok":
        out["align"] = "mismatch"

    struct, member = record.get("struct_name"), record.get("member_name")
    if struct and member and offset is not None:
        out["record"] = {"module": module, "struct": struct, "member": member, "offset": offset,
                         "size": size, "symbol": record.get("_symbol"), "offset_sig": record.get("offset_sig")}
        by_offset, sizes = _members(platform)
        # unique: two members of one struct cannot share an offset. linux
        # CServerSideClient shipped m_NetChannel AND m_SteamID at 0xa0 for 14182-14190.
        others = by_offset.get((module, struct), {}).get(offset, set()) - {member}
        if others and size:
            out["unique"] = "mismatch"
            out["shares_offset_with"] = ", ".join(sorted(map(str, others)))
        # width: the instruction the value was read from must touch the whole field. Only
        # when both platforms agree on the field's size (that metadata is not always right:
        # BotProfile::m_difficultyFlags is 1 byte on linux and 4 on windows) and it is not
        # an array element access.
        other_platform = "windows" if platform == "linux" else "linux"
        other_size = sizes.get((other_platform, module, struct, member))
        if record.get("offset_sig") and size in (1, 2, 4, 8) and other_size == size:
            access = V.value_access(blob, info, record["offset_sig"], offset, record.get("offset_sig_disp"))
            if access and access[0] in PLAIN_ACCESS and not access[2] and access[1] < size:
                out["width"] = "mismatch"
                out["accessed_bytes"] = access[1]

    # schema: the game's own schema places the member at that offset.
    if record.get("struct_name") and record.get("member_name") and offset is not None:
        classes = binaries.schema(module, platform)
        if classes:
            import schema_dump
            hit = schema_dump.field_offset(classes, str(record["struct_name"]), str(record["member_name"]))
            if hit is not None:  # (owning class, absolute offset)
                out["schema"] = "ok" if hit[1] == offset else "mismatch"

    # gv: the global's signature still addresses that global.
    gv_va = _int(record.get("gv_va"))
    if record.get("gv_sig") and gv_va is not None:
        hits = _code_hits(blob, info, record["gv_sig"])
        if len(hits) == 1:
            inst = V.off_to_va(info, hits[0]) + int(_int(record.get("gv_inst_offset")) or 0)
            target = _rip_target(blob, info, inst)
            if target is not None:
                out["gv"] = "ok" if target == gv_va else "mismatch"
        elif hits:
            out["gv"] = "ambiguous"

    # rtti for a vtable record: the class's primary vtable is at that address.
    vtable_va = _int(record.get("vtable_va"))
    if record.get("vtable_class") and vtable_va is not None:
        tables = V.resolve_vtable(blob, info, relocs, record["vtable_class"], primary_only=True)
        if tables:
            out["rtti"] = "ok" if any(va == vtable_va for va, _slots in tables) else "mismatch"
    return out


PASSING = ("ok", "ok-globalref", "match")


def cross_platform(row):
    """xplat: two compilers, one value. When linux and windows each re-read the same
    offset from an instruction of their own, both builds agree on the layout - and the
    one known misidentification (linux m_designerName 0x10 against windows 0x20) is the
    case where they do not. Platforms that legitimately differ just get no xplat."""
    linux, windows = row["platforms"].get("linux") or {}, row["platforms"].get("windows") or {}
    if linux.get("status") != "match" or windows.get("status") != "match":
        return
    if linux.get("insn") != "ok" or windows.get("insn") != "ok":
        return
    if linux.get("value") is not None and linux.get("value") == windows.get("value"):
        linux["xplat"] = windows["xplat"] = "ok"


def _field_accesses(blob, info, start, end, size):
    """{displacement: first VA} of plain, non-indexed memory accesses `size` bytes wide
    in [start, end)."""
    import capstone
    out = {}
    off = V.va_to_off(info, start)
    if off is None or V._MD is None:
        return out
    for ins in V._MD.disasm(blob[off:off + (end - start)], start):
        if ins.mnemonic not in PLAIN_ACCESS:
            continue
        for op in ins.operands:
            if (op.type == capstone.x86.X86_OP_MEM and op.mem.index == 0 and op.size == size
                    and op.mem.base not in (capstone.x86.X86_REG_RIP, capstone.x86.X86_REG_RSP)
                    and op.mem.disp > 0):
                out.setdefault(op.mem.disp, ins.address)
    return out


def anchor_disagreement(row, binaries):
    """xplat=mismatch with evidence: one platform's value sits in an identified function F,
    the other platform disagrees and has no anchor or schema of its own, and F on the other
    platform accesses the anchored platform's value at the field's width - but not its own.
    windows CServerSideClient::m_bFakePlayer shipped 0x9f8 (a getter of another field)
    while CServerSideClientBase_Connect stores the flag at 0xa0 on BOTH platforms. A layout
    that really differs (smoke 3008 / 3736) uses its own value in F and is left alone."""
    cells = row["platforms"]
    for anchored, other in (("linux", "windows"), ("windows", "linux")):
        a, b = cells.get(anchored) or {}, cells.get(other) or {}
        ra, rb = a.get("record"), b.get("record")
        if not ra or not rb or a.get("anchor") != "ok" or not a.get("anchored_in"):
            continue
        if b.get("anchor") == "ok" or b.get("schema") == "ok" or ra["offset"] == rb["offset"]:
            continue
        size = rb.get("size") or ra.get("size")
        if size not in (1, 2, 4, 8):
            continue
        blob, info, _ = binaries.get(rb["module"], other)
        if blob is None:
            continue
        span = next(((x, y) for x, y, n in _identified_functions(binaries, rb["module"], other)
                     if n == a["anchored_in"]), None)
        if not span:
            continue
        seen = _field_accesses(blob, info, span[0], span[1], size)
        if ra["offset"] in seen and rb["offset"] not in seen:
            b["xplat"] = "mismatch"
            b["expected"] = ra["offset"]
            b["evidence_at"] = hex(seen[ra["offset"]])
            b["evidence_in"] = a["anchored_in"]


def verification(info):
    """'verified' | 'contradicted' | 'unverified' | None (nothing shipped to judge)."""
    status = info.get("status")
    if status in ("not-shipped", "no-binary", "symbol-name"):
        return None
    if (status in ("broken", "ambiguous", "mismatch", "unparsable", "too-few-literals")
            or any(info.get(m) == "mismatch" for m in CONFIRM_METHODS)
            or info.get("vtable") in VTABLE_BAD):
        return "contradicted"
    if status in PASSING and any(info.get(m) == "ok" for m in CONFIRM_METHODS):
        return "verified"
    # mid-function is expected of a patch site, and func=ok there means it landed on the
    # exact instruction the patch record names
    if status == "ok-midfunction" and info.get("func") == "ok":
        return "verified"
    # A key this repo has no record for at all: the plugin author's value, shipped as the
    # plugin publishes it (sync_plugin_templates). Not verified by us - reported, but not a
    # gate failure, since leaving it out would break the plugin feature that reads it.
    if info.get("unrecorded") and status in ("ok", "ok-midfunction", "ok-globalref", "no-reference"):
        return "upstream"
    return "unverified"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-gamedata", required=True,
                        help="the plugin's gamedata file (JSON, JSONC or KeyValues)")
    parser.add_argument("-snapshot", default=None, help="default: gamesymbols/<gamever>.yaml")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-configyaml", default=None,
                        help="default: configs/<gamever>.yaml; supplies the alias map")
    parser.add_argument("-json", action="store_true")
    parser.add_argument("-quiet", action="store_true", help="only print what is not ok")
    parser.add_argument("-require-verified", dest="require_verified", action="store_true",
                        help="also fail on any shipped entry no method could confirm from the binary")
    parser.add_argument("-platform", default="linux,windows",
                        help="only judge these platforms (autopilot's linux-first release checks "
                             "linux alone while the windows values are still the previous build's)")
    args = parser.parse_args()
    global PLATFORMS
    PLATFORMS = tuple(p for p in ("linux", "windows") if p in args.platform.split(","))

    snapshot = args.snapshot or os.path.join("gamesymbols", f"{args.gamever}.yaml")
    index = load_snapshot_index(snapshot)
    _SNAPSHOT_INDEX.update(index)
    binaries = Binaries(args.bindir, args.gamever)
    gamedata, note = load_gamedata(args.gamedata)
    if note and "key=value" in note:
        text = open(args.gamedata, "r", encoding="utf-8-sig").read()
        kv_entries = parse_keyvalue_file(text)
        if kv_entries:
            results = check_keyvalue_entries(kv_entries, index, binaries,
                                             bindings=generator_keyvalue_bindings(plugin_of(args.gamedata)))
            for row in results:
                anchor_disagreement(row, binaries)
            return _report(results, args, os.path.basename(args.gamedata))
    if note:
        print(f"{os.path.basename(args.gamedata)}: {note}")
        return 2
    config_path = args.configyaml or os.path.join("configs", f"{args.gamever}.yaml")
    aliases = load_alias_map(config_path) if os.path.isfile(config_path) else {}
    if os.path.isfile(config_path):
        GENERATOR_ALIASES.update(load_generator_aliases(config_path))
    GENERATOR_ALIASES.update(generator_key_overrides(plugin_of(args.gamedata)))

    vtable_blocks = load_vtable_blocks(args.gamedata)

    results = []
    for name in sorted(gamedata):
        entry = gamedata[name]
        kind, values = entry["kind"], entry["values"]
        module = LIBRARY_TO_MODULE.get(str(entry.get("library") or "server"), "server")
        row = {"name": name, "kind": kind, "module": module, "platforms": {}}
        for platform in PLATFORMS:
            value = values.get(platform)
            if value in (None, ""):
                row["platforms"][platform] = {"status": "not-shipped"}
                continue
            if kind == "offset":
                row["platforms"][platform] = check_offset(index, binaries, name, platform,
                                                          value, aliases)
                # A record that carries no index or offset says nothing about this value either:
                # stock CounterStrikeSharp's GameEventManager (93, read by no code) folds onto one.
                if (resolve_record(index, name, platform, aliases) is None
                        or row["platforms"][platform].get("reason") == "record carries no index or offset"):
                    row["platforms"][platform]["unrecorded"] = True
                continue
            if kind == "patch":
                # A patch value is what the plugin WRITES, not where it writes
                # it, so its bytes are not expected to appear in the binary.
                # Scanning for them says nothing either way - reporting that
                # honestly beats calling a working patch broken.
                row["platforms"][platform] = {"status": "patch-unverifiable"}
                continue
            record = resolve_record(index, name, platform, aliases)
            info = check_signature(binaries, module, platform, value, record)
            if record is None:
                info["unrecorded"] = True
            if record and info.get("status") == "ok" and record.get("func_va"):
                # func: the plugin's pattern lands on the function this repo identified
                info["func"] = "ok" if V._hexint(info["at"]) == _int(record["func_va"]) else "mismatch"
            elif record and info.get("status") in ("ok", "ok-midfunction") and record.get("patch_va"):
                # a plugin may scan for a patch site as a plain signature (SwiftlyS2's
                # SetSchemaHammerUniqueId): it must land on the patch this repo recorded
                info["func"] = "ok" if V._hexint(info["at"]) == _int(record["patch_va"]) else "mismatch"
            if record and info.get("status") in PASSING:
                for method, verdict in confirm_record(binaries, record, platform).items():
                    info.setdefault(method, verdict)
            if name in vtable_blocks:
                expected = (V._hexint(info["at"]) if info.get("status") in ("ok", "ok-midfunction")
                            else None)
                if expected is None and record and record.get("func_va"):
                    expected = V._hexint(record.get("func_va"))
                verdict = check_vtable_slot(binaries, module, platform, vtable_blocks[name], expected)
                if verdict:
                    info["vtable"] = verdict
            row["platforms"][platform] = info
        anchor_disagreement(row, binaries)
        results.append(row)

    return _report(results, args, os.path.basename(args.gamedata))


def _report(results, args, filename):
    """Shared rendering for both the symbol-keyed and the key=value paths."""
    bad = 0
    tally = {"verified": 0, "unverified": 0, "contradicted": 0, "upstream": 0}
    unverified, upstream = [], []
    for row in results:
        cross_platform(row)
    for row in results:
        for platform, info in row["platforms"].items():
            state = verification(info)
            if state:
                info["verification"] = state
                tally[state] += 1
            if state == "unverified":
                unverified.append(f"{row['name']}.{platform}")
            if state == "upstream":
                upstream.append(f"{row['name']}.{platform}")
            if state == "verified" and {m for m in CONFIRM_METHODS if info.get(m) == "ok"} <= INSTRUCTION_ONLY:
                info["instruction_only"] = True
                tally["instruction_only"] = tally.get("instruction_only", 0) + 1
            if (info["status"] in ("broken", "ambiguous", "mismatch", "unparsable", "too-few-literals")
                    or state == "contradicted"
                    or (state == "unverified" and getattr(args, "require_verified", False))):
                bad += 1

    if args.json:
        print(json.dumps({"gamever": args.gamever, "gamedata": args.gamedata,
                          "results": results, "unhealthy": bad, "verification": tally}, indent=1))
        return 1 if bad else 0

    counts = {}
    for row in results:
        for info in row["platforms"].values():
            key = info["status"] if info.get("rtti") != "mismatch" else "rtti-mismatch"
            counts[key] = counts.get(key, 0) + 1
        statuses = [i["status"] for i in row["platforms"].values()]
        if args.quiet and all(st in ("ok", "ok-globalref", "match", "not-shipped",
                                     "symbol-name") for st in statuses) \
                and not any(i.get("vtable") in VTABLE_BAD for i in row["platforms"].values()):
            continue
        cells = []
        for platform in PLATFORMS:
            info = row["platforms"].get(platform, {"status": "-"})
            cell = info["status"]
            if info.get("count"):
                cell += f"({info['count']})"
            if info.get("reference") is not None:
                cell += f" ref={info['reference']}"
            if info.get("resolved"):
                cell += f" as {info['resolved']}"
            for method in CONFIRM_METHODS:
                if info.get(method):
                    cell += f" {method}={info[method]}"
            if info.get("vtable"):
                cell += f" vtable={info['vtable']}"
            if info.get("points_at"):
                cell += f" points_at={info['points_at']} expected={info.get('expected')}"
            cells.append(f"{platform} {cell}")
        print(f"  {row['name']:46} {row['kind']:12} {' | '.join(cells)}")

    print()
    # match, ok, ok-globalref and symbol-name are all passes; they are named apart
    # only to say WHY they pass.
    print(f"{len(results)} entries in {filename}: "
          + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    print(f"verified: {tally['verified']} ({tally.get('instruction_only', 0)} by instruction only), "
          f"unverified: {tally['unverified']}, contradicted: {tally['contradicted']}, upstream: {tally['upstream']}")
    if unverified and not args.quiet:
        print("  unverified: " + ", ".join(unverified[:40]) + (" ..." if len(unverified) > 40 else ""))
    if upstream:
        print(f"upstream (the plugin author's value, no record here): {', '.join(upstream[:40])}")
    print(f"unhealthy: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
