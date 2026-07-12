# Validation Failures — 2026-07-10

## find-CBaseFilter_InputTestActivator_Register  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBaseFilter_InputTestActivator_Register
      Preprocess: CBaseFilter_InputTestActivator_Register.windows.yaml func_sig matched 0 (need 1)
      Preprocess: trying func_xrefs fallback for CBaseFilter_InputTestActivator_Register
      Preprocess: undefined func recovery skipped: no_entry
      Preprocess: empty candidate set for string xref: FULLMATCH:InputTestActivator
      Preprocess: failed to locate CBaseFilter_InputTestActivator_Register
    Preprocess failed: find-CBaseFilter_InputTestActivator_Register; falling back to AGENT SKILL
    Processing skill: find-CBaseFilter_InputTestActivator_Register
      Falling back to: .claude\skills\find-CBaseFilter_InputTestActivator_Register\SKILL.md
      Error: Skill file not found: .claude\skills\find-CBaseFilter_InputTestActivator_Register\SKILL.md
      Failed

Diagnosis: the existing `func_sig` for `CBaseFilter_InputTestActivator_Register` no longer matches (0 matches, need 1)
on this game version. The func_xrefs fallback (string xref `FULLMATCH:InputTestActivator`) also came back with an
empty candidate set, meaning that string is no longer present/matched in this binary either — the string itself
likely changed or was removed. There is no agent-fallback
`.claude\skills\find-CBaseFilter_InputTestActivator_Register\SKILL.md` to catch this case. Needs either a new
anchor (updated string/signature) or an authored fallback SKILL.md. Note: `find-CBaseFilter_InputTestActivator`
declares `expected_input_windows: CBaseFilter_InputTestActivator_Register.{platform}.yaml`, so it will likely
cascade-fail next unless that output already exists on disk.

