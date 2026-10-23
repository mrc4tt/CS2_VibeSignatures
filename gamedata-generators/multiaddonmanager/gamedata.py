#!/usr/bin/env python3
"""
MultiAddonManager Gamedata Update Module (stripper pattern)

MultiAddonManager does NOT read a gamedata file: its three signatures and two
offsets are `constexpr` literals in `src/multiaddonmanager.cpp`, chosen by
`#ifdef PLATFORM_WINDOWS` and resolved with `CModule::LookupSignature`. The file
this generator emits is therefore a *reference*, not a drop-in - the values have
to be pasted into the source and the plugin rebuilt.

Worth generating anyway, for the same reason as stripper: the values are published
with every build, so the site shows when one moved. The linux ReplyConnection
literal in the plugin ("55 B9 ? ? ? ? 41 B8") already matched twice on 14192.

Signatures use one `?` per wildcard, the form the plugin's literals use
(`convert_sig_to_css`). Offsets are byte offsets into CNetworkGameServer.
"""

import json
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, normalize_func_name_colons_to_underscore

# Plugin: https://github.com/mrc4tt/MultiAddonManager - no "Seed source:" line, the
# values are C++ literals in src/multiaddonmanager.cpp, not a gamedata file.
MODULE_NAME = "multiaddonmanager"
MODULE_ENABLED = True

GAMEDATA_PATH = "gamedata/multiaddonmanager.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)
STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Refresh every signature and offset in multiaddonmanager.json from the snapshot.

    Merge semantics, same as the other seeded generators: the keys already in the
    file are refreshed in place and never renamed, added or dropped, so a key the
    snapshot cannot satisfy keeps its previous value rather than disappearing.

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    gamedata_path = os.path.join(output_dir, GAMEDATA_PATH)

    if not os.path.exists(gamedata_path):
        print(f"  Warning: MultiAddonManager gamedata not found: {gamedata_path}")
        return 0, 0, [], []

    with open(gamedata_path, "r", encoding="utf-8") as f:
        gamedata = json.load(f)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    for key, entry in gamedata.items():
        # :: to _ only for matching with YAML data - never for the output key
        yaml_name = normalize_func_name_colons_to_underscore(key, alias_to_name_map)
        section = entry.get("signatures") or entry.get("offsets") or {}
        library = section.get("library") or func_lib_map.get(yaml_name)

        if not library:
            print(f"  Warning: Unknown library for {key}, skipping")
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": key, "reason": "unknown library"})
            continue

        yaml_entry = yaml_data.get(yaml_name)
        if not yaml_entry or yaml_entry.get("library") != library:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": key, "reason": "no matching YAML data"})
            continue

        for platform in platforms:
            record = yaml_entry.get(platform) or {}
            if "signatures" in entry and "func_sig" in record:
                entry["signatures"][platform] = convert_sig_to_css(record["func_sig"])
                kind = "signature"
            elif "offsets" in entry and "struct_member_offset" in record:
                entry["offsets"][platform] = record["struct_member_offset"]
                kind = "struct_offset"
            else:
                continue
            updated_count += 1
            if debug:
                updated_symbols.append({"name": key, "type": kind, "platform": platform})

    with open(gamedata_path, "w", encoding="utf-8") as f:
        json.dump(gamedata, f, indent=2)
        f.write("\n")

    return updated_count, skipped_count, updated_symbols, skipped_symbols
