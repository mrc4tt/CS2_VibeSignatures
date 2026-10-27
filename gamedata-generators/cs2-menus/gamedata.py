#!/usr/bin/env python3
"""
cs2-menus Gamedata Update Module (KeyValues, comment-preserving)

cs2-menus (github.com/mrc4tt/cs2-menus, a Metamod plugin) reads configs/signatures.ini:
a KeyValues file with root "Gamedata" and one block per key,

    "Key"
    {
        "linux"     "<sig or vtable slot>"
        "windows"   "<sig or vtable slot>"
    }

The file carries the author's search notes as // comments, which the vdf library would
drop, so the values are rewritten line by line and everything else - comments, line
endings, alignment - is left as it is. (canonicalize_output_text then turns the plugin's
CRLF into LF for every output; its KeyValues reader takes either.) Merge semantics as in the other seeded generators:
existing keys are refreshed in place, never added, renamed or dropped, and a value the
snapshot cannot satisfy keeps what it had.

Value sources, per key:
  OFFSET_KEYS    vfunc_index, written as a decimal string (GetOffset parses it)
  GLOBAL_KEYS    gv_sig - the plugin resolves these with ResolveRelativeAddress(3, 7) at
                 the start of the match, so only a gv_sig that starts AT the 7-byte
                 rip-relative load with its displacement at +3 is usable
  everything     func_sig
  else

Signatures are CModule::FindPattern's format: space-separated hex, one `?` per
wildcard, which is convert_sig_to_css. IsHearingClient is the one engine key; the
library comes from func_lib_map, the plugin looks it up in libengine2 itself.

deploy_local_plugins.sh copies the output to configs/signatures.ini in the plugin repo.
"""

import os
import re
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, normalize_func_name_colons_to_underscore

# Plugin: https://github.com/mrc4tt/cs2-menus - deliberately no "Seed source:" line.
# deploy_local_plugins.sh writes that repo's configs/signatures.ini from this output,
# so sync_plugin_templates would only be reading our own file back.
MODULE_NAME = "cs2-menus"
MODULE_ENABLED = True

# The plugin loads configs/signatures.ini; generated as .txt, which is the suffix the
# gamedata contract and the metadata/verify tools read as KeyValues, and deployed under
# the plugin's name by deploy_local_plugins.sh.
GAMEDATA_PATH = "configs/signatures.txt"
OUTPUT_PATHS = (GAMEDATA_PATH,)
STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)


# This plugin's own key names routed to our records - kept out of the shared ALIAS_OVERRIDES
# so they reach no other plugin's file. Identified on 14183 linux by resolving the plugin's
# own signatures in libserver.so and matching the hit against the snapshot's func_va.
KEY_SYMBOL_OVERRIDES = {
    # lea of the pointer variable the plugin dereferences (14183 0x278ea30)
    "GetGameTraceManager": "g_GameTraceManager",
    "UTIL_TraceShape": "TraceShape",
    # the plugin's signature lands on SetPawn; it respawns by re-attaching the pawn
    "UTIL_RespawnPlayer": "CBasePlayerController_SetPawn",
    "SwitchTeam": "CCSPlayerController_SwitchTeam",
    "SetMoveType": "CBaseEntity_SetMoveType",
    # the plugin's target (14183 0x1b76d20) is what this 5-byte jmp stub enters, same args
    "StopSoundEvent": "CBaseEntity_ScriptStopSound",
    # the plugin's target is a thin wrapper calling this with the same sret ABI
    "EmitSoundFilter": "CBaseEntity_EmitSoundFilter",
    "IsHearingClient": "CServerSideClient_IsHearingClient",
    "UTIL_Say": "Say_CommandHandler",
    "UTIL_SayTeam": "SayTeam_CommandHandler",
    # a pointer variable the plugin reads with GetValue<IGameEventManager2*>; the
    # plugin's own lea (14183 0x29c4e00) is not this record's address - verify at runtime
    "GetGameEventManager": "gameeventmanager",
    "GetLegacyGameEventListener": "LegacyGameEventListener",
    "UTIL_AcceptInput": "CEntityInstance_AcceptInput",
    "UTIL_DispatchSpawn": "CBaseEntity_DispatchSpawn",
    "UTIL_CreateEntity": "UTIL_CreateEntityByName",
    "OnTakeDamagePre": "CCSPlayer_DamageReactServices_TakeDamage",
    "TerminateRound": "CCSGameRules_TerminateRound",
    "CanAcquire": "CCSPlayer_ItemServices_CanAcquire",
    "ProcessUsercmds": "CBasePlayerController_ProcessUsercmds",
    "OnTakeDamage_Alive": "CCSPlayerPawn_OnTakeDamage_Alive",
    "CommitSuicide": "CBasePlayerPawn_CommitSuicide",
    "CollisionRulesChanged": "CBaseEntity_CollisionRulesChanged",
    # Teleport is the shared ALIAS_OVERRIDES route onto CBaseEntity_Teleport
    "ChangeTeam": "CCSPlayerController_ChangeTeam",
    "Respawn": "CCSPlayerController_Respawn",
    "DropWeapon": "CCSPlayer_WeaponServices_DropWeapon",
    "RemoveWeapons": "CCSPlayer_ItemServices_RemoveWeapons",
}

# Read with GetOffset (a vtable slot), not GetSig
OFFSET_KEYS = frozenset({
    "OnTakeDamage_Alive",
    "CommitSuicide",
    "CollisionRulesChanged",
    "Teleport",
    "ChangeTeam",
    "Respawn",
    "DropWeapon",
    "RemoveWeapons",
})

# Resolved with ResolveRelativeAddress(3, 7) at the match start
GLOBAL_KEYS = frozenset({
    "GetGameTraceManager",
    "GetGameEventManager",
})

_KEY_LINE = re.compile(r'^\s*"([^"]+)"\s*$')
_VALUE_LINE = re.compile(r'^(\s*"(linux|windows)"\s+")([^"]*)(".*)$')


def _value_for(key, record):
    """The value this key takes from one platform's record, or None."""
    if key in OFFSET_KEYS:
        index = record.get("vfunc_index")
        return None if index is None else str(index)
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
    """Refresh every linux/windows value in signatures.txt from the snapshot.

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    alias_to_name_map = {**(alias_to_name_map or {}), **KEY_SYMBOL_OVERRIDES}
    gamedata_path = os.path.join(output_dir, GAMEDATA_PATH)

    if not os.path.exists(gamedata_path):
        print(f"  Warning: cs2-menus gamedata not found: {gamedata_path}")
        return 0, 0, [], []

    # newline="" keeps the line endings exactly as the template has them
    with open(gamedata_path, "r", encoding="utf-8", newline="") as f:
        lines = f.read().splitlines(keepends=True)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    depth = 0
    key = None  # the block being read: "Key" at depth 1, then its { at depth 2
    pending = None
    seen = set()

    for i, line in enumerate(lines):
        code = line.split("//", 1)[0].strip()
        if code == "{":
            depth += 1
            if depth == 2:
                key = pending
            continue
        if code == "}":
            depth -= 1
            if depth < 2:
                key = None
            continue

        match = _KEY_LINE.match(code)
        if match and depth == 1:
            pending = match.group(1)
            continue

        body = line.rstrip("\r\n")
        match = _VALUE_LINE.match(body)
        if not match or key is None:
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
            kind = "offset" if key in OFFSET_KEYS else "signature"
            updated_symbols.append({"name": key, "type": kind, "platform": platform})

    with open(gamedata_path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

    return updated_count, skipped_count, updated_symbols, skipped_symbols
