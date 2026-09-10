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
}


# Fork-owned OBSOLETE tasks: declarations for artifacts that turned out to be wrong.
FORK_OWNED_OBSOLETE_TASKS = [
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
    # No linux call site exists to record. g_pNetworkSystem dispatches on 34 distinct
    # slots in engine2.dll and 27 in libengine2.so, and 0xb8 is in neither set. The
    # windows artifact's own call site (0x1800696bd) receives from 0x180613ca8, not
    # from g_pNetworkSystem (0x180689e80): that global is registered in the
    # Source2Engine interface family between "Source2EngineToClient001" and
    # "Source2EngineToServer001", and every function loading it deals with level
    # loading ("*** Map Load Complete", "OnEngineLevelLoadingStarted",
    # "Engine2/DisableLoadingPlaque", "ActivateGameUI()"). So the recorded receiver
    # is an engine service, and the INetworkSystem label does not match it - which
    # makes a hunt for a linux counterpart a hunt for something that is not there.
    # Nothing consumes the symbol and it ships nothing, so windows keeps what it has
    # always had and linux stops being reported as missing.
    ("INetworkSystem_RemoveNetChannel", "engine", "windows",
     "no linux call site; windows receiver is an engine service, not INetworkSystem"),
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
]

# Fork-owned bare optional_output tasks. These declare artifacts recovered headlessly
# for a platform/module upstream never analysed; without a declaring task
# gamesymbol_snapshot drops the artifact as "undeclared" and the warning returns.
# optional_output (not expected_output) is the correct lever: expected_output makes the
# path REQUIRED and pack then fails with "Missing required symbol YAML".
FORK_OWNED_OPTIONAL_TASKS = [
    # (task_name, module, artifact_path)
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
    if (patched == text and not repaired and not reclassified and not aliased
            and not tasked and not removed and not moved and not opt_tasked
            and not pinned and not dropped):
        return

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"  updated: {config_path}")


if __name__ == "__main__":
    main()
