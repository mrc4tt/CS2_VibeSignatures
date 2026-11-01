#!/usr/bin/env python3
"""
GameBanFix Gamedata Update Module (Valve KeyValues, comment-preserving)

GameBanFix (github.com/mrc4tt/GameBanFix, fork of Cruze03/GameBanFix, a Metamod
plugin) loads addons/gamebanfix/bin/<platform>/gamedata/gamebanfix.games.txt, which
its PackageScript copies from gamedata/gamebanfix.games.txt in the repo:

    "Games" { "csgo" { "Signatures" { "Key" { "library" ... "linux" ... "windows" ... } } } }

The file carries the author's search notes as // comments, so values are rewritten
line by line (as in cs2-menus) and everything else is left as it is. Merge semantics as
in the other seeded generators: existing keys are refreshed in place, never added,
renamed or dropped, and a value the snapshot cannot satisfy keeps what it had.

Value sources, per key:
  GLOBAL_KEYS    gv_sig - addresses::InitializeBanMap() takes the match start, skips 3
                 bytes and reads a rip-relative disp32 against match + 7, so only a
                 gv_sig that starts AT the 7-byte instruction with its displacement at
                 +3 is usable
  everything     func_sig
  else

Signatures are IDA style, one `?` per wildcard (convert_sig_to_css): the fork's
CGameConfig::HexToPattern hands them to KHook::LookupSignature as they are (it still
accepts the old \\x escapes).

deploy_local_plugins.sh copies the output to gamedata/gamebanfix.games.txt in the
plugin repo.
"""

import os
import re
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, normalize_func_name_colons_to_underscore

# Plugin: https://github.com/mrc4tt/GameBanFix - deliberately no "Seed source:" line.
# deploy_local_plugins.sh writes that repo's gamedata file from this output, so
# sync_plugin_templates would only be reading our own file back.
MODULE_NAME = "gamebanfix"
MODULE_ENABLED = True

GAMEDATA_PATH = "gamedata/gamebanfix.games.txt"
OUTPUT_PATHS = (GAMEDATA_PATH,)
STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)

# Resolved as lea/mov rip-relative at the match start (InitializeBanMap: +3, +7)
GLOBAL_KEYS = frozenset({
    "CCSGameRules__sm_mapGcBanInformation",
})

_KEY_LINE = re.compile(r'^\s*"([^"]+)"\s*$')
_VALUE_LINE = re.compile(r'^(\s*"(linux|windows)"\s+")([^"]*)(".*)$')


def _value_for(key, record):
    """The value this key takes from one platform's record, or None."""
    if key in GLOBAL_KEYS:
        if (
            record.get("gv_sig")
            and record.get("gv_inst_offset", 0) == 0
            and record.get("gv_inst_length") == 7
            and record.get("gv_inst_disp") == 3
        ):
            return convert_sig_to_css(record["gv_sig"])
        return None
    sig = record.get("func_sig")
    return convert_sig_to_css(sig) if sig else None


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Refresh every linux/windows value under "Signatures" from the snapshot.

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    gamedata_path = os.path.join(output_dir, GAMEDATA_PATH)

    if not os.path.exists(gamedata_path):
        print(f"  Warning: GameBanFix gamedata not found: {gamedata_path}")
        return 0, 0, [], []

    # newline="" keeps the line endings exactly as the template has them
    with open(gamedata_path, "r", encoding="utf-8", newline="") as f:
        lines = f.read().splitlines(keepends=True)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    stack = []  # names of the open blocks: Games, csgo, Signatures, <Key>
    pending = None
    seen = set()

    for i, line in enumerate(lines):
        code = line.split("//", 1)[0].strip()
        if code == "{":
            stack.append(pending)
            pending = None
            continue
        if code == "}":
            if stack:
                stack.pop()
            continue

        match = _KEY_LINE.match(code)
        if match:
            pending = match.group(1)
            continue

        if len(stack) < 2 or stack[-2] != "Signatures":
            continue
        key = stack[-1]

        body = line.rstrip("\r\n")
        match = _VALUE_LINE.match(body)
        if not match:
            continue
        platform = match.group(2)
        if platform not in platforms:
            continue

        yaml_name = normalize_func_name_colons_to_underscore(key, alias_to_name_map)
        library = func_lib_map.get(yaml_name)
        yaml_entry = yaml_data.get(yaml_name)
        if not library or not yaml_entry or yaml_entry.get("library") != library:
            if key not in seen:
                seen.add(key)
                skipped_count += 1
                if debug:
                    skipped_symbols.append({"name": key, "reason": "no matching YAML data"})
            continue

        value = _value_for(key, yaml_entry.get(platform) or {})
        if value is None:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": key, "reason": f"no usable {platform} value"})
            continue

        lines[i] = match.group(1) + value + match.group(4) + line[len(body):]
        updated_count += 1
        if debug:
            updated_symbols.append({"name": key, "type": "signature", "platform": platform})

    with open(gamedata_path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

    return updated_count, skipped_count, updated_symbols, skipped_symbols
