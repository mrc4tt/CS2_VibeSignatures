#!/usr/bin/env python3
"""
StatusModifier Gamedata Update Module (JSONC, comment-preserving)

StatusModifier (github.com/Cruze03/StatusModifier, a Metamod plugin that rewrites the
`status` command's output) reads gamedata/statusmodifier.jsonc:

    { "Signatures": { "Key": { "library", "windows", "linux" } },
      "Offsets":    { "Key": { "windows", "linux" } },
      "Patches":    {} }

Merge semantics as in the other seeded generators: the keys already in the file are
refreshed in place, never added, renamed or dropped, and a value the snapshot cannot
satisfy keeps what it had. Signatures are written one `?` per wildcard
(convert_sig_to_css), the style the plugin's own file uses.

Generated only, not deployed: this fork has no copy of the plugin, so the file is
published with every build for the site and the scanner to compare against.
"""

import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, load_jsonc, normalize_func_name_colons_to_underscore, save_jsonc

MODULE_NAME = "StatusModifier"
MODULE_ENABLED = True

# Seed source: https://raw.githubusercontent.com/Cruze03/StatusModifier/main/gamedata/statusmodifier.jsonc

GAMEDATA_PATH = "gamedata/statusmodifier.jsonc"
OUTPUT_PATHS = (GAMEDATA_PATH,)
STATIC_SOURCES = ((GAMEDATA_PATH, GAMEDATA_PATH),)

# StatusModifier's own key names routed to our records (read by verify_plugin_gamedata,
# sync_plugin_templates and the metadata coverage through generator_key_overrides).
KEY_SYMBOL_OVERRIDES = {
    # the pre-filter CServerSideClient runs every incoming message through; the
    # author's note ("tried to send a RebroadcastSourceId msg.") names the same string
    # our record is anchored on, and his signature lands on its head on both platforms
    "FilterMessage": "INetworkMessageProcessingPreFilter_FilterMessage",
    # INetworkSystem slot 32 (returns this+0x3c, the public netadr filled from
    # SteamGameServer()->GetPublicIP); same index as the author's on both platforms
    "GetPublicAdr": "CNetworkSystem_GetPublicAdr",
    # CServerSideClientBase sits at offset 0 of CServerSideClient, where the member is filed
    "CServerSideClientBase::m_nClientSlot": "CServerSideClient_m_nClientSlot",
}


def _record_name(key, alias_to_name_map):
    return KEY_SYMBOL_OVERRIDES.get(key) or normalize_func_name_colons_to_underscore(key, alias_to_name_map)


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """Refresh every linux/windows value under "Signatures" and "Offsets".

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    path = os.path.join(output_dir, GAMEDATA_PATH)
    if not os.path.exists(path):
        print(f"  Warning: StatusModifier gamedata not found: {path}")
        return 0, 0, [], []

    data = load_jsonc(path)
    updated, skipped = [], []

    def skip(key, reason):
        skipped.append({"name": key, "reason": reason})

    for key, entry in (data.get("Signatures") or {}).items():
        name = _record_name(key, alias_to_name_map)
        library = entry.get("library") or func_lib_map.get(name)
        record = yaml_data.get(name)
        if not record or not library or record.get("library") != library:
            skip(key, "no matching YAML data")
            continue
        for platform in platforms:
            sig = (record.get(platform) or {}).get("func_sig")
            if sig:
                entry[platform] = convert_sig_to_css(sig)
                updated.append({"name": key, "type": "signature", "platform": platform})

    for key, entry in (data.get("Offsets") or {}).items():
        record = yaml_data.get(_record_name(key, alias_to_name_map))
        if not record:
            skip(key, "no matching YAML data")
            continue
        for platform in platforms:
            payload = record.get(platform) or {}
            if "vfunc_index" in payload:
                entry[platform] = payload["vfunc_index"]
                updated.append({"name": key, "type": "offset", "platform": platform})
            elif "struct_member_offset" in payload:
                entry[platform] = payload["struct_member_offset"]
                updated.append({"name": key, "type": "struct_offset", "platform": platform})

    save_jsonc(path, data)
    return len(updated), len(skipped), (updated if debug else []), (skipped if debug else [])
