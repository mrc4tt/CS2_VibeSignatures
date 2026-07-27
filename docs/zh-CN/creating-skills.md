[返回中文 README](../../README_CN.md) | [English](../en/creating-skills.md)

创建好符号分析 skill 后，可参阅[通过 PR 贡献](conributing-via-pr.md)，了解如何使用 `SKILL: create-pr` 共享它。

# 创建符号分析 skill

## vtable 示例

以 `CCSPlayerPawn` 为例，让Claude Code通过调用SKILL来自动创建vtable-finder预处理脚本并更新config。

* opencode也可以自动识别.claude/skills下的SKILL.md，但是codex需要你自行创建.claude/skills <==> .codex/skills的符号链接才能识别仓库内的已有SKILL。

```text
/create-preprocessor-scripts Create "find-CCSPlayerPawn_vtable" in server.
```

## 普通函数示例

本例先定位 `CItemDefuser_Spawn`，再利用它查找 `CBaseModelEntity_SetModel`。

### 1. 在 IDA 中定位目标符号

搜索 `weapons/models/defuser/defuser.vmdl`，并在其 cross-reference 中查找以下模式：

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

包含该代码片段的函数为 `CItemDefuser_Spawn`。

### 2. 创建 preprocessor 并更新配置

```text
/create-preprocessor-scripts Create "find-CItemDefuser_Spawn" in server by xref_strings "weapons/models/defuser/defuser.vmdl" "defuser_dropped", where CItemDefuser_Spawn is a vfunc of CItemDefuser_vtable.
```

```text
/create-preprocessor-scripts Create "find-CBaseModelEntity_SetModel" in server by LLM_DECOMPILE with "CItemDefuser_Spawn", where CBaseModelEntity_SetModel is a regular function being called in "CItemDefuser_Spawn".
```

## 全局变量示例

本例定位 `IGameSystem_InitAllSystems_pFirst`。

### 1. 在 IDA 中定位目标符号

- 搜索 `IGameSystem::InitAllSystems`；引用该字符串的函数就是 `IGameSystem_InitAllSystems`。
- 如有需要，将其重命名为 `IGameSystem_InitAllSystems`。
- 在函数开头附近查找 `( i = qword_XXXXXX; i; i = *(_QWORD *)(i + 8) )`。
- 如有需要，将该 `qword_XXXXXX` 重命名为 `IGameSystem_InitAllSystems_pFirst`。

### 2. 创建 preprocessor 并更新配置

```text
/create-preprocessor-scripts Create "find-IGameSystem_InitAllSystems" in server by xref_strings "IGameSystem::InitAllSystems", where IGameSystem_InitAllSystems is a regular func.
```

```text
/create-preprocessor-scripts Create "find-IGameSystem_InitAllSystems_pFirst" in server by LLM_DECOMPILE with "IGameSystem_InitAllSystems", where IGameSystem_InitAllSystems_pFirst is a global variable being used in "IGameSystem_InitAllSystems".
```

## 结构体偏移示例

本例定位 `CGameResourceService_m_pEntitySystem`。

### 1. 在 IDA 中定位目标符号

- 搜索 `CGameResourceService::BuildResourceManifest(start)` 并检查其 cross-reference。
- cross-reference 应指向 `CGameResourceService_BuildResourceManifest`。如有需要将其重命名。

### 2. 创建 preprocessor 并更新配置

```text
/create-preprocessor-scripts Create "find-CGameResourceService_BuildResourceManifest" in engine by xref_strings "CGameResourceService::BuildResourceManifest(start)", where CGameResourceService_BuildResourceManifest is a vfunc of CGameResourceService_vtable.
```

```text
/create-preprocessor-scripts Create "find-CGameResourceService_m_pEntitySystem" in engine by LLM_DECOMPILE with "CGameResourceService_BuildResourceManifest", where CGameResourceService_m_pEntitySystem is a struct offset.
```

## 补丁示例

补丁 skill 会在已知函数内定位特定指令，并生成替换字节来修改运行时行为，例如强制或跳过分支、NOP 某次调用。目标函数通常应已有对应的 find-skill 输出，一般通过 `expected_input` 提供。

务必确保 ida-pro-mcp server 正在运行。人类贡献者应为每个新符号编写新的初始提示词，不要直接复制示例提示词。

本例将 `CCSPlayer_MovementServices_FullWalkMove` 内速度限制逻辑对应的 `jbe` 补丁为无条件 `jmp`。

### 1. 在 IDA 中定位目标指令

反编译 `CCSPlayer_MovementServices_FullWalkMove`，查找速度限制条件：

```c
v20 = (float)((float)(v16 * v16) + (float)(v19 * v19)) + (float)(v17 * v17);
if ( v20 > (float)(v18 * v18) )
{
  ...velocity clamping logic...
}
```

在比较附近反汇编，定位 `comiss` 与条件跳转：

```asm
addss   xmm2, xmm1
comiss  xmm2, xmm0
jbe     loc_XXXXXXXX
```

根据指令编码确定补丁字节：

- Near `jbe`（`0F 86 rel32`，6 字节）改为 `E9 <new_rel32> 90`（`jmp` 加 `nop`）。
- Short `jbe`（`76 rel8`，2 字节）改为 `EB rel8`（`jmp short`）。

### 2. 创建 preprocessor 并更新配置

```text
/create-preprocessor-scripts Create "find-CCSPlayer_MovementServices_FullWalkMove" in server with SKILL.md support. the SKILL.md should follow what we did via ida-pro-mcp.
```
