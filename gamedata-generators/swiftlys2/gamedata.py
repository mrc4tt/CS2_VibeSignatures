#!/usr/bin/env python3
"""
SwiftlyS2 Gamedata Update Module

Updates signatures.jsonc and offsets.jsonc for SwiftlyS2 plugin framework.
"""

import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_swiftly, normalize_func_name_colons_to_underscore, load_jsonc, save_jsonc

# Module metadata
MODULE_NAME = "SwiftlyS2"
MODULE_ENABLED = True

# Seed source: https://raw.githubusercontent.com/swiftly-solution/swiftlys2/master/plugin_files/gamedata/cs2/core/signatures.jsonc template=templates/signatures.jsonc output=plugin_files/gamedata/cs2/core/signatures.jsonc
# Seed source: https://raw.githubusercontent.com/swiftly-solution/swiftlys2/master/plugin_files/gamedata/cs2/core/offsets.jsonc template=templates/offsets.jsonc output=plugin_files/gamedata/cs2/core/offsets.jsonc

# Relative paths to gamedata files within the module output directory
SIGNATURES_PATH = "plugin_files/gamedata/cs2/core/signatures.jsonc"
OFFSETS_PATH = "plugin_files/gamedata/cs2/core/offsets.jsonc"
OUTPUT_PATHS = (SIGNATURES_PATH, OFFSETS_PATH)

# Source-owned upstream baselines; provenance is recorded in templates/upstream.json.
DOWNLOAD_SOURCES = ()
STATIC_SOURCES = (
    ("templates/offsets.jsonc", OFFSETS_PATH),
    ("templates/signatures.jsonc", SIGNATURES_PATH),
)


