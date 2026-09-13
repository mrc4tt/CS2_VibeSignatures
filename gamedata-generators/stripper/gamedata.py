#!/usr/bin/env python3
"""
StripperCS2 Gamedata Update Module (bot-hider pattern)

StripperCS2 does NOT read a gamedata file: both signatures are string literals in
`src/hook.cpp`, chosen by `#ifdef WIN32` and resolved with
`KHook::LookupSignature`. The file this generator emits is therefore a *reference*,
not a drop-in - a server owner cannot copy it into the plugin, they have to paste
the value into `hook.cpp` and rebuild.

It is still worth generating, for two reasons a symbol on its own does not give:
the value is published with every build, so `sig.miksen.me` shows when it last
moved, and "Check my file" can tell someone whether the signature their build
carries is the current one. That is the whole problem being solved here - the
linux literal in the plugin's own source was stale for 14181 and the plugin would
simply have failed to hook.

The signature format matches what `KHook::LookupSignature` parses: space-separated
hex bytes with a single `?` per wildcard, which is exactly `convert_sig_to_css`.
"""

import json
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, normalize_func_name_colons_to_underscore

# Upstream source of the two literals (not a gamedata file - read them off the
# #ifdef in the hook):
#   https://github.com/Source2ZE/StripperCS2/blob/master/src/hook.cpp
MODULE_NAME = "stripper"
MODULE_ENABLED = True

GAMEDATA_PATH = "gamedata/stripper.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)
STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Refresh every signature in stripper.json from the snapshot.

    Merge semantics, same as the other seeded generators: the keys already in the
    file are refreshed in place and never renamed, added or dropped, so a key the
    snapshot cannot satisfy keeps its previous value rather than disappearing.

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    gamedata_path = os.path.join(output_dir, GAMEDATA_PATH)

    if not os.path.exists(gamedata_path):
        print(f"  Warning: StripperCS2 gamedata not found: {gamedata_path}")
        return 0, 0, [], []

    with open(gamedata_path, "r", encoding="utf-8") as f:
        gamedata = json.load(f)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    for func_name, entry in gamedata.items():
        # :: to _ only for matching with YAML data - never for the output key
        yaml_func_name = normalize_func_name_colons_to_underscore(func_name, alias_to_name_map)

        library = None
        if "signatures" in entry and "library" in entry["signatures"]:
            library = entry["signatures"]["library"]
        elif yaml_func_name in func_lib_map:
            library = func_lib_map[yaml_func_name]

        if not library:
            print(f"  Warning: Unknown library for {func_name}, skipping")
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "unknown library"})
            continue

        yaml_entry = yaml_data.get(yaml_func_name)
        if not yaml_entry or yaml_entry.get("library") != library:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "no matching YAML data"})
            continue

        if "signatures" in entry:
            for platform in platforms:
                if platform in yaml_entry and "func_sig" in yaml_entry[platform]:
                    entry["signatures"][platform] = convert_sig_to_css(yaml_entry[platform]["func_sig"])
                    updated_count += 1
                    if debug:
                        updated_symbols.append({"name": func_name, "type": "signature", "platform": platform})

    with open(gamedata_path, "w", encoding="utf-8") as f:
        json.dump(gamedata, f, indent=2)
        f.write("\n")

    return updated_count, skipped_count, updated_symbols, skipped_symbols
