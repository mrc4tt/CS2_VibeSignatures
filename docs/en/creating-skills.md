[Back to README](../../README.md) | [中文](../zh-CN/creating-skills.md)

Once a symbol-analysis skill is ready to share, see [Contributing via PR](conributing-via-pr.md) for the `SKILL: create-pr` workflow.

# Creating symbol-analysis skills

## Vtable example

For `CCSPlayerPawn`, ask Claude Code to create the vtable-finder preprocessor script && update config via SKILL:

* OpenCode can also automatically discover `SKILL.md` files under `.claude/skills`, but Codex requires you to create a `.claude/skills` <==> `.codex/skills` symbolic link manually before it can discover existing skills in the repository.

```text
/create-preprocessor-scripts Create "find-CCSPlayerPawn_vtable" in server.
```

## Regular-function example

This example identifies `CItemDefuser_Spawn`, then uses it to locate `CBaseModelEntity_SetModel`.

### 1. Locate the target symbols in IDA

Search for `weapons/models/defuser/defuser.vmdl` and inspect its cross-references for this pattern:

```c
v2 = a2;
v3 = (__int64)a1;
sub_180XXXXXX(a1, (__int64)"weapons/models/defuser/defuser.vmdl"); // CBaseModelEntity_SetModel
sub_180YYYYYY(v3, v2);
v4 = (_DWORD *)sub_180ZZZZZZ(&unk_181AAAAAA, 0xFFFFFFFFi64);
if ( !v4 )
  v4 = *(_DWORD **)(qword_181BBBBBB + 8);
if ( *v4 == 1 )
{
  v5 = (__int64 *)(*(__int64 (__fastcall **)(__int64, const char *, _QWORD, _QWORD))(*(_QWORD *)qword_181CCCCCC + 48i64))(
                    qword_181CCCCCC,
                    "defuser_dropped",
                    0i64,
                    0i64);
```

The containing function is `CItemDefuser_Spawn`.

### 2. Create preprocessors and update the config

```text
/create-preprocessor-scripts Create "find-CItemDefuser_Spawn" in server by xref_strings "weapons/models/defuser/defuser.vmdl" "defuser_dropped", where CItemDefuser_Spawn is a vfunc of CItemDefuser_vtable.
```

```text
/create-preprocessor-scripts Create "find-CBaseModelEntity_SetModel" in server by LLM_DECOMPILE with "CItemDefuser_Spawn", where CBaseModelEntity_SetModel is a regular function being called in "CItemDefuser_Spawn".
```

## Global-variable example

This example identifies `IGameSystem_InitAllSystems_pFirst`.

### 1. Locate the target symbols in IDA

- Search for `IGameSystem::InitAllSystems`; the function referencing the string is `IGameSystem_InitAllSystems`.
- Rename it to `IGameSystem_InitAllSystems` if necessary.
- Look near the start of the function for `( i = qword_XXXXXX; i; i = *(_QWORD *)(i + 8) )`.
- Rename that `qword_XXXXXX` to `IGameSystem_InitAllSystems_pFirst` if necessary.

### 2. Create preprocessors and update the config

```text
/create-preprocessor-scripts Create "find-IGameSystem_InitAllSystems" in server by xref_strings "IGameSystem::InitAllSystems", where IGameSystem_InitAllSystems is a regular func.
```

```text
/create-preprocessor-scripts Create "find-IGameSystem_InitAllSystems_pFirst" in server by LLM_DECOMPILE with "IGameSystem_InitAllSystems", where IGameSystem_InitAllSystems_pFirst is a global variable being used in "IGameSystem_InitAllSystems".
```

## Struct-offset example

This example identifies `CGameResourceService_m_pEntitySystem`.

### 1. Locate the target symbols in IDA

- Search for `CGameResourceService::BuildResourceManifest(start)` and inspect its cross-references.
- The cross-reference should point to `CGameResourceService_BuildResourceManifest`. Rename it if necessary.

### 2. Create preprocessors and update the config

```text
/create-preprocessor-scripts Create "find-CGameResourceService_BuildResourceManifest" in engine by xref_strings "CGameResourceService::BuildResourceManifest(start)", where CGameResourceService_BuildResourceManifest is a vfunc of CGameResourceService_vtable.
```

```text
/create-preprocessor-scripts Create "find-CGameResourceService_m_pEntitySystem" in engine by LLM_DECOMPILE with "CGameResourceService_BuildResourceManifest", where CGameResourceService_m_pEntitySystem is a struct offset.
```

## Patch example

A patch skill locates a specific instruction inside a known function and generates replacement bytes to change its runtime behavior, such as forcing or skipping a branch or NOPing a call. The target function should already have a corresponding find-skill output, typically supplied through `expected_input`.

Always ensure the ida-pro-mcp server is running. Human contributors should write a new initial prompt for each new symbol instead of copying the example prompt verbatim.

This example patches the velocity-clamping `jbe` inside `CCSPlayer_MovementServices_FullWalkMove` to an unconditional `jmp`.

### 1. Locate the target instruction in IDA

Decompile `CCSPlayer_MovementServices_FullWalkMove` and locate the velocity-clamping condition:

```c
v20 = (float)((float)(v16 * v16) + (float)(v19 * v19)) + (float)(v17 * v17);
if ( v20 > (float)(v18 * v18) )
{
  ...velocity clamping logic...
}
```

Disassemble around the comparison to locate the `comiss` and conditional jump pair:

```asm
addss   xmm2, xmm1
comiss  xmm2, xmm0
jbe     loc_XXXXXXXX
```

Determine the patch bytes from the instruction encoding:

- Near `jbe` (`0F 86 rel32`, 6 bytes) becomes `E9 <new_rel32> 90` (`jmp` plus `nop`).
- Short `jbe` (`76 rel8`, 2 bytes) becomes `EB rel8` (`jmp short`).

### 2. Create the preprocessor and update the config

```text
/create-preprocessor-scripts Create "find-CCSPlayer_MovementServices_FullWalkMove" in server with SKILL.md support. the SKILL.md should follow what we did via ida-pro-mcp.
```