## find-CBaseFilter_InputTestActivator  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBaseFilter_InputTestActivator
    Failed: find-CBaseFilter_InputTestActivator (missing expected_input: CBaseFilter_InputTestActivator_Register.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CBaseFilter_InputTestActivator_Register` above — its
`expected_input_windows` entry can no longer be satisfied. Not an independent bug; re-enable once the producer
skill is fixed.

## find-CBasePlayerController_Respawn  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBasePlayerController_Respawn
      Preprocess: CBasePlayerController_Respawn.windows.yaml vfunc_sig matched 0 (need 1..1)
      Preprocess: llm_decompile request ready for CBasePlayerController_Respawn: platform=windows, model=gpt-5.4,
        reference_yaml_paths=['...references\\server\\CCSGameRules_BeginRound.windows.yaml']
      ... (llm_decompile decompiled CCSGameRules_BeginRound as reference; found only a direct "found_call" hit
      on CBasePlayerController_Respawn at 0x1808C1DB1 `call sub_180A35E30`, no `found_vcall` entry) ...
      Preprocess: failed to locate CBasePlayerController_Respawn
    Preprocess failed: find-CBasePlayerController_Respawn; falling back to AGENT SKILL
    Processing skill: find-CBasePlayerController_Respawn
      Falling back to: .claude\skills\find-CBasePlayerController_Respawn\SKILL.md
      Error: Skill file not found: .claude\skills\find-CBasePlayerController_Respawn\SKILL.md
      Failed

Diagnosis: the existing `vfunc_sig` for `CBasePlayerController_Respawn` no longer matches (0 matches, need 1..1)
on this game version, so the preprocessor fell back to LLM_DECOMPILE against predecessor `CCSGameRules_BeginRound`.
The decompile located a plain direct call to `CBasePlayerController_Respawn` (`call sub_180A35E30`) rather than a
`found_vcall` (an indirect `call [reg+offset]` vtable dispatch), so the preprocessor could not derive a new vfunc
offset from it — this looks like the actual virtual dispatch site moved to a different predecessor function than
`CCSGameRules_BeginRound`, or the call at 0x1808C1DB1 is now inlined/direct rather than virtual in this reference.
There is no agent-fallback `.claude\skills\find-CBasePlayerController_Respawn\SKILL.md`. Needs either a new/updated
predecessor anchor for the LLM_DECOMPILE step or an authored fallback SKILL.md.

## find-CCSPlayerController_Respawn  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CCSPlayerController_Respawn
    Failed: find-CCSPlayerController_Respawn (missing expected_input: CBasePlayerController_Respawn.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CBasePlayerController_Respawn` above. Not an independent bug;
re-enable once the producer skill is fixed.

## find-CCSPlayer_WeaponServices_DropWeapon  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CCSPlayer_WeaponServices_DropWeapon
      Preprocess: CCSPlayer_WeaponServices_DropWeapon.windows.yaml vfunc_sig matched 0 (need 1..1)
      Preprocess: llm_decompile request ready for CCSPlayer_WeaponServices_DropWeapon: platform=windows, model=gpt-5.4,
        reference_yaml_paths=['...references\\server\\CCSPlayer_ItemServices_DropActivePlayerWeapon.windows.yaml']
      Preprocess: llm_decompile raw response for CCSPlayer_WeaponServices_DropWeapon BEGIN
    {}
      Preprocess: llm_decompile raw response for CCSPlayer_WeaponServices_DropWeapon END
      Preprocess: llm_decompile parsed response BEGIN
    {
      "found_vcall": [],
      "found_call": [],
      "found_funcptr": [],
      "found_gv": [],
      "found_struct_offset": []
    }
      Preprocess: failed to locate CCSPlayer_WeaponServices_DropWeapon
    Preprocess failed: find-CCSPlayer_WeaponServices_DropWeapon; falling back to AGENT SKILL
    Processing skill: find-CCSPlayer_WeaponServices_DropWeapon
      Falling back to: .claude\skills\find-CCSPlayer_WeaponServices_DropWeapon\SKILL.md
      Error: Skill file not found: .claude\skills\find-CCSPlayer_WeaponServices_DropWeapon\SKILL.md
      Failed

Diagnosis: the existing `vfunc_sig` for `CCSPlayer_WeaponServices_DropWeapon` no longer matches (0 matches, need
1..1). The LLM_DECOMPILE fallback against predecessor `CCSPlayer_ItemServices_DropActivePlayerWeapon` returned a
completely empty response (`{}`), so no candidate vcall/struct-offset was found at all — the predecessor's body
likely no longer references this vfunc the way it used to, or the reference decompile itself changed shape. There
is no agent-fallback `.claude\skills\find-CCSPlayer_WeaponServices_DropWeapon\SKILL.md`. Needs either a new/updated
predecessor anchor or an authored fallback SKILL.md.

## find-CEntitySystem_Init-decompiles  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntitySystem_Init-decompiles
      ... (most of the 9 expected_output + expected_output_linux/_windows targets were generated successfully,
      e.g. INetworkMessages_SetNetworkSerializationContextData, IFlattenedSerializers_CreateFieldChangedEventQueue,
      CEntitySystem_m_pFieldChangeLimitSpew, CEntitySystem_m_ComponentUnserializerInfoAllocator, etc.) ...
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_sEntSystemName
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_eNetworkSerializationMode
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_ComponentUnserializerInfoAllocator
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_Symbols
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_pNetworkFieldScratchData
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_pFieldChangeLimitSpew
      Preprocess: struct-member name mismatch for CEntitySystem_m_EntityMaterialAttributes: expected CEntitySystem.m_EntityMaterialAttributes, got CEntitySystem.m_pNetworkFieldChangedEventQueue
      Preprocess: failed to locate CEntitySystem_m_EntityMaterialAttributes
    Preprocess failed: find-CEntitySystem_Init-decompiles; falling back to AGENT SKILL
    Processing skill: find-CEntitySystem_Init-decompiles
      Falling back to: .claude\skills\find-CEntitySystem_Init-decompiles\SKILL.md
      Error: Skill file not found: .claude\skills\find-CEntitySystem_Init-decompiles\SKILL.md
      Failed

Diagnosis: this skill decompiles `CEntitySystem_Init` to recover several struct members / globals in one pass.
Every target except the Windows-only `expected_output_windows` entry `CEntitySystem_m_EntityMaterialAttributes`
was located successfully this run. For that one member, the preprocessor iterated multiple struct-offset
candidates but each resolved to an already-named, different `CEntitySystem` member (name mismatch against every
candidate it tried), so it could never confirm the right offset for `m_EntityMaterialAttributes` — the member's
storage/access pattern in `CEntitySystem_Init` likely changed shape in this game version. There is no
agent-fallback `.claude\skills\find-CEntitySystem_Init-decompiles\SKILL.md`. Needs either a preprocessor fix
specific to locating `m_EntityMaterialAttributes` (or splitting it into its own skill so the rest aren't blocked
by it) or an authored fallback SKILL.md.

## find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState
      Preprocess: CBodyGameSystem_SpawnDependencyIsland.windows.yaml func_sig matched 2 (need 1)
      Preprocess: llm_decompile reference missing for CBodyGameSystem_SpawnDependencyIsland: D:\CS2_VibeSignatures\ida_preprocessor_scripts\references\server\CGameEntitySystem_Spawn.windows.yaml
      Preprocess: failed to locate CBodyGameSystem_SpawnDependencyIsland
    Preprocess failed: find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState; falling back to AGENT SKILL
    Processing skill: find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState
      Falling back to: .claude\skills\find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState\SKILL.md
      Error: Skill file not found: .claude\skills\find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState\SKILL.md
      Failed

Diagnosis: different failure shape than prior entries — the existing `func_sig` for `CBodyGameSystem_SpawnDependencyIsland`
became *ambiguous* this game version (2 matches, need exactly 1), rather than vanishing outright. The preprocessor's
disambiguation fallback needs to re-derive the right candidate via LLM_DECOMPILE against predecessor
`CGameEntitySystem_Spawn`, but the cached decompile reference file
`ida_preprocessor_scripts\references\server\CGameEntitySystem_Spawn.windows.yaml` does not exist on disk at all
(distinct from the `CGameEntitySystem_Spawn.{platform}.yaml` gamedata output declared in `expected_input`, which
does exist) — so the LLM_DECOMPILE request could never be built. There is no agent-fallback
`.claude\skills\find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState\SKILL.md`. Needs
either regenerating/adding the missing reference YAML for `CGameEntitySystem_Spawn`, a signature fix to
disambiguate the 2 func_sig matches directly, or an authored fallback SKILL.md.

## find-CGameSceneNode_PreInstanceSpawn  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CGameSceneNode_PreInstanceSpawn
    Failed: find-CGameSceneNode_PreInstanceSpawn (missing expected_input: CBodyGameSystem_SpawnDependencyIsland.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CBodyGameSystem_SpawnDependencyIsland-AND-CGameEntitySystem_CheckGlobalState`
above. Not an independent bug; re-enable once the producer skill is fixed.

## find-CLoopModeGame_ShutdownServer  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CLoopModeGame_ShutdownServer
      Preprocess: CLoopModeGame_ShutdownServer.windows.yaml func_sig matched 0 (need 1)
      Preprocess: trying func_xrefs fallback for CLoopModeGame_ShutdownServer
      Preprocess: common_funcs before excludes = ['0x180bdad20', '0x180bdd0a0']
      Preprocess: common_funcs after excludes = ['0x180bdad20', '0x180bdd0a0']
      Preprocess: xref intersection yielded 2 function(s) for CLoopModeGame_ShutdownServer (need exactly 1)
      Preprocess: failed to locate CLoopModeGame_ShutdownServer
    Preprocess failed: find-CLoopModeGame_ShutdownServer; falling back to AGENT SKILL
    Processing skill: find-CLoopModeGame_ShutdownServer
      Falling back to: .claude\skills\find-CLoopModeGame_ShutdownServer\SKILL.md
      Error: Skill file not found: .claude\skills\find-CLoopModeGame_ShutdownServer\SKILL.md
      Failed

Diagnosis: the existing `func_sig` for `CLoopModeGame_ShutdownServer` no longer matches (0 matches, need 1). The
func_xrefs fallback narrowed candidates to exactly 2 functions (`0x180bdad20`, `0x180bdd0a0`) via xref
intersection, but the skill's `exclude_funcs` (currently empty/insufficient) doesn't cut it down to exactly 1, so
preprocessing can't disambiguate between the two. There is no agent-fallback
`.claude\skills\find-CLoopModeGame_ShutdownServer\SKILL.md`. Needs either an `exclude_funcs`/additional xref
constraint to eliminate one of the two candidates, or an authored fallback SKILL.md.

## find-CLoopModeGame_OnLoopDeactivate  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CLoopModeGame_OnLoopDeactivate
    Failed: find-CLoopModeGame_OnLoopDeactivate (missing expected_input: CLoopModeGame_ShutdownServer.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CLoopModeGame_ShutdownServer` above. Not an independent bug;
re-enable once the producer skill is fixed.

## find-CEntitySystem_ClearEntityDatabase  (module: server, platform: windows) — CASCADE (2nd order)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntitySystem_ClearEntityDatabase
    Failed: find-CEntitySystem_ClearEntityDatabase (missing expected_input: CLoopModeGame_OnLoopDeactivate.windows.yaml)

Diagnosis: second-order cascade — depends on `find-CLoopModeGame_OnLoopDeactivate`'s output, which is itself a
cascade of `find-CLoopModeGame_ShutdownServer` above. Not an independent bug; re-enable once the root producer
skill is fixed.

## find-CPhysicsEntitySolver_PhysEnableEntityCollisions  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CPhysicsEntitySolver_PhysEnableEntityCollisions
      Preprocess: CPhysicsEntitySolver_PhysEnableEntityCollisions.windows.yaml func_sig matched 0 (need 1)
      Preprocess: trying func_xrefs fallback for CPhysicsEntitySolver_PhysEnableEntityCollisions
      Preprocess: vtable CPhysicsEntitySolver has 236 entries as candidate set
      Preprocess: common_funcs before excludes = []
      Preprocess: common_funcs after excludes = []
      Preprocess: xref intersection yielded 0 function(s) for CPhysicsEntitySolver_PhysEnableEntityCollisions (need exactly 1)
      Preprocess: failed to locate CPhysicsEntitySolver_PhysEnableEntityCollisions
    Preprocess failed: find-CPhysicsEntitySolver_PhysEnableEntityCollisions; falling back to AGENT SKILL
    Processing skill: find-CPhysicsEntitySolver_PhysEnableEntityCollisions
      Falling back to: .claude\skills\find-CPhysicsEntitySolver_PhysEnableEntityCollisions\SKILL.md
      Error: Skill file not found: .claude\skills\find-CPhysicsEntitySolver_PhysEnableEntityCollisions\SKILL.md
      Failed

Diagnosis: the existing `func_sig` for `CPhysicsEntitySolver_PhysEnableEntityCollisions` no longer matches (0
matches, need 1). The func_xrefs fallback used the 236-entry `CPhysicsEntitySolver` vtable as its candidate set,
but the xref intersection with `common_funcs` (currently no excludes configured) yielded 0 functions — the
opposite failure mode from `find-CLoopModeGame_ShutdownServer` above (too many candidates there; none here),
meaning the xref-string/caller assumption the skill relies on no longer holds for this function in this game
version. There is no agent-fallback
`.claude\skills\find-CPhysicsEntitySolver_PhysEnableEntityCollisions\SKILL.md`. Needs either a new anchor
(different xref string/caller or updated func_sig) or an authored fallback SKILL.md.

## find-CPointTeleportAPI_TeleportEntityInternal  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CPointTeleportAPI_TeleportEntityInternal
      Preprocess: CPointTeleportAPI_TeleportEntityInternal.windows.yaml func_sig matched 0 (need 1)
      Preprocess: trying func_xrefs fallback for CPointTeleportAPI_TeleportEntityInternal
      Preprocess: exclude_func YAML missing or invalid: CPointTeleport_Activate.windows.yaml
      Preprocess: failed to locate CPointTeleportAPI_TeleportEntityInternal
    Preprocess failed: find-CPointTeleportAPI_TeleportEntityInternal; falling back to AGENT SKILL
    Processing skill: find-CPointTeleportAPI_TeleportEntityInternal
      Falling back to: .claude\skills\find-CPointTeleportAPI_TeleportEntityInternal\SKILL.md
      Error: Skill file not found: .claude\skills\find-CPointTeleportAPI_TeleportEntityInternal\SKILL.md
      Failed

Diagnosis: the existing `func_sig` for `CPointTeleportAPI_TeleportEntityInternal` no longer matches (0 matches,
need 1). The func_xrefs fallback needs to exclude candidates that call `CPointTeleport_Activate`, but
`CPointTeleport_Activate.windows.yaml` doesn't exist yet — the config's `expected_input` for this skill only
lists its own output and doesn't declare `CPointTeleport_Activate.{platform}.yaml` as a dependency (the
`find-CPointTeleport_Activate` skill is defined later in config.yaml with no ordering edge forcing it first), so
the exclude anchor is unresolved when this skill runs. This is the same class of issue documented in this skill's
own instructions (missing exclude-anchor YAML, cf. the `find-ConnectInterfaces` example) — see
`ida_analyze_bin_failfast_validation`/`expected_input_needs_only_func_va` Serena memories. There is no
agent-fallback `.claude\skills\find-CPointTeleportAPI_TeleportEntityInternal\SKILL.md`. Needs adding
`CPointTeleport_Activate.{platform}.yaml` to this skill's `expected_input` (to force ordering) or an authored
fallback SKILL.md.

## find-CBaseEntity_Teleport  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBaseEntity_Teleport
    Failed: find-CBaseEntity_Teleport (missing expected_input: CPointTeleportAPI_TeleportEntityInternal.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CPointTeleportAPI_TeleportEntityInternal` above. Not an
independent bug; re-enable once the producer skill is fixed.

## find-CSource2EntitySystem_StaticInit-decompiles  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CSource2EntitySystem_StaticInit-decompiles
      Preprocess: missing desired-fields for target symbol: CGameEntitySystem_m_pEntity2SaveRestore
    Preprocess failed: find-CSource2EntitySystem_StaticInit-decompiles; falling back to AGENT SKILL
    Processing skill: find-CSource2EntitySystem_StaticInit-decompiles
      Falling back to: .claude\skills\find-CSource2EntitySystem_StaticInit-decompiles\SKILL.md
      Error: Skill file not found: .claude\skills\find-CSource2EntitySystem_StaticInit-decompiles\SKILL.md
      Failed

Diagnosis: different failure shape — no signature-matched-0/ambiguous message here, just an immediate preprocessor
error: "missing desired-fields for target symbol: CGameEntitySystem_m_pEntity2SaveRestore". This skill decompiles
`CSource2EntitySystem_StaticInit` to recover 8 shared outputs plus platform-specific extras (11 targets total,
including `CGameEntitySystem_m_pEntity2SaveRestore` in the common `expected_output` list). The error fired before
any "generated X.yaml" progress lines for this run, suggesting the preprocessor's per-target field table (used to
know what to extract for each target symbol during decompile) has no entry — or an invalid/stale one — for
`CGameEntitySystem_m_pEntity2SaveRestore` specifically, distinct from a signature drift issue. There is no
agent-fallback `.claude\skills\find-CSource2EntitySystem_StaticInit-decompiles\SKILL.md`. Needs a preprocessor-side
fix to register/repair the desired-fields entry for `CGameEntitySystem_m_pEntity2SaveRestore` (or split it out of
this combined skill) or an authored fallback SKILL.md.

## find-CEntitySystem_m_DataDescKeyUnserializers  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntitySystem_m_DataDescKeyUnserializers
    Failed: find-CEntitySystem_m_DataDescKeyUnserializers (missing expected_input: CEntitySystem_InstallCreationWrapperCallbacks.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CSource2EntitySystem_StaticInit-decompiles` above (that skill
never got the chance to generate any of its 11 outputs, including `CEntitySystem_InstallCreationWrapperCallbacks`).
Not an independent bug; re-enable once the producer skill is fixed.

## find-CEntitySystem_m_EntityPostSpawnCallback  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntitySystem_m_EntityPostSpawnCallback
    Failed: find-CEntitySystem_m_EntityPostSpawnCallback (missing expected_input: CEntitySystem_InstallPostSpawnCallback.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CSource2EntitySystem_StaticInit-decompiles` above. Not an
independent bug; re-enable once the producer skill is fixed.

## find-CGameEntitySystem_m_spawnGroupEntityFilters-windows  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CGameEntitySystem_m_spawnGroupEntityFilters-windows
    Failed: find-CGameEntitySystem_m_spawnGroupEntityFilters-windows (missing expected_input: CSpawnGroupEntityFilterRegistrar_RegisterSpawnGroupEntityFilters.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CSource2EntitySystem_StaticInit-decompiles` above. Not an
independent bug; re-enable once the producer skill is fixed.

## find-IGameSystem_OnServerBeginAsyncPostTickWork  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-IGameSystem_OnServerBeginAsyncPostTickWork
      Preprocess: invalid entry count from CLoopModeGame_OnServerBeginAsyncPostTickWork, expected 1, got 0
    Preprocess failed: find-IGameSystem_OnServerBeginAsyncPostTickWork; falling back to AGENT SKILL
    Processing skill: find-IGameSystem_OnServerBeginAsyncPostTickWork
      Falling back to: .claude\skills\find-IGameSystem_OnServerBeginAsyncPostTickWork\SKILL.md
      Error: Skill file not found: .claude\skills\find-IGameSystem_OnServerBeginAsyncPostTickWork\SKILL.md
      Failed

Diagnosis: another new failure shape — the preprocessor expected exactly 1 entry derived from (predecessor)
`CLoopModeGame_OnServerBeginAsyncPostTickWork` but got 0, i.e. whatever relationship/xref/vcall it reads off that
predecessor to locate `IGameSystem_OnServerBeginAsyncPostTickWork` no longer holds in this game version. There is
no agent-fallback `.claude\skills\find-IGameSystem_OnServerBeginAsyncPostTickWork\SKILL.md`. Needs a preprocessor/
predecessor fix or an authored fallback SKILL.md.

## find-ILoopMode_OnLoopDeactivate  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-ILoopMode_OnLoopDeactivate
    Failed: find-ILoopMode_OnLoopDeactivate (missing expected_input: CLoopModeGame_OnLoopDeactivate.windows.yaml)

Diagnosis: cascade from quarantining `find-CLoopModeGame_ShutdownServer` (iteration 7) → `find-CLoopModeGame_OnLoopDeactivate`
(iteration 8) chain — this consumer's dependency finally isn't on disk this run. Not an independent bug; re-enable
once the root producer skill is fixed.

## find-PhysEnableEntityCollisions-windows  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-PhysEnableEntityCollisions-windows
    Failed: find-PhysEnableEntityCollisions-windows (missing expected_input: CPhysicsEntitySolver_PhysEnableEntityCollisions.windows.yaml)

Diagnosis: direct cascade from quarantining `find-CPhysicsEntitySolver_PhysEnableEntityCollisions` (iteration 8).
Not an independent bug; re-enable once the producer skill is fixed.

## find-CBaseEntity_CollisionRulesChanged  (module: server, platform: windows) — CASCADE (2nd order)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBaseEntity_CollisionRulesChanged
    Failed: find-CBaseEntity_CollisionRulesChanged (missing expected_input: PhysEnableEntityCollisions.windows.yaml)

Diagnosis: second-order cascade — depends on `find-PhysEnableEntityCollisions-windows`'s output, itself a cascade
of `find-CPhysicsEntitySolver_PhysEnableEntityCollisions`. Not an independent bug; re-enable once the root producer
skill is fixed.

## find-ShowHudHint  (module: server, platform: windows)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-ShowHudHint
    Preprocess failed: find-ShowHudHint; falling back to AGENT SKILL
    Processing skill: find-ShowHudHint
      Falling back to: .claude\skills\find-ShowHudHint\SKILL.md
      Error: Skill file not found: .claude\skills\find-ShowHudHint\SKILL.md
      Failed

Diagnosis: different failure shape — no `Preprocess: ...` diagnostic line at all between "Start skill" and
"Preprocess failed", and the config.yaml entry for this skill has no `func_sig`/`vfunc_sig`/xref fields at all,
just a bare `expected_output: ShowHudHint.{platform}.yaml`. This skill was apparently always meant to be resolved
purely by an agent SKILL.md (no preprocessor path exists for it at all), but
`.claude\skills\find-ShowHudHint\SKILL.md` doesn't exist on disk. Needs an authored SKILL.md for this skill (there
is no preprocessor-side fix possible here since there's nothing to preprocess).

## find-UTIL_GetPlayerControllerForEntity  (module: server, platform: windows) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-UTIL_GetPlayerControllerForEntity
    Failed: find-UTIL_GetPlayerControllerForEntity (missing expected_input: ShowHudHint.windows.yaml)

Diagnosis: direct cascade from quarantining `find-ShowHudHint` above. Not an independent bug; re-enable once that
skill gets an authored fallback SKILL.md.

## find-UTIL_GetPlayerControllerForEntity-decompiles  (module: server, platform: windows) — CASCADE (2nd order)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-UTIL_GetPlayerControllerForEntity-decompiles
    Failed: find-UTIL_GetPlayerControllerForEntity-decompiles (missing expected_input: UTIL_GetPlayerControllerForEntity.windows.yaml)

Diagnosis: second-order cascade — depends on `find-UTIL_GetPlayerControllerForEntity`'s output, itself a cascade
of `find-ShowHudHint`. Not an independent bug; re-enable once the root producer skill is fixed.

Note: this run had **no new root-cause failure** — both failures were cascades of previously-quarantined skills,
and the rest of the module (including `find-g_pNavMesh`, `find-s_GameEventManager`) completed successfully. This
failure type (`missing expected_input`) does not abort sibling skills, so the module ran to completion; the run
still reports non-zero `Failed` and stops before further modules.

## find-CBasePlayerPawn_DropActivePlayerWeapon  (module: server, platform: linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CBasePlayerPawn_DropActivePlayerWeapon
      Preprocess: CBasePlayerPawn_DropActivePlayerWeapon.linux.yaml vfunc_sig matched 0 (need 1..1)
      Preprocess: llm_decompile request ready for CBasePlayerPawn_DropActivePlayerWeapon: platform=linux, model=gpt-5.4,
        reference_yaml_paths=['...references\\server\\CBaseCombatCharacter_OnKilled.linux.yaml']
      ... (decompiled CBaseCombatCharacter_OnKilled as reference; its body calls
      `(*(void (...)(...))(*a1 + 2664LL))(a1, &v27, v18, 0); // 2664LL = 0xA68 = CBasePlayerPawn_DropActivePlayerWeapon`
      i.e. a genuine vcall at vtable+0xA68, but the LLM response came back empty) ...
      Preprocess: llm_decompile raw response for CBasePlayerPawn_DropActivePlayerWeapon BEGIN
    {}
      Preprocess: llm_decompile raw response for CBasePlayerPawn_DropActivePlayerWeapon END
      Preprocess: llm_decompile parsed response BEGIN
    {
      "found_vcall": [],
      "found_call": [],
      "found_funcptr": [],
      "found_gv": [],
      "found_struct_offset": []
    }
      Preprocess: failed to locate CBasePlayerPawn_DropActivePlayerWeapon
    Preprocess failed: find-CBasePlayerPawn_DropActivePlayerWeapon; falling back to AGENT SKILL
    Processing skill: find-CBasePlayerPawn_DropActivePlayerWeapon
      Falling back to: .claude\skills\find-CBasePlayerPawn_DropActivePlayerWeapon\SKILL.md
      Error: Skill file not found: .claude\skills\find-CBasePlayerPawn_DropActivePlayerWeapon\SKILL.md
      Failed

Diagnosis: first Linux-platform failure in this run (all prior quarantines were Windows). The existing `vfunc_sig`
for `CBasePlayerPawn_DropActivePlayerWeapon` no longer matches on Linux (0 matches, need 1..1). The LLM_DECOMPILE
fallback against predecessor `CBaseCombatCharacter_OnKilled` decompiled a disasm that clearly *does* contain the
right vcall (annotated by IDA itself as `; 0xA68 = CBasePlayerPawn_DropActivePlayerWeapon` at
`(*(_QWORD*)a1+2664LL))(...)`), yet the model returned a completely empty `{}` response — this looks like an
LLM_DECOMPILE miss (the call is wrapped in a cast/function-pointer expression that may be harder to recognize as a
vcall) rather than a real binary-shape change. Since this is a shared `{platform}` skill (not `-windows`/`-linux`
split), quarantining it affects both platforms even though only Linux failed. There is no agent-fallback
`.claude\skills\find-CBasePlayerPawn_DropActivePlayerWeapon\SKILL.md`. Needs either a retry/prompt fix for
LLM_DECOMPILE on this call shape or an authored fallback SKILL.md. Likely cascades to
`find-CCSPlayer_ItemServices_DropActivePlayerWeapon` (declares this as `expected_input`) if its Linux output isn't
already on disk.

## find-CCSPlayer_ItemServices_DropActivePlayerWeapon  (module: server, platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CCSPlayer_ItemServices_DropActivePlayerWeapon
    Failed: find-CCSPlayer_ItemServices_DropActivePlayerWeapon (missing expected_input: CBasePlayerPawn_DropActivePlayerWeapon.linux.yaml)

Diagnosis: direct cascade from quarantining `find-CBasePlayerPawn_DropActivePlayerWeapon` above. Not an
independent bug; re-enable once the producer skill is fixed.

## find-CEntityIdentity_AcceptInputInternal  (module: server, platform: linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntityIdentity_AcceptInputInternal
      Preprocess: CEntityIdentity_AcceptInputInternal.linux.yaml func_sig matched 0 (need 1)
      Preprocess: llm_decompile request ready for CEntityIdentity_AcceptInputInternal: platform=linux, model=gpt-5.4,
        reference_yaml_paths=['...references\\server\\CEntityIdentity_AcceptInput.linux.yaml']
      ... (predecessor CEntityIdentity_AcceptInput's disasm ends with `jmp CEntityIdentity_AcceptInputInternal` —
      IDA has already named/resolved this as a direct tail-call target, and the decompiled pseudocode literally
      reads `return CEntityIdentity_AcceptInputInternal((_DWORD)a1, v9, a3, a4, a5, a6, a7, a8);` — yet the LLM
      response came back empty) ...
      Preprocess: llm_decompile raw response for CEntityIdentity_AcceptInputInternal BEGIN
    {}
      Preprocess: llm_decompile parsed response BEGIN
    {
      "found_vcall": [],
      "found_call": [],
      "found_funcptr": [],
      "found_gv": [],
      "found_struct_offset": []
    }
      Preprocess: failed to locate CEntityIdentity_AcceptInputInternal
    Preprocess failed: find-CEntityIdentity_AcceptInputInternal; falling back to AGENT SKILL
    Processing skill: find-CEntityIdentity_AcceptInputInternal
      Falling back to: .claude\skills\find-CEntityIdentity_AcceptInputInternal\SKILL.md
      Error: Skill file not found: .claude\skills\find-CEntityIdentity_AcceptInputInternal\SKILL.md
      Failed

Diagnosis: the existing `func_sig` for `CEntityIdentity_AcceptInputInternal` no longer matches on Linux (0
matches, need 1). Unlike most other LLM_DECOMPILE misses so far, this one is clearly a spurious miss rather than a
binary-shape change: the reference predecessor's disassembly and decompiled pseudocode both already name
`CEntityIdentity_AcceptInputInternal` directly as a plain tail-called function (IDA had already resolved/named
it), so this should have been a trivial `found_call` — but the model still returned `{}`. This is the same failure
class as `find-CBasePlayerPawn_DropActivePlayerWeapon` above (empty LLM_DECOMPILE response despite an obvious
answer being present in the reference payload) — worth investigating as a systemic LLM_DECOMPILE prompt issue
rather than fixing case-by-case. There is no agent-fallback
`.claude\skills\find-CEntityIdentity_AcceptInputInternal\SKILL.md`. Needs either a retry/prompt fix for
LLM_DECOMPILE or an authored fallback SKILL.md.

## find-CEntityInstance_ScriptAcceptInput-linux  (module: server, platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntityInstance_ScriptAcceptInput-linux
    Failed: find-CEntityInstance_ScriptAcceptInput-linux (missing expected_input: CEntityIdentity_AcceptInputInternal.linux.yaml)

Diagnosis: direct cascade from quarantining `find-CEntityIdentity_AcceptInputInternal` above. Not an independent
bug; re-enable once the producer skill is fixed.

## find-CEntitySystem_AddComponentFieldUnserializer  (module: server, platform: linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntitySystem_AddComponentFieldUnserializer
      Preprocess: CEntitySystem_AddComponentFieldUnserializer.linux.yaml func_sig matched 0 (need 1)
      Preprocess: trying func_xrefs fallback for CEntitySystem_AddComponentFieldUnserializer
      Preprocess: common_funcs before excludes = ['0x2129820', '0x212a8e0']
      Preprocess: common_funcs after excludes = ['0x2129820', '0x212a8e0']
      Preprocess: xref intersection yielded 2 function(s) for CEntitySystem_AddComponentFieldUnserializer (need exactly 1)
      Preprocess: failed to locate CEntitySystem_AddComponentFieldUnserializer
    Preprocess failed: find-CEntitySystem_AddComponentFieldUnserializer; falling back to AGENT SKILL
    Processing skill: find-CEntitySystem_AddComponentFieldUnserializer
      Falling back to: .claude\skills\find-CEntitySystem_AddComponentFieldUnserializer\SKILL.md
      Error: Skill file not found: .claude\skills\find-CEntitySystem_AddComponentFieldUnserializer\SKILL.md
      Failed

Diagnosis: same ambiguous-xref-intersection shape as `find-CLoopModeGame_ShutdownServer` (iteration 7) — the
`func_sig` no longer matches (0, need 1), and the func_xrefs fallback narrows to exactly 2 candidates
(`0x2129820`, `0x212a8e0`) with no `exclude_funcs` configured to break the tie. There is no agent-fallback
`.claude\skills\find-CEntitySystem_AddComponentFieldUnserializer\SKILL.md`. Needs either an `exclude_funcs`/
additional xref constraint to eliminate one candidate, or an authored fallback SKILL.md.

## find-CEntitySystem_m_EntityMaterialAttributes-linux  (module: server, platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEntitySystem_m_EntityMaterialAttributes-linux
    Failed: find-CEntitySystem_m_EntityMaterialAttributes-linux (missing expected_input: CEntitySystem_ProcessEntityRegistration.linux.yaml)

Diagnosis: cascade from `find-CSource2EntitySystem_StaticInit-decompiles` (iteration 10) — `CEntitySystem_ProcessEntityRegistration`
was one of that skill's `expected_output_linux` entries, never generated because that skill failed immediately
(no outputs at all this game version). Not an independent bug; re-enable once the root producer skill is fixed.

## find-CGameEntitySystem_m_pEntity2Networkables-linux  (module: server, platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CGameEntitySystem_m_pEntity2Networkables-linux
    Failed: find-CGameEntitySystem_m_pEntity2Networkables-linux (missing expected_input: CEntity2NetworkClasses_ServerClass_InitEntity2NetworkClasses.linux.yaml)

Diagnosis: another cascade from `find-CSource2EntitySystem_StaticInit-decompiles` (iteration 10) —
`CEntity2NetworkClasses_ServerClass_InitEntity2NetworkClasses` was also one of that skill's `expected_output_linux`
entries. Not an independent bug; re-enable once the root producer skill is fixed.

## find-CPlayer_MovementServices_ForceButtonState  (module: server, platform: linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CPlayer_MovementServices_ForceButtonState
      Preprocess: CPlayer_MovementServices_ForceButtonState.linux.yaml func_sig matched 0 (need 1)
      Preprocess: trying func_xrefs fallback for CPlayer_MovementServices_ForceButtonState
      Preprocess: common_funcs before excludes = ['0x1740ce0', '0x1748440']
      Preprocess: common_funcs after excludes = ['0x1740ce0', '0x1748440']
      Preprocess: xref intersection yielded 2 function(s) for CPlayer_MovementServices_ForceButtonState (need exactly 1)
      Preprocess: failed to locate CPlayer_MovementServices_ForceButtonState
    Preprocess failed: find-CPlayer_MovementServices_ForceButtonState; falling back to AGENT SKILL
    Processing skill: find-CPlayer_MovementServices_ForceButtonState
      Falling back to: .claude\skills\find-CPlayer_MovementServices_ForceButtonState\SKILL.md
      Error: Skill file not found: .claude\skills\find-CPlayer_MovementServices_ForceButtonState\SKILL.md
      Failed

Diagnosis: third occurrence of the exact same ambiguous-xref-intersection shape (`find-CLoopModeGame_ShutdownServer`
iter7, `find-CEntitySystem_AddComponentFieldUnserializer` iter16, this one) — `func_sig` gone, func_xrefs narrows to
exactly 2 candidates, no `exclude_funcs` configured to disambiguate. This recurring pattern strongly suggests the
func_xrefs fallback logic itself needs a systemic improvement (e.g. auto-suggest/require `exclude_funcs` when the
intersection count is >1) rather than fixing each skill individually. There is no agent-fallback
`.claude\skills\find-CPlayer_MovementServices_ForceButtonState\SKILL.md`. Needs either an `exclude_funcs`/
additional xref constraint or an authored fallback SKILL.md.

## find-CCSPlayer_MovementServices_ProcessMovement  (module: server, platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CCSPlayer_MovementServices_ProcessMovement
    Failed: find-CCSPlayer_MovementServices_ProcessMovement (missing expected_input: CPlayer_MovementServices_ForceButtonState.linux.yaml)

Diagnosis: direct cascade from quarantining `find-CPlayer_MovementServices_ForceButtonState` above. Not an
independent bug; re-enable once the producer skill is fixed.

## find-CCSPlayer_MovementServices_CheckMovingGround  (module: server, platform: linux) — CASCADE (2nd order)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CCSPlayer_MovementServices_CheckMovingGround
    Failed: find-CCSPlayer_MovementServices_CheckMovingGround (missing expected_input: CCSPlayer_MovementServices_ProcessMovement.linux.yaml)

Diagnosis: second-order cascade — depends on `find-CCSPlayer_MovementServices_ProcessMovement`'s output, itself a
cascade of `find-CPlayer_MovementServices_ForceButtonState`. Not an independent bug; re-enable once the root
producer skill is fixed.

## find-GetCSWeaponDataFromKey  (module: server, platform: linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-GetCSWeaponDataFromKey
      Preprocess: GetCSWeaponDataFromKey.linux.yaml func_sig matched 2 (need 1)
      Preprocess: llm_decompile request ready for GetCSWeaponDataFromKey: platform=linux, model=gpt-5.4,
        reference_yaml_paths=['...references\\server\\CSmokeGrenadeProjectile_Create.linux.yaml']
      Preprocess: llm_decompile raw response for GetCSWeaponDataFromKey BEGIN
    {}
      Preprocess: llm_decompile parsed response BEGIN
    {
      "found_vcall": [],
      "found_call": [],
      "found_funcptr": [],
      "found_gv": [],
      "found_struct_offset": []
    }
      Preprocess: failed to locate GetCSWeaponDataFromKey
    Preprocess failed: find-GetCSWeaponDataFromKey; falling back to AGENT SKILL
    Processing skill: find-GetCSWeaponDataFromKey
      Falling back to: .claude\skills\find-GetCSWeaponDataFromKey\SKILL.md
      Error: Skill file not found: .claude\skills\find-GetCSWeaponDataFromKey\SKILL.md
      Failed

Diagnosis: the existing `func_sig` for `GetCSWeaponDataFromKey` is now *ambiguous* on Linux (2 matches, need 1),
same shape as `find-CBodyGameSystem_SpawnDependencyIsland...` (iteration 6). The LLM_DECOMPILE fallback against
predecessor `CSmokeGrenadeProjectile_Create` returned a completely empty `{}` response — joining the growing list
of "empty LLM_DECOMPILE response" misses (iterations 14, 15) as a likely systemic prompt/model issue rather than
independent binary-shape changes each time. There is no agent-fallback
`.claude\skills\find-GetCSWeaponDataFromKey\SKILL.md`. Needs either a disambiguation fix (exclude one of the 2
func_sig matches) or an authored fallback SKILL.md.

## find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown  (module: engine [2nd pass], platform: linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown
      Preprocess: reused vfunc_sig metadata (no vtable resolution) at 0x36494c for CLoopTypeBase_GetImplType.linux.yaml
      Preprocess: generated CLoopTypeBase_GetImplType.linux.yaml
      Preprocess: ILoopModeFactory_GetLoopModeType.linux.yaml vfunc_sig matched 0 (need 1..1)
      Preprocess: llm_decompile request ready for ILoopModeFactory_GetLoopModeType: platform=linux, model=gpt-5.4,
        reference_yaml_paths=['...references\\engine\\CEngineServiceMgr_UnregisterLoopMode.linux.yaml']
      ... (predecessor CEngineServiceMgr_UnregisterLoopMode's disasm literally comments
      `call qword ptr [rax+20h] ; 20h = ILoopModeFactory_GetLoopModeType` and the decompiled pseudocode likewise
      comments `// 32LL = 0x20 = ILoopModeFactory_GetLoopModeType` at the matching vcall — yet the LLM response
      came back empty) ...
      Preprocess: reused vfunc_sig metadata (no vtable resolution) at 0x50a960 for ILoopModeFactory_Shutdown.linux.yaml
      Preprocess: llm_decompile raw response for ILoopModeFactory_GetLoopModeType BEGIN
    {}
      Preprocess: llm_decompile parsed response for ILoopModeFactory_GetLoopModeType BEGIN
    {
      "found_vcall": [],
      "found_call": [],
      "found_funcptr": [],
      "found_gv": [],
      "found_struct_offset": []
    }
      Preprocess: failed to locate ILoopModeFactory_GetLoopModeType
    Preprocess failed: find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown; falling back to AGENT SKILL
    Processing skill: find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown
      Falling back to: .claude\skills\find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown\SKILL.md
      Error: Skill file not found: .claude\skills\find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown\SKILL.md
      Failed

Diagnosis: first failure of the **second** `engine` module pass (config.yaml processes `engine`/`client`/`server`/
`networksystem` a second time for Shutdown-dependent skills after `engine2.dll` generates `ILoopModeFactory_Shutdown`
— the first full server-module pass, both platforms, is now completely clear). On Windows this exact skill
succeeded (all 3 outputs generated); only the Linux side hit an ambiguous/vanished `vfunc_sig` for
`ILoopModeFactory_GetLoopModeType` (0 matches, need 1..1), and — 4th occurrence now — the LLM_DECOMPILE fallback
returned a completely empty `{}` even though the reference predecessor's disasm/pseudocode both explicitly
comment the exact vcall being asked for. This is now a clearly systemic LLM_DECOMPILE issue (4 occurrences:
iterations 14, 15, 18, and this one) worth a real fix (prompt or retry logic) rather than continuing to quarantine
one-by-one. There is no agent-fallback
`.claude\skills\find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown\SKILL.md`.
Note: `CLoopTypeBase_GetImplType.linux.yaml` and `ILoopModeFactory_Shutdown.linux.yaml` were both generated
successfully before the failure (same partial-success shape as iteration 5's `find-CEntitySystem_Init-decompiles`).

## find-CLoopModeFactory_CLoopModeGame_Shutdown / find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems / find-IGameSystemFactory_Shutdown  (module: client [Shutdown-dependent pass], platform: linux) — CASCADE CHAIN

Failure (from `ida_analyze_bin.py -debug`):

    Failed: find-CLoopModeFactory_CLoopModeGame_Shutdown (missing expected_input: ILoopModeFactory_Shutdown.linux.yaml)
    Start skill: find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems
    Failed: find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems (missing expected_input: CLoopModeFactory_CLoopModeGame_Shutdown.linux.yaml)
    Start skill: find-IGameSystemFactory_Shutdown
    Failed: find-IGameSystemFactory_Shutdown (missing expected_input: IGameSystem_ShutdownAllSystems.linux.yaml)

Diagnosis: a 3-deep cascade chain, all rooted in the previous entry's quarantine of
`find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown` (module: engine
2nd pass) — that skill's Linux output `ILoopModeFactory_Shutdown.linux.yaml` (referenced here cross-module as
`../engine/ILoopModeFactory_Shutdown.{platform}.yaml`) never got generated, so
`find-CLoopModeFactory_CLoopModeGame_Shutdown` fails its `expected_input` check, which cascades to
`find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems`, which cascades again to
`find-IGameSystemFactory_Shutdown`. None are independent bugs; all three re-enable once the root `engine`-module
producer skill is fixed. Note: this exact 3-skill block is **duplicated** under the `server` module (config.yaml
~line 10164, same names/shapes, same `../engine/ILoopModeFactory_Shutdown.{platform}.yaml` dependency) — expect
the identical cascade to surface again once the loop reaches the `server` Shutdown-dependent pass; only the
`client`-module copies were quarantined this iteration per the one-fix-at-a-time rule.

## Config-parsing crash (self-inflicted) — NOT a skill failure

After quarantining all 3 skills under the `client` Shutdown-dependent module above, that module's `skills:` key had
no remaining (uncommented) list items, so PyYAML parsed its value as `None` instead of an empty list. The very
next run crashed before processing anything:

    Traceback (most recent call last):
      File "D:\CS2_VibeSignatures\ida_analyze_bin.py", line 3044, in <module>
        main()
      File "D:\CS2_VibeSignatures\ida_analyze_bin.py", line 2886, in main
        modules = parse_config(config_path)
      File "D:\CS2_VibeSignatures\ida_analyze_bin.py", line 1348, in parse_config
        for skill in module.get("skills", []):
    TypeError: 'NoneType' object is not iterable

Diagnosis/fix: this is not a skill bug and not one of the documented STOP conditions — it's a direct structural
side effect of commenting out every skill in a module block. Fixed by changing that module's `skills:` line to
`skills: []` (keeping the commented-out entries below it as documentation/awaiting-fix markers). Verified
`python -c "import yaml; yaml.safe_load(open('config.yaml'))"` reports no module with a `None` skills list before
continuing the loop. Applied the same preemptive `skills: []` fix to the `server` module's identical 3-skill block
below when quarantining it too, to avoid repeating this crash.

## find-CLoopModeFactory_CLoopModeGame_Shutdown / find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems / find-IGameSystemFactory_Shutdown  (module: server [Shutdown-dependent pass], platform: linux) — CASCADE CHAIN (duplicate block)

Failure (from `ida_analyze_bin.py -debug`):

    Failed: find-CLoopModeFactory_CLoopModeGame_Shutdown (missing expected_input: ILoopModeFactory_Shutdown.linux.yaml)
    Start skill: find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems
    Failed: find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems (missing expected_input: CLoopModeFactory_CLoopModeGame_Shutdown.linux.yaml)
    Start skill: find-IGameSystemFactory_Shutdown
    Failed: find-IGameSystemFactory_Shutdown (missing expected_input: IGameSystem_ShutdownAllSystems.linux.yaml)

Diagnosis: exactly the same cascade as the `client`-module entry above, from the exact same root cause
(`ILoopModeFactory_Shutdown.linux.yaml` never generated) — this is the predicted duplicate block under the
`server` module (config.yaml ~line 10164-10186). Not an independent bug; re-enable both module copies once the
root `engine`-module producer skill is fixed.

## find-CEngineServiceMgr_GetEventDispatcher  (module: engine [3rd pass — "after late client IEngineServiceMgr output"], platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CEngineServiceMgr_GetEventDispatcher
    Failed: find-CEngineServiceMgr_GetEventDispatcher (missing expected_input: IEngineServiceMgr_GetEventDispatcher.linux.yaml)

Diagnosis: further cascade from the same `ILoopModeFactory_Shutdown.linux.yaml` root cause — this skill's
`expected_input` includes `../client/IEngineServiceMgr_GetEventDispatcher.{platform}.yaml`, one of the two outputs
of `find-IEngineServiceMgr_GetEventDispatcher-AND-IGameSystem_ShutdownAllSystems` quarantined above (both the
`client` and `server` copies), so it was never generated on Linux. Not an independent bug; re-enable once the root
`engine`-module producer skill is fixed. This was the **only** skill in this module block, so quarantining it also
required the same `skills: []` structural fix (see the config-parsing-crash note above) to avoid the same
`TypeError: 'NoneType' object is not iterable` crash.

## find-CFlattenedSerializers_CreateFieldChangedEventQueue  (module: networksystem [2nd pass, "after server.dll"], platform: linux) — CASCADE

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-CFlattenedSerializers_CreateFieldChangedEventQueue
    Failed: find-CFlattenedSerializers_CreateFieldChangedEventQueue (missing expected_input: IFlattenedSerializers_CreateFieldChangedEventQueue.linux.yaml)

Diagnosis: cascade from `find-CEntitySystem_Init-decompiles` (iteration 5) — `IFlattenedSerializers_CreateFieldChangedEventQueue`
was one of that skill's shared `expected_output` entries (referenced here cross-module as
`../server/IFlattenedSerializers_CreateFieldChangedEventQueue.{platform}.yaml`). That skill got 8/9 outputs on
Windows before failing on `m_EntityMaterialAttributes`, but this is the Linux side reaching a consumer of one of
those outputs for the first time — evidently the Linux copy was never generated either (the whole skill was
quarantined before Linux got a chance, or Linux failed the same shared target silently before the module aborted).
Not an independent bug; re-enable once the root producer skill is fixed.

## ⚠ find-CNetworkMessages_GetIsForServer  (module: networksystem [2nd pass], platform: linux) — DIFFERENT FAILURE CLASS, LOOP PAUSED

Failure (from `ida_analyze_bin.py -debug`):

    Processing skill: find-CNetworkMessages_GetIsForServer
      Falling back to: .claude\skills\find-CNetworkMessages_GetIsForServer\SKILL.md
      ... (agent invocation via claude.cmd) ...
      Running (attempt 1/3): claude.cmd -p /find-CNetworkMessages_GetIsForServer --agent sig-finder --allowedTools mcp__ida-pro-mcp__* ...
    API Error: Sonnet 5 has safety measures that flagged this message for a cybersecurity topic. To learn about the
    Cyber Verification Program and apply for access, visit our help center:
    https://support.claude.com/en/articles/14604842-real-time-cyber-safeguards-on-claude.
      Skill failed with return code: 1
      Retrying with session ...
      [RETRY] Running (attempt 2/3): ... --resume ...
    API Error: Sonnet 5 has safety measures that flagged this message for a cybersecurity topic. (same message)
      [RETRY] Running (attempt 3/3): ... --resume ...
    API Error: Sonnet 5 has safety measures that flagged this message for a cybersecurity topic. (same message)
      Failed after 3 attempts
      Failed

Diagnosis: **NOT a signature/binary-drift issue** — this is an Anthropic API-level real-time safety classifier
blocking the `sig-finder` sub-agent's session on a "cybersecurity topic" flag, on all 3 retry attempts. The
function itself (`CNetworkMessages_GetIsForServer`, a network-serialization getter) has no obviously
security-sensitive name, so this is plausibly triggered by the broader task framing (binary reverse-engineering /
byte-signature-generation agent context) rather than this symbol specifically. This does not match this skill's
documented STOP signals verbatim (IDB lock / binary verification / MCP restore / gamever) but matches their
*spirit* — an infrastructure/environment-level block unrelated to this skill's own signature logic — so per the
Safety Rules this run **paused here instead of quarantining** and surfaced the issue for the user, rather than
mechanically commenting the skill out. Needs the user's input: whether to apply for the linked Cyber Verification
Program, adjust the fallback agent's framing, or explicitly accept quarantining this skill (and watch for
recurrence on others) before the loop continues.

**User decision (2026-07-10): quarantine and continue.** Confirmed as the only occurrence in 23 iterations; treated
like the other unresolved skills — commented out of config.yaml, loop resumed. If this safety flag recurs on other
skills, that would indicate a systemic issue with the `sig-finder` sub-agent's framing worth investigating properly
rather than continuing to quarantine case-by-case.

## find-CNetworkMessages_SetNetworkSerializationContextData / find-CNetworkMessages_GetNetworkSerializationContextData / find-INetworkMessages_GetFieldChangeCallbackOrderCount-AND-INetworkMessages_GetFieldChangeCallbackPriorities  (module: networksystem [2nd pass], platform: linux) — CASCADES

Failure (from `ida_analyze_bin.py -debug`):

    Failed: find-CNetworkMessages_SetNetworkSerializationContextData (missing expected_input: INetworkMessages_SetNetworkSerializationContextData.linux.yaml)
    Start skill: find-CNetworkMessages_GetNetworkSerializationContextData
    Failed: find-CNetworkMessages_GetNetworkSerializationContextData (missing expected_input: CNetworkMessages_SetNetworkSerializationContextData.linux.yaml)
    Start skill: find-INetworkMessages_GetFieldChangeCallbackOrderCount-AND-INetworkMessages_GetFieldChangeCallbackPriorities
    Failed: find-INetworkMessages_GetFieldChangeCallbackOrderCount-AND-INetworkMessages_GetFieldChangeCallbackPriorities (missing expected_input: CFlattenedSerializers_CreateFieldChangedEventQueue.linux.yaml)

Diagnosis: three more cascades, no new root cause this iteration.
`find-CNetworkMessages_SetNetworkSerializationContextData` → cascade of `find-CEntitySystem_Init-decompiles`
(iteration 5; `INetworkMessages_SetNetworkSerializationContextData` was another of its shared outputs never
generated on Linux).
`find-CNetworkMessages_GetNetworkSerializationContextData` → 2nd-order cascade of the above.
`find-INetworkMessages_GetFieldChangeCallbackOrderCount-AND-INetworkMessages_GetFieldChangeCallbackPriorities` →
cascade of `find-CFlattenedSerializers_CreateFieldChangedEventQueue` (iteration 23). None are independent bugs;
all re-enable once their respective root producer skills are fixed.
