# Preprocessor coverage: 14178b

Static inventory from config; presence does not prove runtime success or platform support.
Counts are configured module/skill entries, not symbols or binary files.
`entrypoint_not_declared` requires review (the entrypoint may be imported dynamically).

Total: 1255. Missing Python: 75. Missing Python with SKILL.md: 75.

| Module | Entries | Python present | Missing Python | Other issues |
|---|---:|---:|---:|---:|
| SDL3 | 6 | 6 | 0 | 0 |
| client | 129 | 129 | 0 | 0 |
| engine | 413 | 396 | 17 | 0 |
| matchmaking | 1 | 1 | 0 | 0 |
| networksystem | 52 | 52 | 0 | 0 |
| scenesystem | 2 | 2 | 0 | 0 |
| server | 651 | 593 | 58 | 0 |
| vphysics2 | 1 | 1 | 0 | 0 |

## engine

- `find-CNetworkGameServerBase_m_Clients` (windows,linux): **missing_py**; source: `.claude/skills/find-CNetworkGameServerBase_m_Clients/SKILL.md`; target: `ida_preprocessor_scripts/find-CNetworkGameServerBase_m_Clients.py`
- `find-CNetworkGameServer_PackEntities` (windows,linux): **missing_py**; source: `.claude/skills/find-CNetworkGameServer_PackEntities/SKILL.md`; target: `ida_preprocessor_scripts/find-CNetworkGameServer_PackEntities.py`
- `find-CServerSideClient_SetName` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_SetName/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_SetName.py`
- `find-CServerSideClient_m_Name` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_Name/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_Name.py`
- `find-CServerSideClient_m_NetChannel` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_NetChannel/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_NetChannel.py`
- `find-CServerSideClient_m_Server` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_Server/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_Server.py`
- `find-CServerSideClient_m_SteamID` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_SteamID/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_SteamID.py`
- `find-CServerSideClient_m_SteamIDMirror` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_SteamIDMirror/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_SteamIDMirror.py`
- `find-CServerSideClient_m_UserID` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_UserID/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_UserID.py`
- `find-CServerSideClient_m_UserIDString` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_UserIDString/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_UserIDString.py`
- `find-CServerSideClient_m_bFakePlayer` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_bFakePlayer/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_bFakePlayer.py`
- `find-CServerSideClient_m_bIsHLTV` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_bIsHLTV/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_bIsHLTV.py`
- `find-CServerSideClient_m_nClientSlot` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_nClientSlot/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_nClientSlot.py`
- `find-CServerSideClient_m_nConnectionTypeFlags` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_nConnectionTypeFlags/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_nConnectionTypeFlags.py`
- `find-CServerSideClient_m_nEntityIndex` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_nEntityIndex/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_nEntityIndex.py`
- `find-CServerSideClient_m_nSignonState` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_nSignonState/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_nSignonState.py`
- `find-CServerSideClient_m_pAttachedTo` (windows,linux): **missing_py**; source: `.claude/skills/find-CServerSideClient_m_pAttachedTo/SKILL.md`; target: `ida_preprocessor_scripts/find-CServerSideClient_m_pAttachedTo.py`

## server

