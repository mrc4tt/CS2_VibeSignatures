#!/usr/bin/env python3
"""Ensure every symbol from the local plugin gamedata seeds is analyzable in an
analysis config.

Reads every entry from the seed files below (weaponpaints, matchzy, bot-controller,
bot-hider) and injects into the server module of the given config:

  - a find-task (skills:)        name: find-<symbol>, expected_output <symbol>.{platform}.yaml
  - a symbol entry (symbols:)    category derived from the gamedata entry:
                                     signatures       -> func
                                     offsets + m_*    -> structmember (struct: + member:)
                                     offsets + method -> vfunc
  - an alias for ::-style keys so gamedata key names resolve to symbol names
  - a SKILL.md under .claude/skills/find-<symbol>/ when one does not already exist

Idempotent per symbol: already-present symbols are skipped, so newly added gamedata
entries are picked up on the next run without duplicating existing ones.

Usage:
  uv run ensure_local_gamedata_symbols.py -config configs/14178b.yaml
  uv run ensure_local_gamedata_symbols.py            # newest configs/<GAMEVER>.yaml
"""

import argparse
import glob
import json
import os
import re
import sys

SEEDS = [
    "gamedata-generators/weaponpaints/gamedata/weaponpaints.json",
    "gamedata-generators/matchzy/gamedata/matchzy.json",
    "gamedata-generators/bot-controller/gamedata/bot-controller.json",
    "gamedata-generators/bot-hider/gamedata/bot-hider.json",
]

SKILLS_DIR = ".claude/skills"

# BotProfile er en non-polymorphic POD (ingen vtable) - offset-entries er structmembers.
# Member-navne fra Bot-Improver referencegamedata (IDA-verificeret 14178b: POD, win==linux).
BUYSTATE_MEMBERS = {
    "DoneBuying": "m_doneBuying",
    "InitialDelay": "m_isInitialDelay",
}
BOTPROFILE_MEMBERS = {
    "Aggression": "m_aggression", "Skill": "m_skill", "Teamwork": "m_teamwork",
    "WeaponPref": "m_weaponPreference", "WeaponPrefCount": "m_weaponPreferenceCount",
    "Cost": "m_cost", "Difficulty": "m_difficultyFlags", "ReactionTime": "m_reactionTime",
    "AttackDelay": "m_attackDelay",
    "LookAngleMaxAccelAttacking": "m_lookAngleMaxAccelAttacking",
    "LookAngleStiffnessAttacking": "m_lookAngleStiffnessAttacking",
    "LookAngleDampingAttacking": "m_lookAngleDampingAttacking",
}

# Symbols this fork carries that upstream does not. sync_upstream.sh resolves
# config conflicts in upstream's favour, so an upstream merge silently DROPS them
# from the newest config - it did exactly that to all six CustomHud entries on
# 14181, whose artifacts then packed as "undeclared symbol YAML" and shipped
# nowhere. Re-injected on every run, like the seed symbols.
FORK_OWNED_SYMBOLS = [
    # (symbol_name, category, lib, alias)
    ("CCSCustomHudLayout_SetDialogVariableString", "func", None, None),
    ("CCSCustomHudLayout_SetDialogVariableStringForPlayer", "func", None, None),
    ("CCSCustomHudLayout_SetHasClass", "func", None, None),
    ("CCSCustomHudLayout_SetHasClassForPlayer", "func", None, None),
    ("CCSCustomHudLayout_SetInputCaptureEnabled", "func", None, None),
    ("CCSPointScript_OnCustomHudClicked", "func", None, None),
    # CS2Fixes' gamedata asks for this under the alias; upstream declares neither
    ("CTakeDamageInfo_ctor", "func", None, "CTakeDamageInfo"),
    # CounterStrikeSharp ships this signature and the cs2-signatures tracker had no
    # reference for it: the artifacts existed only on 14178b and no task declared
    # them, so gamesymbol_snapshot dropped them as undeclared. Relocated to 14181
    # (linux 0x1904cd0, windows 0x180d452d0, both a unique wildcarded match).
    ("CCSNavArea_IsValidNavMesh", "func", None, None),
    # CS2Fixes ships signatures for these three and the analysis had no record under
    # any name - verified by resolving its own patterns in libserver.so/server.dll and
    # finding no artifact at the resulting addresses. All three are server functions
    # with a clean head and a unique match on both platforms.
    ("SetBeamOrigin", "func", None, None),
    ("SetBeamEndPos", "func", None, None),
    ("IsCommandWhitelisted", "func", None, None),
    # CS2Fixes lists this in both Signatures and Patches: the anchor is the `75 ??`
    # (jnz) it rewrites to EB to force the branch, so it is a patch site rather than a
    # function head - hence category patch with patch_bytes, not func.
    ("SetSchemaHammerUniqueId", "patch", None, None),
    # CounterStrikeSharp's key is offsets-only, so it carries no signatures.library,
    # and the config declared the artifact through per-platform declaration tasks
    # without ever adding a symbols: entry - so build_function_library_map had no
    # library for it and the generator skipped it as "unknown library". The slots
    # sat frozen in the template instead (linux 0 / windows 2, which the artifacts
    # do confirm). Declared here so they are regenerated and RTTI-checked instead.
    ("CEntityResourceManifest_AddResource", "vfunc", "engine", None),
]

# Fork-owned find-tasks for symbols upstream DOES declare. inject() skips a
# symbol that is already present, so a task upstream never had (or deliberately
# commented out) is not restored by FORK_OWNED_SYMBOLS - and without a task the
# artifact is never declared, so gamesymbol_snapshot drops it as "undeclared".
#
# Each entry names the task that must FOLLOW it. Position matters: task order
# drives expected_input dependency resolution, and inserting at the head of the
# skills list made pack fail with "Missing required symbol YAML" for an
# unrelated symbol. Anchoring reproduces the layout that is known to pack.
FORK_OWNED_TASKS = [
    # (symbol_name, module, insert_before_task)
    ("CCSPlayer_MovementServices_FullWalkMove", "server",
     "find-CCSPlayer_MovementServices_FullWalkMove_SpeedClamp"),
    ("CCSPlayer_MovementServices_FullWalkMove_SpeedClamp", "server",
     "find-CCSPlayer_MovementServices_CheckJumpButton"),
    ("CTakeDamageInfo_ctor", "server", "find-CTakeDamageInfo_GetWeaponName"),
]

# Fork-owned category decisions. Upstream declares some offset-entries as vfunc
# even though the class is a non-polymorphic POD, and sync_upstream.sh resolves
# config conflicts in upstream's favour - so these get re-asserted after every
# merge instead of being skipped as "already present".
CATEGORY_DECISIONS = {
    # Every CCSBot_Profile artifact on both platforms is structmember-shaped
    # (CCSBot::m_profile, offset 0x8, size 8; windows write is "mov [rdi+8], rax").
    # As vfunc, generation takes the vfunc path for a structmember payload.
    "CCSBot_Profile": ("structmember", "CCSBot", "m_profile"),
}

