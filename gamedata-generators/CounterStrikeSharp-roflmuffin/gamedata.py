#!/usr/bin/env python3
"""
CounterStrikeSharp (roflmuffin) Gamedata Update Module

Updates gamedata.json for stock CounterStrikeSharp, the key set roflmuffin's repo ships,
for servers that run the original framework rather than the mrc4tt fork the
CounterStrikeSharp generator follows. The fork adds keys (the CCSCustomHudLayout family,
CheckTransmit, CBaseEntity_TakeDamage) that stock CSS never reads, and stock CSS still
carries GameEventManager, which the fork dropped.

Same schema, so the CounterStrikeSharp generator's update logic is reused unchanged
(signatures, vtable slots proved the way CSS reads them, offsets). Not a deploy target:
the local install is the fork, so this file is published to the site only.
"""

import importlib.util
import os

# Seed source: https://raw.githubusercontent.com/roflmuffin/CounterStrikeSharp/main/configs/addons/counterstrikesharp/gamedata/gamedata.json

# Version 2: the context names the game build, whose binaries prove each vtable slot.
GENERATOR_API_VERSION = 2

# Module metadata
MODULE_NAME = "CounterStrikeSharp-roflmuffin"
MODULE_ENABLED = True

# Relative path to gamedata file within the module output directory (same as the plugin's)
GAMEDATA_PATH = "config/addons/counterstrikesharp/gamedata/gamedata.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)

STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


def _css():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CounterStrikeSharp", "gamedata.py")
    spec = importlib.util.spec_from_file_location("_css_gamedata_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False, *, context=None):
    """Update roflmuffin's gamedata.json; see CounterStrikeSharp/gamedata.py update()."""
    return _css().update_file(os.path.join(output_dir, GAMEDATA_PATH), yaml_data, func_lib_map, platforms,
                              alias_to_name_map, debug, context=context)