- `find-BotProfile_Aggression` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_Aggression/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_Aggression.py`
- `find-BotProfile_AttackDelay` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_AttackDelay/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_AttackDelay.py`
- `find-BotProfile_Cost` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_Cost/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_Cost.py`
- `find-BotProfile_Difficulty` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_Difficulty/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_Difficulty.py`
- `find-BotProfile_LookAngleDampingAttacking` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_LookAngleDampingAttacking/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_LookAngleDampingAttacking.py`
- `find-BotProfile_LookAngleMaxAccelAttacking` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_LookAngleMaxAccelAttacking/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_LookAngleMaxAccelAttacking.py`
- `find-BotProfile_LookAngleStiffnessAttacking` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_LookAngleStiffnessAttacking/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_LookAngleStiffnessAttacking.py`
- `find-BotProfile_ReactionTime` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_ReactionTime/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_ReactionTime.py`
- `find-BotProfile_Skill` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_Skill/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_Skill.py`
- `find-BotProfile_Teamwork` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_Teamwork/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_Teamwork.py`
- `find-BotProfile_WeaponPref` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_WeaponPref/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_WeaponPref.py`
- `find-BotProfile_WeaponPrefCount` (windows,linux): **missing_py**; source: `.claude/skills/find-BotProfile_WeaponPrefCount/SKILL.md`; target: `ida_preprocessor_scripts/find-BotProfile_WeaponPrefCount.py`
- `find-BuyState_DoneBuying` (windows,linux): **missing_py**; source: `.claude/skills/find-BuyState_DoneBuying/SKILL.md`; target: `ida_preprocessor_scripts/find-BuyState_DoneBuying.py`
- `find-BuyState_InitialDelay` (windows,linux): **missing_py**; source: `.claude/skills/find-BuyState_InitialDelay/SKILL.md`; target: `ida_preprocessor_scripts/find-BuyState_InitialDelay.py`
- `find-BuyState_OnUpdate` (windows,linux): **missing_py**; source: `.claude/skills/find-BuyState_OnUpdate/SKILL.md`; target: `ida_preprocessor_scripts/find-BuyState_OnUpdate.py`
- `find-CBaseEntity_m_iTeamNum` (windows,linux): **missing_py**; source: `.claude/skills/find-CBaseEntity_m_iTeamNum/SKILL.md`; target: `ida_preprocessor_scripts/find-CBaseEntity_m_iTeamNum.py`
- `find-CBaseIssue_CountPotentialVoters` (windows,linux): **missing_py**; source: `.claude/skills/find-CBaseIssue_CountPotentialVoters/SKILL.md`; target: `ida_preprocessor_scripts/find-CBaseIssue_CountPotentialVoters.py`
- `find-CBasePlayerController_FakeClientFlags` (windows,linux): **missing_py**; source: `.claude/skills/find-CBasePlayerController_FakeClientFlags/SKILL.md`; target: `ida_preprocessor_scripts/find-CBasePlayerController_FakeClientFlags.py`
- `find-CBasePlayerController_OnSimulateUserCommands` (windows,linux): **missing_py**; source: `.claude/skills/find-CBasePlayerController_OnSimulateUserCommands/SKILL.md`; target: `ida_preprocessor_scripts/find-CBasePlayerController_OnSimulateUserCommands.py`
- `find-CCSBotManager_MaintainBotQuota` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSBotManager_MaintainBotQuota/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSBotManager_MaintainBotQuota.py`
- `find-CCSBot_EquipBestWeapon` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSBot_EquipBestWeapon/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSBot_EquipBestWeapon.py`
- `find-CCSBot_EquipPistol` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSBot_EquipPistol/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSBot_EquipPistol.py`
- `find-CCSBot_Profile` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSBot_Profile/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSBot_Profile.py`
- `find-CCSBot_Update` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSBot_Update/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSBot_Update.py`
- `find-CCSBot_UpdateLookAngles` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSBot_UpdateLookAngles/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSBot_UpdateLookAngles.py`
- `find-CCSCustomHudLayout_SetDialogVariableString` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSCustomHudLayout_SetDialogVariableString/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSCustomHudLayout_SetDialogVariableString.py`
- `find-CCSCustomHudLayout_SetDialogVariableStringForPlayer` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSCustomHudLayout_SetDialogVariableStringForPlayer/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSCustomHudLayout_SetDialogVariableStringForPlayer.py`
- `find-CCSCustomHudLayout_SetHasClass` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSCustomHudLayout_SetHasClass/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSCustomHudLayout_SetHasClass.py`
- `find-CCSCustomHudLayout_SetHasClassForPlayer` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSCustomHudLayout_SetHasClassForPlayer/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSCustomHudLayout_SetHasClassForPlayer.py`
- `find-CCSCustomHudLayout_SetInputCaptureEnabled` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSCustomHudLayout_SetInputCaptureEnabled/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSCustomHudLayout_SetInputCaptureEnabled.py`
- `find-CCSGameRules_SameMapTeardown` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSGameRules_SameMapTeardown/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSGameRules_SameMapTeardown.py`
- `find-CCSPlayerController_HandleCommand_JoinTeam` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerController_HandleCommand_JoinTeam/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerController_HandleCommand_JoinTeam.py`
- `find-CCSPlayerController_InventoryServices_m_pInventory` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerController_InventoryServices_m_pInventory/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerController_InventoryServices_m_pInventory.py`
- `find-CCSPlayerInventory_GetItemInLoadout` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerInventory_GetItemInLoadout/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerInventory_GetItemInLoadout.py`
- `find-CCSPlayerInventory_SendInventoryUpdateEvent` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerInventory_SendInventoryUpdateEvent/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerInventory_SendInventoryUpdateEvent.py`
- `find-CCSPlayerInventory_m_pSOCache` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerInventory_m_pSOCache/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerInventory_m_pSOCache.py`
- `find-CCSPlayerPawn_SetEyeAngles` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerPawn_SetEyeAngles/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerPawn_SetEyeAngles.py`
- `find-CCSPlayerPawn_SetModelFromClass` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerPawn_SetModelFromClass/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerPawn_SetModelFromClass.py`
- `find-CCSPlayerPawn_SetModelFromLoadout` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayerPawn_SetModelFromLoadout/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayerPawn_SetModelFromLoadout.py`
- `find-CCSPlayer_ItemServices_SetWearables` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayer_ItemServices_SetWearables/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayer_ItemServices_SetWearables.py`
- `find-CCSPlayer_MovementServices_Pawn` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayer_MovementServices_Pawn/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayer_MovementServices_Pawn.py`
- `find-CCSPlayer_WeaponServices_Weapon_GetSlot` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPlayer_WeaponServices_Weapon_GetSlot/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPlayer_WeaponServices_Weapon_GetSlot.py`
- `find-CCSPointScript_OnCustomHudClicked` (windows,linux): **missing_py**; source: `.claude/skills/find-CCSPointScript_OnCustomHudClicked/SKILL.md`; target: `ida_preprocessor_scripts/find-CCSPointScript_OnCustomHudClicked.py`
- `find-CEconItemView_CEconItemView` (windows,linux): **missing_py**; source: `.claude/skills/find-CEconItemView_CEconItemView/SKILL.md`; target: `ida_preprocessor_scripts/find-CEconItemView_CEconItemView.py`
- `find-CEconItemView_operator=` (windows,linux): **missing_py**; source: `.claude/skills/find-CEconItemView_operator=/SKILL.md`; target: `ida_preprocessor_scripts/find-CEconItemView_operator=.py`
- `find-CEntityIdentity_EHandle` (windows,linux): **missing_py**; source: `.claude/skills/find-CEntityIdentity_EHandle/SKILL.md`; target: `ida_preprocessor_scripts/find-CEntityIdentity_EHandle.py`
- `find-CEntityIdentity_Size` (windows,linux): **missing_py**; source: `.claude/skills/find-CEntityIdentity_Size/SKILL.md`; target: `ida_preprocessor_scripts/find-CEntityIdentity_Size.py`
- `find-CEntityIdentity_m_designerName` (windows,linux): **missing_py**; source: `.claude/skills/find-CEntityIdentity_m_designerName/SKILL.md`; target: `ida_preprocessor_scripts/find-CEntityIdentity_m_designerName.py`
- `find-CEntityIdentity_m_pInstance` (windows,linux): **missing_py**; source: `.claude/skills/find-CEntityIdentity_m_pInstance/SKILL.md`; target: `ida_preprocessor_scripts/find-CEntityIdentity_m_pInstance.py`
- `find-CEntitySystem_m_EntityList` (windows,linux): **missing_py**; source: `.claude/skills/find-CEntitySystem_m_EntityList/SKILL.md`; target: `ida_preprocessor_scripts/find-CEntitySystem_m_EntityList.py`
- `find-CGCClientSharedObjectCache_m_Owner` (windows,linux): **missing_py**; source: `.claude/skills/find-CGCClientSharedObjectCache_m_Owner/SKILL.md`; target: `ida_preprocessor_scripts/find-CGCClientSharedObjectCache_m_Owner.py`
- `find-CMoveData_AbsOrigin` (windows,linux): **missing_py**; source: `.claude/skills/find-CMoveData_AbsOrigin/SKILL.md`; target: `ida_preprocessor_scripts/find-CMoveData_AbsOrigin.py`
- `find-CMoveData_Velocity` (windows,linux): **missing_py**; source: `.claude/skills/find-CMoveData_Velocity/SKILL.md`; target: `ida_preprocessor_scripts/find-CMoveData_Velocity.py`
- `find-MpHumanTeam_ApplyRestriction` (windows,linux): **missing_py**; source: `.claude/skills/find-MpHumanTeam_ApplyRestriction/SKILL.md`; target: `ida_preprocessor_scripts/find-MpHumanTeam_ApplyRestriction.py`
- `find-UTIL_Remove` (windows,linux): **missing_py**; source: `.claude/skills/find-UTIL_Remove/SKILL.md`; target: `ida_preprocessor_scripts/find-UTIL_Remove.py`
- `find-vtidx_DropWeapon` (windows,linux): **missing_py**; source: `.claude/skills/find-vtidx_DropWeapon/SKILL.md`; target: `ida_preprocessor_scripts/find-vtidx_DropWeapon.py`
- `find-vtidx_FinishMove` (windows,linux): **missing_py**; source: `.claude/skills/find-vtidx_FinishMove/SKILL.md`; target: `ida_preprocessor_scripts/find-vtidx_FinishMove.py`
- `find-vtidx_PlayerRunCommand` (windows,linux): **missing_py**; source: `.claude/skills/find-vtidx_PlayerRunCommand/SKILL.md`; target: `ida_preprocessor_scripts/find-vtidx_PlayerRunCommand.py`