# Renamed engine symbols: old gamedata keys map to the canonical analyzed symbol via
# config aliases instead of separate analysis tasks.
ALIAS_OVERRIDES = {
    # bot-hider bruger GameResourceServiceServer; upstream analyserer klassen som
    # CGameResourceService (engine-modulet, linux 0x50 / windows 0x58).
    "GameResourceServiceServer::m_pEntitySystem": "CGameResourceService_m_pEntitySystem",
    "CCSPlayerController_HandleCommandJoinTeam": "CBasePlayerController_HandleCommand_JoinTeam",
    "CCSPlayerController_HandleCommand_JoinTeam": "CBasePlayerController_HandleCommand_JoinTeam",
    # IDA-verified 14178b: matchzy's GetSlot sig targets the same function upstream
    # analyzes as CCSPlayer_WeaponServices_Weapon_GetSlot (pseudocode confirmed).
    "CCSPlayer_WeaponServices::GetSlot": "CCSPlayer_WeaponServices_Weapon_GetSlot",
    # ShowHudHint was refactored into CEnvHudHint_API::ShowHudHint in 14168; the old
    # key survives as an alias instead of a second declaration (the config validator
    # rejects two symbols sourcing one artifact).
    "ShowHudHint": "CEnvHudHint_API_ShowHudHint",
    # CounterStrikeSharp ships this offset under the short name its schema code uses
    # (schema.cpp:167 reads GetOffset("SetStateChanged")), while the analysis files the
    # virtual as CEntityInstance_NetworkStateChanged. Same values - windows 28 from
    # vfunc_offset 0xe0, linux 29 from 0xe8 - so the alias only moves the key from the
    # frozen template into pipeline control.
    "SetStateChanged": "CEntityInstance_NetworkStateChanged",
    # bot-controller asks for the CCSPlayer_WeaponServices::DropWeapon vtable index
    # under its own short key. A separate vtidx_DropWeapon record carried the same
    # func_va on both platforms (linux 0x15cde70 / windows 0x180acf6f0) - one
    # function, two records, which is the ClientPrint trap again. Its own artifacts
    # then lost vfunc_index (see the seeder ratchet), so the key fell back to the
    # template's stale 24/25 while RTTI says 29/28. Aliased onto the canonical
    # symbol, which carries the index, and the duplicate is retired below.
    "vtidx::DropWeapon": "CCSPlayer_WeaponServices_DropWeapon",
    # CS2Fixes ships an Offsets entry under the bare method name; the analysis files
    # the virtual as CBaseEntity_Teleport (whose only alias was CBaseEntity::Teleport,
    # which does not fold to "Teleport").
    "Teleport": "CBaseEntity_Teleport",
    # CS2Fixes calls it SnapViewAngles on CBasePlayerPawn. Its signature resolves to
    # 0x1837d60 / 0x180cab920, which is the same function this repo files as
    # CCSPlayerPawn_SetEyeAngles - verified by address, not by name.
    "CBasePlayerPawn_SnapViewAngles": "CCSPlayerPawn_SetEyeAngles",
}


# Downstream keys a declared symbol must STOP claiming. ALIAS_OVERRIDES points a
# key at the right symbol; this points a key away from the wrong one (rule 15:
# when two things claim one key, decide, and write the decision down).
FORK_OWNED_ALIAS_REMOVALS = {
    # (no entries: the one case this was written for turned out to need the
    # declaration retired, because the generator folds names rather than reading
    # aliases. Kept as the lever for the next key two symbols fight over.)
}


