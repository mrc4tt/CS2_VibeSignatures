#!/usr/bin/env python3
"""
WeaponPaints (Nereziel) Gamedata Update Module

Updates weaponpaints.json for the original cs2-WeaponPaints plugin, for servers that run
Nereziel's release rather than the fork the weaponpaints generator follows. The original
reads one key, under its underscore spelling (CAttributeList_SetOrAddAttributeValueByName);
the fork reads thirteen in ::-spelling.

Same schema, so the weaponpaints generator's update logic is reused unchanged. Not a
deploy target: the local plugin is the fork, so this file is published to the site only.
"""

import importlib.util
import os

# Seed source: https://raw.githubusercontent.com/Nereziel/cs2-WeaponPaints/main/gamedata/weaponpaints.json

# Module metadata
MODULE_NAME = "weaponpaints-nereziel"
MODULE_ENABLED = True

# Relative path to the gamedata file within the module output directory (same as the plugin's)
GAMEDATA_PATH = "gamedata/weaponpaints.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)

STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


def _weaponpaints():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "weaponpaints", "gamedata.py")
    spec = importlib.util.spec_from_file_location("_weaponpaints_gamedata_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Update Nereziel's weaponpaints.json; see weaponpaints/gamedata.py update()."""
    return _weaponpaints().update_file(os.path.join(output_dir, GAMEDATA_PATH), yaml_data, func_lib_map,
                                       platforms, alias_to_name_map, debug)