# SwiftlyS2's own key names routed to our records. Kept here rather than in the shared
# ALIAS_OVERRIDES so they reach no other plugin's file. verify_plugin_gamedata.py and
# sync_plugin_templates.py read this table too.
KEY_SYMBOL_OVERRIDES = {
    # the (entity, info) TakeDamage, which the analysis files as CBaseEntity_TakeDamageOld;
    # the author's own signature lands on it on both platforms (14192 linux 0xd6d9c0,
    # windows 0x1803f3ae0). Until now the key was never generated, only shipped as written.
    "CBaseEntity::TakeDamage": "CBaseEntity_TakeDamageOld",
    # its spelling; the windows signature is byte-identical to ours (14192 0x1805506f0)
    "GetWeaponCSDataFromKey": "GetCSWeaponDataFromKey",
    # the static projectile factories, anchored on the same "<x>_projectile" strings our
    # find-C*Projectile_Create preprocessors use. No flashbang Create record exists, so
    # CFlashbangProjectile::EmitGrenade stays the author's value.
    "CHEGrenadeProjectile::EmitGrenade": "CHEGrenadeProjectile_Create",
    "CMolotovProjectile::EmitGrenade": "CMolotovProjectile_Create",
    "CDecoyProjectile::EmitGrenade": "CDecoyProjectile_Create",
    "CSmokeGrenadeProjectile::EmitGrenade": "CSmokeGrenadeProjectile_Create",
    # Interface slots, filed under the class that implements them. Each index equals
    # the author's on 14192 on both platforms.
    "IServerGameClients::ClientCommand": "CSource2GameClients_ClientCommand",
    "IServerGameClients::ClientConnect": "CSource2GameClients_ClientConnect",
    "IServerGameClients::ClientDisconnect": "CSource2GameClients_ClientDisconnect",
    "IServerGameClients::ClientPutInServer": "CSource2GameClients_ClientPutInServer",
    "IServerGameClients::OnClientConnected": "CSource2GameClients_OnClientConnected",
    "IServerGameDLL::GameFrame": "CSource2Server_GameFrame",
    "IServerGameDLL::GameServerSteamAPIActivated": "CSource2Server_GameServerSteamAPIActivated",
    "IServerGameDLL::GameServerSteamAPIDeactivated": "CSource2Server_GameServerSteamAPIDeactivated",
    "IServerGameDLL::PreWorldUpdate": "CSource2Server_PreWorldUpdate",
    "INetworkServerService::StartupServer": "CNetworkServerService_StartupServer",
    "CGameRules::GoToIntermission": "CCSGameRules_GoToIntermission",
    # Members the analysis files under the derived class (CServerSideClientBase sits at
    # offset 0 of CServerSideClient) or the base server; same offsets as the author's.
    "CNetworkGameServer::m_Clients": "CNetworkGameServerBase_m_Clients",
    "CServerSideClientBase::m_bFakePlayer": "CServerSideClient_m_bFakePlayer",
    "CServerSideClientBase::m_bIsHLTV": "CServerSideClient_m_bIsHLTV",
    "CServerSideClientBase::m_Name": "CServerSideClient_m_Name",
    "CServerSideClientBase::m_nClientSlot": "CServerSideClient_m_nClientSlot",
    "CServerSideClientBase::m_nConnectionTypeFlags": "CServerSideClient_m_nConnectionTypeFlags",
    "CServerSideClientBase::m_nEntityIndex": "CServerSideClient_m_nEntityIndex",
    "CServerSideClientBase::m_NetChannel": "CServerSideClient_m_NetChannel",
    "CServerSideClientBase::m_nSignonState": "CServerSideClient_m_nSignonState",
    "CServerSideClientBase::m_SteamID": "CServerSideClient_m_SteamID",
    "CServerSideClientBase::m_UserID": "CServerSideClient_m_UserID",
    "CServerSideClientBase::m_UserIDString": "CServerSideClient_m_UserIDString",
    "CServerSideClientBase::m_DisconnectedSteamID": "CServerSideClient_m_SteamIDMirror",
    # Records the analysis already had under its own names. DropActiveItem, SelectWeapon
    # and RunCommand are the same slots on both platforms; OnJumpLegacy is the
    # "player_jump" function upstream files as CheckJumpButton (CheckJumpButtonLegacy
    # calls it); ProcessUserCmd and Cmd_ExecuteCommand land on these heads with the
    # author's own signatures. BotNavIgnore1-3 are one patch site in CCSBotManager::AddBot
    # (SwiftlyS2 lists the same signature three times).
    "CCSPlayer_ItemServices::DropActiveItem": "CCSPlayer_ItemServices_DropActivePlayerWeapon",
    "CCSPlayer_WeaponServices::SelectWeapon": "CCSPlayer_WeaponServices_SelectItem",
    "CPlayer_MovementServices::RunCommand": "vtidx_PlayerRunCommand",
    "CCSPlayer_MovementServices::OnJumpLegacy": "CCSPlayer_MovementServices_CheckJumpButton",
    "CCSPlayerController::ProcessUserCmd": "CBasePlayerController_ProcessUsercmds",
    "Cmd_ExecuteCommand": "CInputService_ProcessCommand",
    "CTakeDamageInfo::Constructor": "CTakeDamageInfo_ctor",
    "CFlashbangProjectile::EmitGrenade": "CFlashbangProjectile_Create",
    "BotNavIgnore1": "CCSBotManager_AddBot_BotNavIgnore",
    "BotNavIgnore2": "CCSBotManager_AddBot_BotNavIgnore",
    "BotNavIgnore3": "CCSBotManager_AddBot_BotNavIgnore",
    # Interface slots, filed under the implementing class.
    "IVEngineServer2::SetClientListening": "CEngineServer_SetClientListening",
    "IGameEventSystem::PostEventAbstract": "CGameEventSystem_PostEventAbstract",
    "ICvar::DispatchConCommand": "CCvar_DispatchConCommand",
    "IGameEventManager2::FireEvent": "CGameEventManager_FireEvent",
    "IServerGameClients::ClientVoice": "CSource2GameClients_ClientVoice",
    "CGameRules::GetViewVectors": "CCSGameRules_GetViewVectors",
    # SwiftlyS2's ResetUserSettings re-reads "rate" from userinfo: the SDK's
    # UpdateRateFromUserInfo.
    "CServerSideClientBase::ResetUserSettings": "CServerSideClientBase_UpdateRateFromUserInfo",
    # CNetChan's INetChannelInfo / INetChannel slots. Where these differ from the
    # author's 14192 values, the binary decides: GetAvgData is slot 15 (Steam's bytes/sec;
    # 14 is a plain per-flow float), and every INetChannel slot is one higher on linux,
    # where the dtor takes two slots (CanPacket 48 holds "!CanPacket()", SetTimeout 56
    # "NetChan Setting Timeout"). SuppressTransmit / IsSuppressingTransmit store and load
    # the byte CanPacket tests (linux 82/83, windows 81/82); the author's 80/81 and 79/80
    # are the pending-disconnect reason. SwiftlyS2's INetChannelInfo has no GetPeakJitter,
    # so its names from 14 on are one slot early: slot 14 is a running maxss of 0.1 ms
    # frame-time samples, reset to -1 and bucketed into the jitter histogram (linux
    # networksystem 0x29b130 writes flow+0x10), and the slot it calls GetAvgPacketBytes
    # (15) is the bytes/sec function. Both keys therefore ship slot 15.
    "INetChannelInfo::GetName": "CNetChan_GetName",
    "INetChannelInfo::GetAddress": "CNetChan_GetAddress",
    "INetChannelInfo::GetRemoteAddress": "CNetChan_GetRemoteAddress",
    "INetChannelInfo::GetTime": "CNetChan_GetTime",
    "INetChannelInfo::GetTimeConnected": "CNetChan_GetTimeConnected",
    "INetChannelInfo::GetDataRate": "CNetChan_GetDataRate",
    "INetChannelInfo::IsLocalHost": "CNetChan_IsLocalHost",
    "INetChannelInfo::IsLoopback": "CNetChan_IsLoopback",
    "INetChannelInfo::IsTimingOut": "CNetChan_IsTimingOut",
    "INetChannelInfo::IsPlayback": "CNetChan_IsPlayback",
    "INetChannelInfo::GetAvgLatency": "CNetChan_GetAvgLatency",
    "INetChannelInfo::GetEngineLatency": "CNetChan_GetEngineLatency",
    "INetChannelInfo::GetAvgLoss": "CNetChan_GetAvgLoss",
    "INetChannelInfo::GetAvgChoke": "CNetChan_GetAvgChoke",
    "INetChannelInfo::GetAvgData": "CNetChan_GetAvgData",
    "INetChannelInfo::GetAvgPacketBytes": "CNetChan_GetAvgData",
    "INetChannelInfo::GetAvgPackets": "CNetChan_GetAvgPackets",
    "INetChannelInfo::GetTotalData": "CNetChan_GetTotalData",
    "INetChannelInfo::GetTotalPackets": "CNetChan_GetTotalPackets",
    "INetChannelInfo::GetSequenceNr": "CNetChan_GetSequenceNr",
    "INetChannelInfo::GetTimeSinceLastReceived": "CNetChan_GetTimeSinceLastReceived",
    "INetChannelInfo::GetRemoteFramerate": "CNetChan_GetRemoteFramerate",
    "INetChannelInfo::GetTimeoutSeconds": "CNetChan_GetTimeoutSeconds",
    "INetChannelInfo::GetTimeUntilTimeout": "CNetChan_GetTimeUntilTimeout",
    "INetChannelInfo::SetInterpolationAmount": "CNetChan_SetInterpolationAmount",
    "INetChannelInfo::SetNumPredictionErrors": "CNetChan_SetNumPredictionErrors",
    "INetChannelInfo::SetShowNetMessages": "CNetChan_SetShowNetMessages",
    "INetChannel::CanPacket": "CNetChan_CanPacket",
    "INetChannel::IsOverflowed": "CNetChan_IsOverflowed",
    "INetChannel::HasPendingReliableData": "CNetChan_HasPendingReliableData",
    "INetChannel::SetMinDataRate": "CNetChan_SetMinDataRate",
    "INetChannel::SetMaxDataRate": "CNetChan_SetMaxDataRate",
    "INetChannel::SetTimeout": "CNetChan_SetTimeout",
    "INetChannel::IsTimedOut": "CNetChan_IsTimedOut",
    "INetChannel::SuppressTransmit": "CNetChan_SuppressTransmit",
    "INetChannel::IsSuppressingTransmit": "CNetChan_IsSuppressingTransmit",
}