# Fork-owned OBSOLETE tasks: declarations for artifacts that turned out to be wrong.
FORK_OWNED_OBSOLETE_TASKS = [
    # The GiveNamedItem2 records were withdrawn: 0x1566a70 is the function the
    # binary itself names CCSPlayer_ItemServices_GiveNamedItem, which this repo
    # already analyses, while the records filed under GiveNamedItem2 pointed at
    # sub_1566A80 - an adjacent unnamed overload forwarding to the same
    # implementation with a different default-argument set. Keeping a record whose
    # NAME is the plugin key but whose ADDRESS is a sibling overload is the
    # ClientPrint trap; the plugin key is aliased to the named symbol instead.
    ("find-GiveNamedItem2", "server", "name belongs to CCSPlayer_ItemServices_GiveNamedItem"),
    # Retired with the declaration above: the task existed only to feed a key that
    # wants a field offset, and its artifact would now pack as undeclared.
    ("find-vtidx_DropWeapon", "server", "declaration retired, see FORK_OWNED_REMOVALS"),
    # An invented name for the shared body that CBaseTrigger::EndTouch's vtable
    # wrapper tail-jumps to. Withdrawn: upstream does not track it, no generator
    # consumes it, the tracker's flat alias map cannot use it without blinding the
    # windows verdict, and the body is reached from at least two wrappers - so
    # naming it after CBaseTrigger was not even accurate.
    ("find-CBaseTrigger_EndTouchInternal-linux", "server", "invented name, no consumer"),
    # A single {platform} declaration task was wrong for this table: these are bare
    # declaration tasks and the name must say which platform the artifact was made
    # for, so the two per-platform entries replace it.
    ("find-CEntityResourceManifest_AddResource", "engine",
     "replaced by the -linux and -windows declaration tasks"),
    # (task_name, module, why)
    # CNetChan has no RTTI in engine2 on either platform, so the single match a
    # 7-byte signature found there was a false positive.
    ("find-CNetChan_ProcessMessages", "engine", "artifact was a false positive"),
]
# Fork-owned platform pins. A symbol that exists on only one platform still gets
# looked up on both, so the absent side logs missing_yaml forever. Pinning is
# upstream's own lever (_target_platforms reads symbol["platform"]).
FORK_OWNED_PLATFORM_PINS = [
    # (symbol_name, module, platform, why)
    # GCC inlines ParseNetadrList into ConnectSocketToAddressList on linux: the
    # linux function at 0x4ac3e0 carries ParseNetadrList's own string literals
    # (' ', 'loopback', ':%d', '%d') inside a body that is otherwise a
    # line-for-line match for windows ConnectSocketToAddressList (same netadr_t
    # clear + CUtlString::Purge prologue, same (a1+9, count) resize helper, same
    # a1[23] = 0xC7EFFFFFE0000000, same netsystem vtable +120/+368/+144, same
    # convar ratio into +43). Confirmed by IDA decompiles of both.
    ("ParseNetadrList", "engine", "windows", "inlined into ConnectSocketToAddressList on linux"),
    # Upstream's label is wrong, so there is no linux call site to find. A headless
    # IDA pass read the registration line straight out of the interface-connect
    # function:
    #     (**v136)(v136, "LegacyGameUI001", qword_180613CA8);
    # and 0x180613ca8 is exactly the receiver of the windows artifact's own call
    # site (0x1800696bd). It is not g_pNetworkSystem (0x180689e80), which dispatches
    # on 34 distinct slots in engine2.dll and 27 in libengine2.so without ever
    # touching 0xb8.
    #
    # The slot map confirms ILegacyGameUI rather than INetworkSystem: 11 from
    # ActivateGameUI(), 13/14 from GameUIService and PanoramaUIStartup, 17 from
    # CEngineGameUI::OnLevelLoadingStarted, 18 from level-loading-finished and
    # Engine2/DisableLoadingPlaque, 21 from "*** Map Load Complete", and 23 from a
    # client disconnect handler ("CL: Disconnected - Client delta ticks out of
    # order!"). So slot 23 is a disconnect notification on the legacy game-UI
    # interface, not RemoveNetChannel.
    #
    # windows-only in every gamever that has it (14172 onward); upstream added the
    # pin itself from 14180, so this only backports it to 14178b
    ("SendViolationReport", "client", "windows", "no linux artifact in any gamever"),
]
# Fork-owned symbol REMOVALS. Upstream declares these, but the binary evidence says
# they cannot be produced, so every run logged a missing_yaml warning and nothing
# ever shipped. sync_upstream.sh resolves config conflicts in upstream's favour, so
# a plain deletion comes back on the next merge.
FORK_OWNED_REMOVALS = [
    # (symbol_name, module, why)
    # The think-function pointer lives at +0x28 in a schema struct that is filled at
    # RUNTIME: there is no .rela.dyn entry and no raw qword anywhere in either binary
    # pointing at the think function, so neither IDA nor a headless pass can read it.
    # No artifact in 14 gamevers and no generator references the key.
    ("g_CCSPlayerController_PlayerForceTeamThink", "server", "runtime-filled pointer"),
    ("g_CCSPlayerController_ResetForceTeamThink", "server", "runtime-filled pointer"),
    ("g_CCSPlayerController_ResourceDataThink", "server", "runtime-filled pointer"),
    ("g_CCSPlayerController_InventoryUpdateThink", "server", "runtime-filled pointer"),
    # Seeded as a vfunc from bot-controller's "offsets" entry whose comment says
    # m_pawn and whose value is the same on both platforms (56) - which rules out a
    # vtable slot, since MSVC shifts them (rule 5). When analysis finally resolved a
    # slot in 14181 the generator, which matches a key to a symbol by folded name,
    # handed 21 to bot-controller and bot-improver for a key they read as a field
    # Same function as CCSPlayer_WeaponServices_DropWeapon - identical func_va on
    # both platforms - so it is a second record for one address, and the generator
    # resolves a key by folded name, meaning whichever record is declared claims
    # bot-controller's vtidx::DropWeapon. The canonical symbol carries the
    # RTTI-confirmed index (linux 29 / windows 28) and now carries the key as an
    # alias, so this record has nothing left to do.
    ("vtidx_DropWeapon", "server", "duplicate of CCSPlayer_WeaponServices_DropWeapon"),
    # Refactored into CEnvHudHint_API::ShowHudHint in 14168 (upstream's own comment
    # on the commented-out find-ShowHudHint task). Kept as a downstream alias on the
    # canonical symbol via ALIAS_OVERRIDES, so the old gamedata key still resolves.
    ("ShowHudHint", "server", "refactored into CEnvHudHint_API_ShowHudHint"),
    # A patch symbol ships nothing without patch_bytes (_load_standard_platform
    # skips the payload), and no gamever in ten has ever had them - the skill says
    # so outright: "No patch_bytes field is generated because this skill
    # identifies the callee call site; the downstream consumer decides how that
    # call instruction is patched." No generator consumes it either.
    #
    # A headless IDA pass settled what the patch would even be for. The site gates
    # this, in C_ServerVoiceHandler::OnServerVoiceData:
    #     if (IsPlayingDemo()) {
    #         if (slot == -1) goto play;
    #         if (!bittest(mask, slot)) return;   // drop this slot's voice
    #     }
    # and the mask is two convars stitched into 64 bits - tv_listen_voice_indices
    # (low) and tv_listen_voice_indices_h (high), confirmed by their registration
    # sites and by the debug string "Voice slot %llu bc: %s heard: %s bitSet: %s".
    # So the behaviour is already runtime-configurable: setting those convars does
    # what neutralising the call would, without patching bytes. The patch has no
    # reason to exist, which is why the declaration is retired here. The find-task
    # and the artifact stay, so the call-site locator survives in the snapshot.
    ("OnServerVoiceData_IsPlayingDemo_Callee", "client", "gate is convar-driven (tv_listen_voice_indices)"),
    # 14178b declares it in both engine and server; the artifact only ever lives in
    # engine, and upstream dropped the server copy from 14180 onward
    ("CServerSideClient_SetName", "server", "stray duplicate; the artifact lives in engine"),
    # Declared by upstream in every config back to 14167, but nothing hunts them and
    # nothing consumes them: no find-task in any module, no reference YAML, no artifact
    # in any gamever, and upstream's own generated gamedata ships none of the three
    # (checked against upstream/main). The only code hit is a synthetic fixture in
    # tests/test_update_gamedata.py, which builds its own config and is unaffected.
    # Retired so missing_report reaches 0 and a future real gap is visible instead of
    # buried under permanent noise.
    ("CNetworkMessages_GetNetworkGroupCount", "networksystem", "never hunted, never shipped"),
    ("CNetworkMessages_GetNetworkGroupName", "networksystem", "never hunted, never shipped"),
    ("CNetworkMessages_GetNetworkGroupColor", "networksystem", "never hunted, never shipped"),
    ("GiveNamedItem2", "server", "address is a sibling overload; the name belongs to CCSPlayer_ItemServices_GiveNamedItem"),
    # Two symbols claimed the single downstream "ClientPrint" key: this one by its own
    # name, and ClientPrintToController through alias: [ClientPrint]. Emission order
    # decided the winner, which is rule 15. A headless IDA pass over libserver.so
    # identified all three candidates in the family (the binary carries real symbol
    # names here, so this is not inference):
    #
    #   0x17c7b30  UTIL_ClientPrintFilter(filter, dest, msg, p1..p4)   size 0xd02
    #   0x17c8840  ClientPrint(pawn, dest, msg, p1..p4)                size 0xf2
    #   0x17c8940  sub_17C8940(controller, dest, msg, p1..p4)          size 0x95
    #
    # ClientPrint reads the handle at pawn+3728, resolves the controller through the
    # entity table, builds a single-recipient filter and forwards to
    # UTIL_ClientPrintFilter. sub_17C8940 skips the pawn step: it passes its pointer
    # straight to the same helper (sub_17BF520), so it takes the CONTROLLER - which is
    # what our ClientPrintToController label already said, and what a managed plugin
    # holds (CCSPlayerController.Handle). A filter, the third variant, cannot be built
    # from managed code at all, so upstream CSS's historical template value pointing
    # there was never usable.
    #
    # So the value already shipping (the controller variant) is the right one for the
    # key, and retiring THIS declaration makes the winner deterministic without
    # changing a byte downstream. The find-task and both artifacts stay as locators.
    #
    # Note for the cs2-signatures tracker: it maps a gamedata key to the snapshot
    # symbol of the same name, so it compares the shipped controller sig against this
    # pawn variant and reports "outdated vs reference". The fix belongs on that side,
    # as one entry in its data/symbol_aliases.json:
    #     "ClientPrint": "ClientPrintToController"
    ("ClientPrint", "server", "key belongs to ClientPrintToController (controller variant; 0x17c8840 takes the pawn)"),
    # Upstream labels engine vfunc slot 0xb8 on the receiver at 0x180613ca8
    # INetworkSystem::RemoveNetChannel. A headless IDA pass read the registration
    # verbatim - (**v136)(v136, "LegacyGameUI001", qword_180613CA8) - and the slot map
    # around it (11 ActivateGameUI, 17 OnLevelLoadingStarted, 18 DisableLoadingPlaque,
    # 21 Map Load Complete, 23 client disconnect) is ILegacyGameUI, not INetworkSystem.
    # The label is therefore wrong, there is no linux counterpart to hunt, and no
    # generator consumes a RemoveNetChannel key at all. The real data already exists as
    # CNetworkSystem_RemoveNetChannel (+ _ByAddress) in networksystem on both platforms.
    # Retired instead of relabelled: upstream's windows artifact stays untouched as a
    # locator, and this stops the linux half being reported as missing forever.
    # Replaces the earlier platform: windows pin, which only hid half the problem.
    ("INetworkSystem_RemoveNetChannel", "engine", "mislabelled ILegacyGameUI slot; real data is CNetworkSystem_RemoveNetChannel"),
]

