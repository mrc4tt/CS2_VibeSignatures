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

Exit code is non-zero when anything is broken or ambiguous, so it can gate a deploy.

  uv run verify_plugin_gamedata.py -gamever 14181 \
      -gamedata gamedata/14181/CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json
"""

import argparse
import json
import os
import re
import sys

import validate_artifacts as V

# CSS spells the library the way the module is named here; a few plugins use the
# binary's own name instead, so both spellings map to one module.
LIBRARY_TO_MODULE = {
    "server": "server", "engine": "engine", "engine2": "engine",
    "client": "client", "networksystem": "networksystem",
    "scenesystem": "scenesystem", "matchmaking": "matchmaking",
    "vphysics2": "vphysics2", "sdl3": "SDL3", "SDL3": "SDL3",
}

BIN_LINUX = {"server": "libserver.so", "engine": "libengine2.so", "client": "libclient.so",
             "networksystem": "libnetworksystem.so", "scenesystem": "libscenesystem.so",
             "matchmaking": "libmatchmaking.so", "vphysics2": "libvphysics2.so",
             "SDL3": "libSDL3.so.0"}
BIN_WIN = {"server": "server.dll", "engine": "engine2.dll", "client": "client.dll",
           "networksystem": "networksystem.dll", "scenesystem": "scenesystem.dll",
           "matchmaking": "matchmaking.dll", "vphysics2": "vphysics2.dll",
           "SDL3": "SDL3.dll"}

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
                    payload = dict(payload, _module=module)
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
        name, hint = "?", None
        for key in reversed(path):
            lowered = str(key).lower()
            if lowered in KIND_WORDS:
                hint = hint or lowered
                continue
            name = key
            break
        sample = next(iter(platform_values.values()))
        kind = "offset" if isinstance(sample, (int, float)) and not isinstance(sample, bool) else "signature"
        if kind == "signature" and isinstance(sample, str) and re.fullmatch(r"\s*\d+\s*", sample):
            kind = "offset"
        if hint and "patch" in hint:
            kind = "patch"
        elif hint and "sig" in hint:
            kind = "signature" if kind == "signature" else kind
        yield name, {"kind": kind,
                     "library": node.get("library") or node.get("Library"),
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
        self.root = os.path.join(bindir, gamever)
        self.cache = {}

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
    parsed = V.parse_sig(pattern)
    if not parsed:
        return {"status": "unparsable", "value": str(pattern)[:40]}
    hits = V.find_all(blob, parsed)
    if not hits:
        return {"status": "broken"}
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


def check_offset(index, binaries, name, platform, value, aliases=None):
    record = (index.get(fold(name)) or {}).get(platform)
    if record is None and aliases:
        canonical = aliases.get(fold(name))
        if canonical:
            record = (index.get(fold(canonical)) or {}).get(platform)
    if record is None:
        return {"status": "no-reference"}
    reference = record.get("vfunc_index")
    if reference is None and record.get("offset") is not None:
        reference = V._hexint(record.get("offset"))
    if reference is None:
        return {"status": "no-reference", "reason": "record carries no index or offset"}
    if int(reference) != int(value):
        return {"status": "mismatch", "reference": int(reference)}
    out = {"status": "match", "value": int(value)}
    # A vtable-backed record can be re-read straight out of the binary.
    vtable_class, func_va = record.get("vtable_name"), record.get("func_va")
    if vtable_class and func_va and record.get("vfunc_index") is not None:
        module_hint = record.get("_module") or "server"
        blob, info, relocs = binaries.get(module_hint, platform)
        if blob is not None:
            verdict = V.verify_vfunc_slot(blob, info, relocs, vtable_class,
                                          int(record["vfunc_index"]), V._hexint(func_va))
            out["rtti"] = verdict or "unresolved"
    return out


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
    args = parser.parse_args()

    snapshot = args.snapshot or os.path.join("gamesymbols", f"{args.gamever}.yaml")
    gamedata, note = load_gamedata(args.gamedata)
    if note:
        print(f"{os.path.basename(args.gamedata)}: {note}")
        return 2
    index = load_snapshot_index(snapshot)
    config_path = args.configyaml or os.path.join("configs", f"{args.gamever}.yaml")
    aliases = load_alias_map(config_path) if os.path.isfile(config_path) else {}
    binaries = Binaries(args.bindir, args.gamever)

    results, bad = [], 0
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
                continue
            # signature and patch are both byte patterns to scan for
            record = (index.get(fold(name)) or {}).get(platform)
            if record is None and aliases.get(fold(name)):
                record = (index.get(fold(aliases[fold(name)])) or {}).get(platform)
            row["platforms"][platform] = check_signature(binaries, module, platform,
                                                         value, record)
        results.append(row)
        for info in row["platforms"].values():
            if (info["status"] in ("broken", "ambiguous", "mismatch", "unparsable")
                    or info.get("rtti") == "mismatch" or info.get("gv") == "mismatch"):
                bad += 1

    if args.json:
        print(json.dumps({"gamever": args.gamever, "gamedata": args.gamedata,
                          "results": results, "unhealthy": bad}, indent=1))
        return 1 if bad else 0

    counts = {}
    for row in results:
        for platform, info in row["platforms"].items():
            key = info["status"] if info.get("rtti") != "mismatch" else "rtti-mismatch"
            counts[key] = counts.get(key, 0) + 1
        interesting = [i["status"] for i in row["platforms"].values()]
        if args.quiet and all(s in ("ok", "match", "not-shipped") for s in interesting):
            continue
        cells = []
        for platform in PLATFORMS:
            info = row["platforms"].get(platform, {"status": "-"})
            cell = info["status"]
            if info.get("count"):
                cell += f"({info['count']})"
            if info.get("reference") is not None:
                cell += f" ref={info['reference']}"
            if info.get("rtti"):
                cell += f" rtti={info['rtti']}"
            if info.get("gv"):
                cell += f" gv={info['gv']}"
            if info.get("points_at"):
                cell += f" points_at={info['points_at']} expected={info.get('expected')}"
            cells.append(f"{platform} {cell}")
        print(f"  {row['name']:52} {row['kind']:9} {' | '.join(cells)}")

    print()
    # ok-globalref and match are passes; they are named apart only to say WHY they pass.
    print(f"{len(results)} entries in {os.path.basename(args.gamedata)}: "
          + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    print(f"unhealthy: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
