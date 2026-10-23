#!/usr/bin/env python3
"""
MatchZy (original) Gamedata Update Module

Updates matchzy.json for shobhit-pathak/MatchZy (WD-'s repo), for servers that run the
original release rather than the mrc4tt fork the matchzy generator follows. Same schema and
same four projectile-create keys, so the matchzy generator's update logic is reused unchanged.
Not a deploy target: the local plugin is the fork, so this file is published to the site only.
"""

import importlib.util
import os

# Seed source: https://raw.githubusercontent.com/shobhit-pathak/MatchZy/main/gamedata/matchzy.json

# Module metadata
MODULE_NAME = "matchzy-original"
MODULE_ENABLED = True

# Relative path to the gamedata file within the module output directory (same as the plugin's)
GAMEDATA_PATH = "gamedata/matchzy.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)

STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


def _matchzy():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "matchzy", "gamedata.py")
    spec = importlib.util.spec_from_file_location("_matchzy_gamedata_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Update the original matchzy.json; see matchzy/gamedata.py update()."""
    return _matchzy().update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug)