# Fork-owned symbol MOVES between module blocks. Upstream declares the symbol under a
# module whose binary does not contain the class at all, so the artifact can never be
# found there and the symbol ships nothing.
FORK_OWNED_MOVES = [
    # (symbol_name, from_module, to_module, anchor_in_target, why)
    # CNetChan has zero RTTI strings in engine2 on either platform; it lives only in
    # networksystem, where find-tasks already produce both artifacts. Slot indices also
    # differ per platform there (linux 73/72, windows 72/71), so the engine declaration
    # could not even be filled by copying.
    ("CNetChan_ProcessMessages", "engine", "networksystem",
     "CNetChan_ParseMessagesDemoInternal", "class absent from engine2"),
    ("CNetChan_ParseMessagesDemo", "engine", "networksystem",
     "CNetChan_ParseMessagesDemoInternal", "class absent from engine2"),
    # Upstream declares it under server, but CFlattenedSerializers lives in
    # networksystem: that is where the find-task, both -decompiles reference YAMLs
    # (references/networksystem/) and the artifacts on both platforms actually are,
    # in all three gamevers. The server declaration can never resolve, which is why
    # missing_report listed it. Upstream's ida_analyze_util docstring still uses
    # "../server/CFlattenedSerializers_CreateFieldChangedEventQueue" as its example
    # of the cross-module base_vfunc_name syntax - that example is where the stale
    # module came from, and no preprocessor uses that path.
    ("CFlattenedSerializers_CreateFieldChangedEventQueue", "server", "networksystem",
     "CFlattenedSerializers_vtable", "class lives in networksystem"),
]

# Fork-owned bare optional_output tasks. These declare artifacts recovered headlessly
# for a platform/module upstream never analysed; without a declaring task
# gamesymbol_snapshot drops the artifact as "undeclared" and the warning returns.
# optional_output (not expected_output) is the correct lever: expected_output makes the
# path REQUIRED and pack then fails with "Missing required symbol YAML".
FORK_OWNED_OPTIONAL_TASKS = [
    # (task_name, module, artifact_path)
    # One entry per platform, not one {platform} entry: every task in this table is a
    # bare DECLARATION task - no preprocessor, no platform: key - existing only so
    # gamesymbol_snapshot does not drop the artifact as undeclared. The name says
    # which platform the artifact was actually produced for, and the path is that
    # platform's literal filename. (Upstream's real hunting tasks are the other
    # shape: a platform: key on the task plus X.{platform}.yaml in the output, where
    # {platform} is expanded to the platform being analysed.)
    #
    # CEntityResourceManifest::AddResource is an OFFSETS entry in CounterStrikeSharp
    # (linux 0, windows 2) that CSS core reads through GetOffset. Both halves are now
    # verified against their own platform's own vtable, as rule 13 requires.
    #
    # linux:   Itanium RTTI -> one 12-slot vtable at 0x9a4000.
    # windows: MSVC RTTI -> .?AVCEntityResourceManifest@@ at 0x180629b18, its
    #          TypeDescriptor at -0x10, one CompleteObjectLocator at 0x1805a9dd0,
    #          vftable at 0x1805708a8 - also 12 slots, so there is no dtor-pair shift
    #          for this class.
    #
    # Slots 0-2 are the three default-argument overloads of AddResource on both
    # platforms, all reaching one implementation (linux tail-jumps to 0x3ce5c0,
    # windows calls 0x1801ada00). The pairing is fixed by the defaulting ladder, not
    # by the usual MSVC shift: the maximally-defaulted overload - the one taking only
    # the resource name - is linux slot 0 (xor r8d/r9d/ecx/edx) and windows slot 2
    # (xor r9d, [rsp+0x20]=0, xor r8d). GCC and MSVC emit the overloads in opposite
    # order, which is exactly why the indices are 0 and 2.
    ("find-CEntityResourceManifest_AddResource-linux", "engine",
     "CEntityResourceManifest_AddResource.linux.yaml"),
    ("find-CEntityResourceManifest_AddResource-windows", "engine",
     "CEntityResourceManifest_AddResource.windows.yaml"),
    ("find-INetworkSystem_CloseSocket-linux", "engine", "INetworkSystem_CloseSocket.linux.yaml"),
    ("find-INetworkSystem_EnableLoopbackBetweenSockets-linux", "engine",
     "INetworkSystem_EnableLoopbackBetweenSockets.linux.yaml"),
    ("find-INetworkSystem_ConnectSocket-linux", "engine", "INetworkSystem_ConnectSocket.linux.yaml"),
    ("find-INetworkSystem_PollSocket-linux", "engine", "INetworkSystem_PollSocket.linux.yaml"),
    ("find-ConnectSocketToAddressList-linux", "engine", "ConnectSocketToAddressList.linux.yaml"),
    ("find-CGameSystemReallocatingFactory_CSource2EntitySystem_CreateGameSystem-server", "server",
     "CGameSystemReallocatingFactory_CSource2EntitySystem_CreateGameSystem.{platform}.yaml"),
    ("find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem-linux", "server",
     "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem.linux.yaml"),
    ("find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_vtable-server", "server",
     "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_vtable.{platform}.yaml"),
    ("find-CEnvHudHint_API_ShowHudHint-binding", "server",
     "CEnvHudHint_API_ShowHudHint.{platform}.yaml"),
    ("find-CCSPlayer_MovementServices_WaterMove-verified", "server",
     "CCSPlayer_MovementServices_WaterMove.{platform}.yaml"),
    # upstream declares the symbol but ships no task for it, so the artifact was
    # dropped as undeclared on every gamever that has one
    ("find-CCSPlayerController_HandleCommand_JoinTeam-local", "server",
     "CCSPlayerController_HandleCommand_JoinTeam.{platform}.yaml"),
    # cross-module relocations: the symbol is declared for this module too, but only
    # the other module was ever analysed, so the artifact had no declaring task here
    ("find-g_pGameEntitySystem", "client", "g_pGameEntitySystem.{platform}.yaml"),
    ("find-g_pGameResourceService", "client", "g_pGameResourceService.{platform}.yaml"),
    ("find-IGameResourceService_SetEntityResourceManifestHandler", "client",
     "IGameResourceService_SetEntityResourceManifestHandler.{platform}.yaml"),
    ("find-IGameSystemFactory_SetGlobalPtr", "server",
     "IGameSystemFactory_SetGlobalPtr.{platform}.yaml"),
    ("find-IGameSystem_SetGameSystemGlobalPtrs", "server",
     "IGameSystem_SetGameSystemGlobalPtrs.{platform}.yaml"),
    ("find-IGameSystem_vdtor", "server", "IGameSystem_vdtor.{platform}.yaml"),
    ("find-CNetworkGameServerBase_IsBackgroundMap", "server",
     "CNetworkGameServerBase_IsBackgroundMap.{platform}.yaml"),
    ("find-CEntityInstance_PreDataUpdate", "server",
     "CEntityInstance_PreDataUpdate.{platform}.yaml"),
    ("find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem", "server",
     "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem.windows.yaml"),
]


