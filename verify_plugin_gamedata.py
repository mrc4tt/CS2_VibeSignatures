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
    """{folded symbol name: {platform: payload}} from a packed snapshot."""
    import yaml
    with open(path, "r", encoding="utf-8") as handle:
        files = yaml.safe_load(handle).get("files") or {}
    index = {}
    for artifact_path, payload in files.items():
        base = artifact_path.split("/")[-1]
        for platform in PLATFORMS:
            suffix = f".{platform}.yaml"
            if base.endswith(suffix):
                index.setdefault(fold(base[: -len(suffix)]), {})[platform] = payload
    return index


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


def check_signature(binaries, module, platform, pattern, record=None):
    """record: this repo's payload for the same symbol, when we have one."""
    blob, info, _ = binaries.get(module, platform)
    if blob is None:
        return {"status": "no-binary"}
    hits = V.find_all(blob, V.parse_sig(pattern))
    if not hits:
        return {"status": "broken"}
    if len(hits) > 1:
        return {"status": "ambiguous", "count": len(hits),
                "at": [hex(V.off_to_va(info, h) or 0) for h in hits[:4]]}
    va = V.off_to_va(info, hits[0])
    if V.is_boundary(blob, info, va):
        return {"status": "ok", "at": hex(va or 0)}
    # A global-variable entry anchors the instruction that REFERENCES the global, so
    # landing mid-function is correct for it rather than a weakness.
    if record and record.get("gv_va"):
        return {"status": "ok-globalref", "at": hex(va or 0)}
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
        module_hint = record.get("_module") or module_of(index, name) or "server"
        blob, info, relocs = binaries.get(module_hint, platform)
        if blob is not None:
            verdict = V.verify_vfunc_slot(blob, info, relocs, vtable_class,
                                          int(record["vfunc_index"]), V._hexint(func_va))
            out["rtti"] = verdict or "unresolved"
    return out


def module_of(index, name):
    return None  # the snapshot index is keyed by symbol, not module; server is the default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-gamedata", required=True, help="the plugin's gamedata.json")
    parser.add_argument("-snapshot", default=None, help="default: gamesymbols/<gamever>.yaml")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-configyaml", default=None,
                        help="default: configs/<gamever>.yaml; supplies the alias map")
    parser.add_argument("-json", action="store_true")
    parser.add_argument("-quiet", action="store_true", help="only print what is not ok")
    args = parser.parse_args()

    snapshot = args.snapshot or os.path.join("gamesymbols", f"{args.gamever}.yaml")
    with open(args.gamedata, "r", encoding="utf-8") as handle:
        gamedata = json.load(handle)
    index = load_snapshot_index(snapshot)
    config_path = args.configyaml or os.path.join("configs", f"{args.gamever}.yaml")
    aliases = load_alias_map(config_path) if os.path.isfile(config_path) else {}
    binaries = Binaries(args.bindir, args.gamever)

    results, bad = [], 0
    for name in sorted(gamedata):
        entry = gamedata[name] or {}
        if "signatures" in entry:
            block = entry["signatures"]
            module = LIBRARY_TO_MODULE.get(str(block.get("library", "server")), "server")
            row = {"name": name, "kind": "signature", "module": module, "platforms": {}}
            for platform in PLATFORMS:
                pattern = block.get(platform)
                if not pattern:
                    row["platforms"][platform] = {"status": "not-shipped"}
                    continue
                record = (index.get(fold(name)) or {}).get(platform)
                if record is None and aliases.get(fold(name)):
                    record = (index.get(fold(aliases[fold(name)])) or {}).get(platform)
                row["platforms"][platform] = check_signature(binaries, module, platform,
                                                             pattern, record)
        elif "offsets" in entry:
            row = {"name": name, "kind": "offset", "platforms": {}}
            for platform in PLATFORMS:
                value = (entry["offsets"] or {}).get(platform)
                if value is None:
                    row["platforms"][platform] = {"status": "not-shipped"}
                    continue
                row["platforms"][platform] = check_offset(index, binaries, name, platform,
                                                          value, aliases)
        else:
            row = {"name": name, "kind": "other", "platforms": {}}
        results.append(row)
        for info in row["platforms"].values():
            if info["status"] in ("broken", "ambiguous", "mismatch") or info.get("rtti") == "mismatch":
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
            cells.append(f"{platform} {cell}")
        print(f"  {row['name']:52} {row['kind']:9} {' | '.join(cells)}")

    print()
    print(f"{len(results)} entries in {os.path.basename(args.gamedata)}: "
          + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    print(f"unhealthy: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