# Routing for one file only. CCSPlayer_WeaponServices::DropWeapon is the vtable slot in
# offsets.jsonc but, in signatures.jsonc, a pattern anchored on "#SFUI_Notice_YouDroppedWeapon"
# that lands on the non-virtual handler.
KEY_SYMBOL_OVERRIDES_BY_OUTPUT = {
    "signatures.jsonc": {
        "CCSPlayer_WeaponServices::DropWeapon": "CCSPlayer_WeaponServices_HandleDropWeapon",
    },
}


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False):
    """
    Update SwiftlyS2 signatures.jsonc and offsets.jsonc files.

    Args:
        yaml_data: Loaded YAML data
        func_lib_map: Function name to library mapping
        platforms: List of platforms to update
        output_dir: Path to this module's versioned output directory
        alias_to_name_map: Mapping from aliases to function names
        debug: If True, collect updated and skipped symbols info

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    total_updated = 0
    total_skipped = 0
    all_updated_symbols = []
    all_skipped_symbols = []

    # Update signatures.jsonc
    sig_path = os.path.join(output_dir, SIGNATURES_PATH)
    if os.path.exists(sig_path):
        updated, skipped, updated_syms, skipped_syms = _update_signatures(
            yaml_data, func_lib_map, platforms, sig_path, alias_to_name_map, debug
        )
        total_updated += updated
        total_skipped += skipped
        all_updated_symbols.extend(updated_syms)
        all_skipped_symbols.extend(skipped_syms)
    else:
        print(f"  Warning: SwiftlyS2 signatures not found: {sig_path}")

    # Update offsets.jsonc
    off_path = os.path.join(output_dir, OFFSETS_PATH)
    if os.path.exists(off_path):
        updated, skipped, updated_syms, skipped_syms = _update_offsets(
            yaml_data, func_lib_map, platforms, off_path, alias_to_name_map, debug
        )
        total_updated += updated
        total_skipped += skipped
        all_updated_symbols.extend(updated_syms)
        all_skipped_symbols.extend(skipped_syms)
    else:
        print(f"  Warning: SwiftlyS2 offsets not found: {off_path}")

    return total_updated, total_skipped, all_updated_symbols, all_skipped_symbols


def _update_signatures(yaml_data, func_lib_map, platforms, sig_path, alias_to_name_map, debug=False):
    """Update SwiftlyS2 signatures.jsonc file."""
    signatures = load_jsonc(sig_path)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    for func_name, entry in signatures.items():
        # Convert :: to _ for matching with YAML data
        own = {**KEY_SYMBOL_OVERRIDES, **KEY_SYMBOL_OVERRIDES_BY_OUTPUT["signatures.jsonc"]}
        yaml_func_name = own.get(func_name) or normalize_func_name_colons_to_underscore(
            func_name, alias_to_name_map
        )

        # Determine library
        library = entry.get("lib")
        if not library and yaml_func_name in func_lib_map:
            library = func_lib_map[yaml_func_name]

        if not library:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "unknown library"})
            continue

        # Find matching YAML data
        yaml_entry = yaml_data.get(yaml_func_name)
        if not yaml_entry or yaml_entry.get("library") != library:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "no matching YAML data"})
            continue

        # Update platform signatures; a patch site (BotNavIgnore) ships its patch_sig
        for platform in platforms:
            payload = yaml_entry.get(platform) or {}
            raw = payload.get("func_sig") or payload.get("patch_sig")
            if raw:
                sig = convert_sig_to_swiftly(raw)
                entry[platform] = sig
                updated_count += 1
                if debug:
                    updated_symbols.append({"name": func_name, "type": "signature", "platform": platform})

    # Write back
    save_jsonc(sig_path, signatures)

    return updated_count, skipped_count, updated_symbols, skipped_symbols


def _update_offsets(yaml_data, func_lib_map, platforms, off_path, alias_to_name_map, debug=False):
    """Update SwiftlyS2 offsets.jsonc file."""
    offsets = load_jsonc(off_path)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    for func_name, entry in offsets.items():
        # Convert :: to _ for matching with YAML data
        own = {**KEY_SYMBOL_OVERRIDES, **KEY_SYMBOL_OVERRIDES_BY_OUTPUT.get("offsets.jsonc", {})}
        yaml_func_name = own.get(func_name) or normalize_func_name_colons_to_underscore(
            func_name, alias_to_name_map
        )

        # Find matching YAML data
        yaml_entry = yaml_data.get(yaml_func_name)
        if not yaml_entry:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "no matching YAML data"})
            continue

        # Update platform offsets
        for platform in platforms:
            if platform in yaml_entry:
                # Check for vfunc_index (virtual function offset)
                if "vfunc_index" in yaml_entry[platform]:
                    entry[platform] = yaml_entry[platform]["vfunc_index"]
                    updated_count += 1
                    if debug:
                        updated_symbols.append({"name": func_name, "type": "offset", "platform": platform})
                # Check for struct_member_offset (struct member offset)
                elif "struct_member_offset" in yaml_entry[platform]:
                    entry[platform] = yaml_entry[platform]["struct_member_offset"]
                    updated_count += 1
                    if debug:
                        updated_symbols.append({"name": func_name, "type": "struct_offset", "platform": platform})

    # Write back
    save_jsonc(off_path, offsets)

    return updated_count, skipped_count, updated_symbols, skipped_symbols