def _module_blocks(lines):
    """(start, end, name) for every top-level module block."""
    starts = [(i, l[len("  - name: "):]) for i, l in enumerate(lines)
              if l.startswith("  - name: ") and l.count(":") == 1]
    return [(st, starts[k + 1][0] if k + 1 < len(starts) else len(lines), name)
            for k, (st, name) in enumerate(starts)]


def _symbol_block(lines, start, end, symbol):
    """(from, to) line range of a symbol entry and its attributes, or None."""
    try:
        at = next(i for i in range(start, end) if lines[i] == f"      - name: {symbol}")
    except StopIteration:
        return None
    to = at + 1
    while to < end and lines[to].startswith("        "):
        to += 1
    return at, to


def enforce_fork_owned_obsolete_tasks(text):
    """Drop task declarations whose artifact was withdrawn."""
    dropped = 0
    lines = text.split("\n")
    for task, module, _why in FORK_OWNED_OBSOLETE_TASKS:
        for start, end, name in _module_blocks(lines):
            if name != module:
                continue
            try:
                at = next(i for i in range(start, end) if lines[i] == f"      - name: {task}")
            except StopIteration:
                continue
            to = at + 1
            while to < end and lines[to].startswith("        "):
                to += 1
            del lines[at:to]
            dropped += 1
            break
    return "\n".join(lines), dropped


def enforce_fork_owned_platform_pins(text):
    """Re-assert single-platform pins on symbols the other platform cannot have."""
    pinned = 0
    lines = text.split("\n")
    for symbol, module, platform, _why in FORK_OWNED_PLATFORM_PINS:
        for start, end, name in _module_blocks(lines):
            if name != module:
                continue
            span = _symbol_block(lines, start, end, symbol)
            if span is None:
                continue
            at, to = span
            if any(l.strip() == f"platform: {platform}" for l in lines[at:to]):
                break
            # replace a wrong pin, otherwise insert right after the category line
            wrong = next((i for i in range(at, to) if lines[i].strip().startswith("platform:")), None)
            if wrong is not None:
                lines[wrong] = f"        platform: {platform}"
            else:
                cat = next((i for i in range(at, to) if lines[i].strip().startswith("category:")), at)
                lines[cat + 1:cat + 1] = [f"        platform: {platform}"]
            pinned += 1
            break
    return "\n".join(lines), pinned


def enforce_fork_owned_removals(text):
    """Drop declarations the binary evidence says can never be produced."""
    removed = 0
    lines = text.split("\n")
    for symbol, module, _why in FORK_OWNED_REMOVALS:
        for start, end, name in _module_blocks(lines):
            if name != module:
                continue
            span = _symbol_block(lines, start, end, symbol)
            if span is None:
                continue
            del lines[span[0]:span[1]]
            removed += 1
            break
    return "\n".join(lines), removed


def enforce_fork_owned_alias_removals(text):
    """Stop a symbol claiming a downstream key that means something else."""
    removed = 0
    lines = text.split("\n")
    for symbol, aliases in FORK_OWNED_ALIAS_REMOVALS.items():
        wanted = {f"- {alias}" for alias in aliases}
        for start, end, _name in _module_blocks(lines):
            span = _symbol_block(lines, start, end, symbol)
            if span is None:
                continue
            block = [l for l in lines[span[0]:span[1]] if l.strip() not in wanted]
            dropped = (span[1] - span[0]) - len(block)
            if not dropped:
                break
            # An "alias:" key with nothing under it is not valid for load_config,
            # so it goes when its last entry does.
            cleaned = [l for i, l in enumerate(block)
                       if l.strip() != "alias:"
                       or (i + 1 < len(block) and block[i + 1].strip().startswith("- "))]
            lines[span[0]:span[1]] = cleaned
            removed += dropped
            break
    return "\n".join(lines), removed


def enforce_fork_owned_moves(text):
    """Move a declaration to the module whose binary actually holds the class."""
    moved = 0
    for symbol, src, dst, anchor, _why in FORK_OWNED_MOVES:
        lines = text.split("\n")
        blocks = _module_blocks(lines)
        # already in the target?
        if any(name == dst and _symbol_block(lines, st, en, symbol)
               for st, en, name in blocks):
            continue
        span = src_span = None
        for st, en, name in blocks:
            if name == src:
                span = _symbol_block(lines, st, en, symbol)
                if span:
                    src_span = span
                    break
        if not src_span:
            continue
        block = lines[src_span[0]:src_span[1]]
        del lines[src_span[0]:src_span[1]]
        blocks = _module_blocks(lines)
        target = None
        for st, en, name in blocks:
            if name != dst:
                continue
            a = _symbol_block(lines, st, en, anchor)
            if a:
                target = a[1]
                break
        if target is None:
            continue  # anchor gone - leave the config untouched rather than guess
        lines[target:target] = block
        text = "\n".join(lines)
        moved += 1
    return text, moved


def enforce_fork_owned_optional_tasks(text):
    """Re-insert the bare optional_output tasks that declare recovered artifacts."""
    added = 0
    lines = text.split("\n")
    for task, module, path in FORK_OWNED_OPTIONAL_TASKS:
        for start, end, name in _module_blocks(lines):
            if name != module:
                continue
            # scope the presence check to THIS module: the same task name also exists
            # in another module with expected_output, and a global check skipped three
            # server tasks that upstream declares only for client.
            try:
                have = next(i for i in range(start, end) if lines[i] == f"      - name: {task}")
            except StopIteration:
                have = None
            if have is not None:
                # present, but possibly narrower than we need (upstream ships
                # g_pGameEntitySystem.windows.yaml; the linux artifact now exists too)
                to = have + 1
                while to < end and lines[to].startswith("        "):
                    to += 1
                if any(l.strip() == f"- {path}" for l in lines[have:to]):
                    break
                if not any(l.strip() == "optional_output:" for l in lines[have:to]):
                    break  # a real find-task with expected_output - leave it alone
                lines[have:to] = [f"      - name: {task}", "        optional_output:",
                                  f"          - {path}"]
                added += 1
                break
            try:
                at = next(i for i in range(start, end) if lines[i] == "    skills:")
            except StopIteration:
                continue
            lines[at + 1:at + 1] = [f"      - name: {task}",
                                    "        optional_output:",
                                    f"          - {path}"]
            added += 1
            break
    return "\n".join(lines), added


