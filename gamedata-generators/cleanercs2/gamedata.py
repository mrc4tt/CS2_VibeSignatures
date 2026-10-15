#!/usr/bin/env python3
"""
CleanerCS2 Gamedata Update Module (stripper pattern)

CleanerCS2 is a Metamod plugin that hooks tier0's internal CLoggingSystem::LogDirect
and drops console lines matching a regex. The function is not exported, so the
plugin needs a signature. It reads addons/cleanercs2/gamedata.json and falls back
to the literal compiled into src/cleanercs2.cpp when the file is missing or has no
entry for the running platform.

The output mirrors the install layout (addons/cleanercs2/gamedata.json), and
deploy_local_plugins.sh copies it to package/gamedata.json in
~/customGIT/CleanerCS2, which xmake packs to that same path.

The signature format matches what `KHook::LookupSignature` parses: space-separated
hex bytes with a single `?` per wildcard, which is exactly `convert_sig_to_css`.
"""

import json
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, normalize_func_name_colons_to_underscore

# Plugin: https://github.com/mrc4tt/CleanerCS2 - deliberately no "Seed source:" line.
# deploy_local_plugins.sh writes that repo's package/gamedata.json from this output,
# so sync_plugin_templates would only be reading our own file back.
MODULE_NAME = "cleanercs2"
MODULE_ENABLED = True

GAMEDATA_PATH = "addons/cleanercs2/gamedata.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)
STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Refresh every signature in gamedata.json from the snapshot.

    Merge semantics, same as the other seeded generators: the keys already in the
    file are refreshed in place and never renamed, added or dropped, so a key the
    snapshot cannot satisfy keeps its previous value rather than disappearing.

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    gamedata_path = os.path.join(output_dir, GAMEDATA_PATH)

    if not os.path.exists(gamedata_path):
        print(f"  Warning: CleanerCS2 gamedata not found: {gamedata_path}")
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