def newest_config():
    candidates = glob.glob("configs/*.yaml")
    numeric = [c for c in candidates if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
    if not numeric:
        return None

    def sort_key(path):
        # gamever first as a number, then the optional letter suffix - sorting on
        # path length instead makes 14178b (19 chars) outrank 14181 (18 chars)
        m = re.fullmatch(r"configs/(\d+)([a-z]?)\.yaml", path)
        return (int(m.group(1)), m.group(2))

    return max(numeric, key=sort_key)


def load_seed_specs():
    """Derive (symbol_name, category, struct, member, alias, lib) for every seed entry."""
    specs = []
    for seed in SEEDS:
        if not os.path.exists(seed):
            print(f"  warning: seed missing, skipping: {seed}")
            continue
        with open(seed, "r", encoding="utf-8") as f:
            gamedata = json.load(f)
        for key, entry in gamedata.items():
            if key in ALIAS_OVERRIDES:
                # alias: kanon-symbolet er allerede i configen (upstream-ejet) -
                # generatoren resolver via aliaset, ingen separat injektion noedvendig
                continue
            symbol_name = ALIAS_OVERRIDES.get(key, key.replace("::", "_"))
            alias = key if key != symbol_name else None
            lib = (entry.get("signatures", {}) or {}).get("library") or entry.get("library")
            if "signatures" in entry:
                specs.append((symbol_name, "func", None, None, alias, lib))
                continue
            cls, _, method = key.partition("::")
            if method.startswith("m_"):
                specs.append((symbol_name, "structmember", cls, method, alias, lib))
            elif symbol_name.startswith("BuyState_") and symbol_name[len("BuyState_"):] in BUYSTATE_MEMBERS:
                # BuyState er en non-polymorphic POD - offset-entries er structmembers
                # (kilde-kommentarer: m_doneBuying / m_isInitialDelay).
                specs.append((symbol_name, "structmember", "BuyState",
                              BUYSTATE_MEMBERS[symbol_name[len("BuyState_"):]], alias, lib))
            elif cls in ("CEntityIdentity", "CMoveData") and method:
                # layout-holder-klasser: offset-entries er structmembers (agent-verificeret 14178b)
                specs.append((symbol_name, "structmember", cls, method, alias, lib))
            elif symbol_name.startswith("BotProfile_") and symbol_name[len("BotProfile_"):] in BOTPROFILE_MEMBERS:
                # BotProfile er en non-polymorphic POD - offset-entries er structmembers
                # (IDA-verificeret 14178b: m_attackDelay +0x5C; Bot-Improver reference).
                specs.append((symbol_name, "structmember", "BotProfile",
                              BOTPROFILE_MEMBERS[symbol_name[len("BotProfile_"):]], alias, lib))
            elif cls and method and re.fullmatch(r"m_[A-Za-z0-9_]+", (entry.get("comment") or "").strip()):
                # An offsets entry whose comment names an m_* member is a struct
                # field, and the plugins say so twice: in the comment, and by
                # carrying the SAME number on both platforms, which a vtable slot
                # cannot do because MSVC shifts slots (rule 5).
                #
                # This branch used to skip such a key outright, because the
                # generator resolves a key to a symbol by FOLDED NAME rather than
                # by the config alias - CCSPlayer_MovementServices::Pawn and
                # CCSPlayer_MovementServices_Pawn fold to the same string - so a
                # symbol seeded here under the wrong category claims the key
                # whether it is aliased or not. Seeding one as a vfunc is how
                # 14181 came to ship slot 21 against the plugins' own 56.
                #
                # structmember is the truthful category, and the offset is now
                # verified: CCSPlayer_MovementServices' own PlayerRunCommand slot
                # calls an accessor that reads the member directly -
                # linux 0x179b460 "mov rax,[rdi+0x38]" and windows 0x180c36380
                # "mov rax,[rcx+0x38]", each followed by a CHandle load at a
                # DIFFERENT offset per platform (0xE90 vs 0xBB0), which is what a
                # real field on two compilers looks like.
                #
                # This generalises BUYSTATE_MEMBERS and BOTPROFILE_MEMBERS above,
                # which hand-maintain the same mapping for fourteen keys. Measured
                # over all four seed files, exactly one key reaches this branch
                # today; the tables keep the ones they already cover.
                specs.append((symbol_name, "structmember", cls, entry["comment"].strip(), alias, lib))
            else:
                specs.append((symbol_name, "vfunc", None, None, alias, lib))
    return specs


def find_task_block(symbol_name):
    return (
        f"      - name: find-{symbol_name}\n"
        f"        expected_output:\n"
        f"          - {symbol_name}.{{platform}}.yaml\n"
    )


def symbol_entry_block(symbol_name, category, struct, member, alias):
    lines = [f"      - name: {symbol_name}", f"        category: {category}"]
    if category == "structmember":
        lines.append(f"        struct: {struct}")
        lines.append(f"        member: {member}")
    if alias:
        lines.append("        alias:")
        lines.append(f"          - {alias}")
    return "".join(line + "\n" for line in lines)


def struct_entry_block(struct):
    return f"      - name: {struct}\n        category: struct\n"


def write_skill(symbol_name, category, struct, alias, member=""):
    display = alias or symbol_name
    if category == "func":
        kind_hint = (
            f"The gamedata consumer stores a BYTE SIGNATURE for this entry - ALWAYS emit the func\n"
            f"schema (func_sig), never vfunc fields. The function may be virtual; locating it via\n"
            f"the owning class vtable (RTTI) is a fine strategy, but once found, read its head bytes\n"
            f"and emit func_sig. Locate via cross-references, distinctive constants/strings, callers\n"
            f"of related symbols, or vtable slots; verify by decompilation before committing."
        )
        output = (
            "Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:\n"
            "```yaml\n"
            "func_name: <SYMBOL_NAME>\n"
            "func_va: \"<hex virtual address>\"\n"
            "func_rva: \"<hex rva>\"\n"
            "func_size: \"<hex size>\"\n"
            "func_sig: \"<byte pattern, ?? wildcards, function head, minimal-unique>\"\n"
            "```\n"
            "NEVER include vfunc_index, vfunc_offset, vfunc_sig or vtable_name."
        )
    elif category == "vfunc":
        kind_hint = (
            f"This gamedata entry is stored as an OFFSET. Determine TRUTHFULLY which of the two\n"
            f"it is: (a) a vtable slot of a POLYMORPHIC class (RTTI/vtable present) -> emit the\n"
            f"vfunc schema, or (b) a plain struct member of a NON-POLYMORPHIC class (no RTTI/vtable;\n"
            f"e.g. config-style POD structs like BotProfile) -> emit the structmember schema.\n"
            f"Never guess: if no vtable exists for the class, it is case (b)."
        )
        output = (
            "Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:\n"
            "```yaml\n"
            "func_name: <SYMBOL_NAME>\n"
            "func_va: \"<hex virtual address>\"\n"
            "func_rva: \"<hex rva>\"\n"
            "func_size: \"<hex size>\"\n"
            "vtable_name: <owning class RTTI name>\n"
            "vfunc_offset: \"<hex vtable byte offset>\"\n"
            "vfunc_index: <decimal slot index>\n"
            "```\n"
            "NEVER include func_sig."
        )
    else:
        kind_hint = (
            f"This is a STRUCT MEMBER OFFSET (schema netvar), not a function. Resolve the\n"
            f"{struct} class layout via the schema/network system; the member must satisfy\n"
            f"natural alignment. Cross-check with functions that dereference the member.\n"
            f"Do not switch output schema: emit the structmember fields below even if the\n"
            f"class turns out to be polymorphic - a func_*/vfunc_* payload for this symbol\n"
            f"is rejected by canonical_symbol_yaml_bytes."
        )
        output = (
            "Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:\n"
            "```yaml\n"
            f"struct_name: {struct}\n"
            f"member_name: {member}\n"
            "offset: \"<hex byte offset as string>\"\n"
            "size: <member size in bytes, decimal>\n"
            "offset_sig: \"<short byte pattern of an instruction touching the offset>\"\n"
            "```\n"
            "NEVER include func_* or vfunc_* fields."
        )

    skill_dir = os.path.join(SKILLS_DIR, f"find-{symbol_name}")
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(skill_path):
        return
    os.makedirs(skill_dir, exist_ok=True)
    # continuation lines must stay inside the "description: |" block scalar - at
    # column 0 they terminate it and the frontmatter stops being valid YAML
    kind_hint_indented = kind_hint.replace("\n", "\n  ")
    body = f"""---
name: find-{symbol_name}
description: |
  Locate {display} in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the local gamedata entry "{display}" (symbol {symbol_name}). {kind_hint_indented}
  Trigger: {symbol_name}, {display}
disable-model-invocation: true
---

# Find {symbol_name}

Target: `{display}` ({category}) in the CS2 server module.

> Do NOT anchor on raw byte patterns from older releases - they shift. Use anchors only to *locate*
> the function, then generate a fresh minimal-unique function-head signature with relocated bytes
> wildcarded. Produce ONLY the output file(s) listed in this skill's expected outputs, for the binary
> loaded in THIS session (one platform per run). NEVER open or analyze the other platform's binary.

## Method

{kind_hint}

## Mandatory self-check before emitting

The pipeline re-reads the bytes at your `func_va` and deterministically regenerates `func_sig` from
them - if your `func_sig` does not match those bytes EXACTLY (with `??` matching anything), the run
aborts. Therefore:

1. After picking the function, read the actual bytes at `func_va` via the IDA MCP.
2. Derive `func_sig` FROM those bytes: keep stable opcode bytes literally, wildcard relocated or
   variable operands as `??`.
3. `func_sig` MUST start at `func_va` (the true function head).
4. Only then write the YAML. A mismatch is always a bug in YOUR output, never in the pipeline.

## Output schema (STRICT)

{output}

## Verification

1. Decompile the candidate and confirm the behavior matches the purpose above (not a caller or callee).
2. Confirm uniqueness: the generated pattern must match exactly one location in the loaded binary.
3. If a candidate cannot be confirmed, report the shortlist instead of guessing - a skipped symbol is
   safer than a wrong signature.
"""
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(body)


LIB_MODULE = {"server": "server", "engine2": "engine", "engine": "engine", "client": "client"}
ENGINE_CLASSES = (
    "CNetworkGameServerBase", "CNetworkGameServer", "CServerSideClient",
    "CServerSideClientBase", "CGameEntitySystem",
)


def module_for(lib, symbol_name):
    if lib and lib in LIB_MODULE:
        return LIB_MODULE[lib]
    if symbol_name.startswith(ENGINE_CLASSES):
        return "engine"
    return "server"


def enforce_category_decisions(text):
    """Re-assert CATEGORY_DECISIONS on symbols already declared in the config.

    inject() skips any symbol whose name is already present, so a symbol declared
    with the wrong category stays wrong - and an upstream merge reintroduces it
    because sync_upstream.sh takes upstream's side on config conflicts.
    """
    changed = 0
    result = text
    for name, (category, struct, member) in CATEGORY_DECISIONS.items():
        pattern = re.compile(
            r"^      - name: " + re.escape(name) + r"\n"
            r"((?:        \S[^\n]*\n|          [^\n]*\n)*)",
            re.M,
        )
        for m in reversed(list(pattern.finditer(result))):
            attrs = m.group(1)
            # keep the alias block (and anything else that is not category/struct/member)
            kept, skipping = [], False
            for line in attrs.splitlines(keepends=True):
                if line.startswith("        "):
                    key = line.strip().split(":", 1)[0]
                    skipping = key in ("category", "struct", "member")
                    if skipping:
                        continue
                elif skipping:
                    continue  # nested list under a dropped key
                kept.append(line)
            rebuilt = f"        category: {category}\n"
            if struct:
                rebuilt += f"        struct: {struct}\n"
            if member:
                rebuilt += f"        member: {member}\n"
            rebuilt += "".join(kept)
            if rebuilt == attrs:
                continue
            result = result[:m.start()] + f"      - name: {name}\n" + rebuilt + result[m.end():]
            changed += 1
    return result, changed


def enforce_fork_owned_tasks(text):
    """Re-insert fork-owned find-tasks, each anchored before a known task.

    Runs to a fixed point: one entry's anchor can be another entry's task, so a
    single pass in list order silently skips whichever comes first (the
    FullWalkMove task anchors on the SpeedClamp task). Looping until nothing
    changes makes the order of FORK_OWNED_TASKS irrelevant.
    """
    total = 0
    while True:
        text, added = _enforce_fork_owned_tasks_once(text)
        total += added
        if not added:
            return text, total


def _enforce_fork_owned_tasks_once(text):
    added = 0
    lines = text.split("\n")
    module_starts = [(i, l[len("  - name: "):]) for i, l in enumerate(lines)
                     if l.startswith("  - name: ") and l.count(":") == 1]
    for symbol, module, anchor in FORK_OWNED_TASKS:
        task = f"      - name: find-{symbol}"
        if task in lines:
            continue
        # the module block that declares the symbol
        target = None
        for k, (start, name) in enumerate(module_starts):
            if name != module:
                continue
            end = module_starts[k + 1][0] if k + 1 < len(module_starts) else len(lines)
            if f"      - name: {symbol}" in lines[start:end]:
                target = (start, end)
                break
        if target is None:
            continue  # symbol not declared (yet) - inject() may add it below
        start, end = target
        try:
            at = next(i for i in range(start, end) if lines[i] == f"      - name: {anchor}")
        except StopIteration:
            continue  # anchor not present (yet) - a later round may restore it
        # optional_output, not expected_output: expected makes the path REQUIRED and
        # pack then dies with "Missing required symbol YAML" on any gamever where the
        # artifact has not been recovered yet - which is what happened the moment
        # these tasks were re-asserted onto 14180 and 14178b. Optional still declares
        # the artifact, so it is packed wherever it does exist.
        lines[at:at] = [task, "        optional_output:", f"          - {symbol}.{{platform}}.yaml"]
        module_starts = [(i, l[len("  - name: "):]) for i, l in enumerate(lines)
                         if l.startswith("  - name: ") and l.count(":") == 1]
        added += 1
    return "\n".join(lines), added


def enforce_alias_overrides(text):
    """Ensure every ALIAS_OVERRIDES key is an alias on its canonical symbol.

    load_seed_specs() skips these keys on the assumption that the canonical
    symbol already carries the alias, which is how the generator resolves the
    plugin's gamedata key. An upstream merge dropped all four from 14180 and
    14181, so e.g. "CCSPlayer_WeaponServices::GetSlot" resolved to "no matching
    YAML data" and shipped a stale signature even though the artifact was there.
    """
    added = 0
    lines = text.split("\n")
    for key, canon in ALIAS_OVERRIDES.items():
        # locate the canonical symbol entry and the extent of its attributes
        try:
            start = next(i for i, l in enumerate(lines) if l == f"      - name: {canon}")
        except StopIteration:
            continue
        end = start + 1
        while end < len(lines) and (lines[end].startswith("        ") or lines[end].startswith("          ")):
            end += 1
        block = lines[start:end]
        if any(l.strip() == f"- {key}" for l in block):
            continue
        alias_at = next((i for i, l in enumerate(block) if l == "        alias:"), None)
        if alias_at is None:
            block.append("        alias:")
            block.append(f"          - {key}")
        else:
            insert = alias_at + 1
            while insert < len(block) and block[insert].startswith("          - "):
                insert += 1
            block.insert(insert, f"          - {key}")
        lines[start:end] = block
        added += 1
    return "\n".join(lines), added


def repair_missing_structs(text):
    """Ensure every structmember's struct is declared (category: struct) in its module.

    Manual vfunc->structmember reclassifications bypass inject()'s struct tracking;
    update_gamedata refuses configs where a structmember references an undeclared
    struct. This pass self-heals any such state.
    """
    mm = list(re.finditer(r"^  - name: (\w+)", text, re.M))
    result = text
    added = 0
    for i, m in enumerate(mm):
        end = mm[i + 1].start() if i + 1 < len(mm) else len(text)
        block = result[m.start():end] if i == 0 else None
    # process bottom-up so offsets stay valid
    blocks = []
    for i, m in enumerate(mm):
        end = mm[i + 1].start() if i + 1 < len(mm) else len(result)
        blocks.append((m.group(1), m.start(), end))
    for mod, start, end in reversed(blocks):
        block = result[start:end]
        members = re.findall(r"^      - name: (\S+)\n        category: structmember\n        struct: (\S+)", block, re.M)
        structs = set(re.findall(r"^      - name: (\S+)\n        category: struct\n", block, re.M))
        missing = sorted({s for _, s in members if s not in structs})
        if not missing:
            continue
        sm = re.search(r"^    symbols:\n", block, re.M)
        if not sm:
            continue
        decls = "".join(f"      - name: {s}\n        category: struct\n" for s in missing)
        block = block[:sm.end()] + decls + block[sm.end():]
        result = result[:start] + block + result[end:]
        added += len(missing)
    return result, added


def inject(text, config_path, specs):
    """Inject specs into the module matching each symbol's library (server/engine/...)."""
    module_matches = list(re.finditer(r"^  - name: ([\w]+)", text, re.M))
    blocks = []  # (name, block_text, start, end)
    for i, m in enumerate(module_matches):
        end = module_matches[i + 1].start() if i + 1 < len(module_matches) else len(text)
        blocks.append((m.group(1), text[m.start():end], m.start(), end))

    new_tasks, new_symbols, new_structs, touched = {}, {}, {}, set()
    for symbol_name, category, struct, member, alias, lib in specs:
        module = module_for(lib, symbol_name)
        block_text = next(btext for name, btext, s, e in blocks if name == module)
        if f"- name: {symbol_name}\n" in block_text:
            continue
        new_tasks.setdefault(module, []).append(find_task_block(symbol_name))
        new_symbols.setdefault(module, []).append(symbol_entry_block(symbol_name, category, struct, member, alias))
        if struct and f"- name: {struct}\n" not in block_text:
            new_structs.setdefault(module, []).append(struct)
        write_skill(symbol_name, category, struct, alias, member)
        touched.add(module)

    if not touched:
        print(f"  already present: {config_path}")
        return text

    result = text
    for module in sorted(touched):
        btext, m_start, m_end = next((bt, s, e) for name, bt, s, e in blocks if name == module)
        block = result[m_start:m_end]
        skills_match = re.search(r"^    skills:\n", block, re.M)
        symbols_match = re.search(r"^    symbols:\n", block, re.M)
        if not skills_match or not symbols_match:
            print(f"  warning: module {module} mangler skills:/symbols: - skipper")
            continue
        # dict.fromkeys: one declaration per struct, not one per member - appending
        # per spec emitted 12 identical BotProfile entries (one for each member),
        # which update_gamedata rejects as "duplicate symbol in module stage N"
        struct_blocks = [struct_entry_block(s) for s in sorted(dict.fromkeys(new_structs.get(module, [])))]
        block = (
            block[: skills_match.end()]
            + "".join(new_tasks[module])
            + block[skills_match.end(): symbols_match.end()]
            + "".join(struct_blocks)
            + "".join(new_symbols[module])
            + block[symbols_match.end():]
        )
        result = result[:m_start] + block + result[m_end:]
        print(f"  {module}: +{len(new_tasks[module])} task(s), +{len(new_symbols[module])} symbol(s)")

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-config", help="analysis config path (default: newest configs/<GAMEVER>.yaml)")
    args = parser.parse_args()

    config_path = args.config or newest_config()
    if not config_path or not os.path.exists(config_path):
        print(f"  warning: no analysis config to patch ({config_path}); skipping")
        return

    specs = load_seed_specs()
    specs += [(name, category, None, None, alias, lib) for name, category, lib, alias in FORK_OWNED_SYMBOLS]

    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()

    patched, reclassified = enforce_category_decisions(text)
    if reclassified:
        print(f"  re-asserted: {reclassified} fork-owned category decision(s)")
    patched, aliased = enforce_alias_overrides(patched)
    if aliased:
        print(f"  re-asserted: {aliased} alias-override mapping(s)")
    patched, unaliased = enforce_fork_owned_alias_removals(patched)
    if unaliased:
        print(f"  re-asserted: {unaliased} downstream key(s) taken off the wrong symbol")
    patched, removed = enforce_fork_owned_removals(patched)
    if removed:
        print(f"  removed: {removed} unproducible upstream declaration(s)")
    patched, moved = enforce_fork_owned_moves(patched)
    if moved:
        print(f"  moved: {moved} declaration(s) to the module holding the class")
    patched, dropped = enforce_fork_owned_obsolete_tasks(patched)
    if dropped:
        print(f"  dropped: {dropped} obsolete task declaration(s)")
    patched, pinned = enforce_fork_owned_platform_pins(patched)
    if pinned:
        print(f"  re-asserted: {pinned} single-platform pin(s)")
    patched, opt_tasked = enforce_fork_owned_optional_tasks(patched)
    if opt_tasked:
        print(f"  re-asserted: {opt_tasked} fork-owned optional_output task(s)")
    patched, repaired = repair_missing_structs(patched)
    if repaired:
        print(f"  repaired: {repaired} missing struct declaration(s)")
    patched = inject(patched, config_path, specs)
    # after inject(), so a symbol it just declared can anchor its own task
    patched, tasked = enforce_fork_owned_tasks(patched)
    if tasked:
        print(f"  re-asserted: {tasked} fork-owned find-task(s)")
    # Again, because inject() runs after the first pass and adds a find-<symbol>
    # task for every symbol it declares. For a symbol whose declaration this fork
    # has deliberately reshaped - CEntityResourceManifest_AddResource is declared
    # by two per-platform tasks, not one {platform} task - the first pass dropped
    # the generic task and inject() put it straight back. The table means the task
    # must not exist, which one pass before inject cannot guarantee.
    patched, dropped_again = enforce_fork_owned_obsolete_tasks(patched)
    if dropped_again:
        print(f"  dropped after inject: {dropped_again} obsolete task declaration(s)")
        dropped += dropped_again
    if (patched == text and not repaired and not reclassified and not aliased
            and not tasked and not removed and not moved and not opt_tasked
            and not pinned and not dropped):
        return

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"  updated: {config_path}")


if __name__ == "__main__":
    main()
