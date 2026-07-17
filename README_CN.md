# CS2 VibeSignatures

[English README](README.md)

这是一个主要用于为 CS2 生成 signatures/offsets，并通过 Agent SKILLS 与 MCP Calls 更新 HL2SDK_CS2 C++ 头文件的项目。

该项目的设计目标是在**完全无需人工参与**的情况下更新 signatures/offsets/cpp headers。

目前，本项目已可自动更新 **CounterStrikeSharp** 和 **CS2Fixes** 的全部 signatures/offsets。

## 依赖要求

1. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)

2. [depotdownloader](https://github.com/steamre/depotdownloader) (需要将depotdownloader.exe所在目录添加到PATH中)

3. `uv sync`

4. claude / codex

5. IDA Pro 9.0+

6. [ida-pro-mcp](https://github.com/mrexodia/ida-pro-mcp)

7. [idalib](https://docs.hex-rays.com/user-guide/idalib)（运行 `ida_analyze_bin.py` 的必需项）

8. Clang-LLVM（运行 `run_cpp_tests.py` 的必需项，需要将clang.exe所在目录添加到PATH中）

## 代码格式化

本仓库使用 `ruff format` 格式化由 git 管理的 `*.py` 文件，并使用 `yamlfix` 格式化由 git 管理的 `*.yaml` 文件。

提交前可在本地运行格式化：

```bash
uv run python format_repo_files.py
```

运行与 GitHub Actions 相同的格式化检查：

```bash
uv run python format_repo_files.py --check
```

格式化脚本只处理 `git ls-files --cached -- '*.py' '*.yaml'` 返回的文件，因此会跳过已被 ignore 的文件和未跟踪的临时文件。`ida_preprocessor_scripts/references/` 下的生成 YAML 与 `gamesymbols/` 下的 canonical lockfile 也会被跳过，由各自生成器保证 byte-stable 格式。

## 整体工作流

### 1. 下载 CS2 二进制文件并复制dll/so到工作目录

```bash
uv run download_depot.py -tag 14156

uv run copy_depot_bin.py -gamever 14146 -platform all-platform
uv run copy_depot_bin.py -gamever 14146 -platform all-platform -checkonly
```

当只需要确认 `bin/<gamever>/...` 下的目标二进制是否已经齐全时，可在 CI 或预检查脚本中使用 `-checkonly`。该模式只检查目标路径，不要求 `cs2_depot` 已准备完成；当所有目标文件都已就绪时返回 `0`，缺少任一目标文件时返回 `1`，配置或参数错误时返回 `2`。

定时的 `Bump Download` GitHub Actions 工作流会维护这份下载清单。它通过 `bump_download.py` 查询 CS2 default branch，只有当发现的 `PatchVersion` 与 depot manifest 需要新增记录时，才追加 `download.yaml`，创建对应本地 commit/tag，并由工作流推送。若只想本地预览且不写入 git 状态，可运行：

```bash
uv run bump_download.py -config download.yaml -depotdir cs2_depot -dry-run
```

如果 DepotDownloader 需要登录，可追加工作流中同样使用的 `-username`、`-password` 与 `-remember-password` 参数。


### 2. 为 `configs/<GAMEVER>.yaml` 的符号生成对应 signatures

 ```bash
 uv run ida_analyze_bin.py -gamever=14146 [-oldgamever=14145] [-configyaml=path/to/custom.yaml] [-modules=server] [-platform=windows] [-agent=claude/codex/opencode/"claude.cmd"/"codex.cmd"/"opencode.cmd"] [-maxretry=3] [-vcall_finder=g_pNetworkMessages|*] [-llm_model=gpt-4o] [-llm_apikey=your-key] [-llm_baseurl=https://api.example.com/v1] [-llm_temperature=0.2] [-llm_effort=medium] [-llm_fake_as=codex] [-debug]
 ```

* 在真正运行 Agent SKILL(s) 前，会先通过 mcp call 直接使用 `bin/{previous_gamever}/{module}/{symbol}.{platform}.yaml` 中的旧 signature 查找当前版本游戏二进制中的符号。不会消耗 token。

* `-agent="claude.cmd"` 用于Windows上使用npm安装的claude cli

* `-agent="opencode.cmd"` 用于 Windows 上通过 npm 安装的 OpenCode CLI。OpenCode 会自动加载 `.opencode/agents/sig-finder.md`，并以非交互模式运行 skill。

* 共享 LLM CLI 参数：
  - `-llm_apikey`：启用基于 LLM 的流程时必需，包括 `vcall_finder` 聚合与 `LLM_DECOMPILE`
  - `-llm_baseurl`：可选，自定义兼容 base URL；启用 `-llm_fake_as=codex` 时必填
  - `-llm_model`：可选，默认 `gpt-4o`
  - `-llm_temperature`：可选，仅在显式设置时发送
  - `-llm_effort`：可选，默认 `medium`，支持 `none|minimal|low|medium|high|xhigh`
  - `-llm_fake_as`：可选，设为 `codex` 时改走直连 `/v1/responses` 的 SSE 传输
  - 环境变量 fallback：`CS2VIBE_LLM_APIKEY`、`CS2VIBE_LLM_BASEURL`、`CS2VIBE_LLM_MODEL`、`CS2VIBE_LLM_TEMPERATURE`、`CS2VIBE_LLM_EFFORT`、`CS2VIBE_LLM_FAKE_AS`
  - LLM 流程不会读取 `OPENAI_API_KEY`、`OPENAI_API_BASE`、`OPENAI_API_MODEL`

* 推荐实务中优先使用：纯程序化的预处理脚本 > 基于 LLM_DECOMPILE 的自动化反编译 > `SKILL.md`

* 当指定了 `-rename` 时, 会根据已有的YAML里的信息来自动重命名所有已知的函数

* Redis 进度上报为可选功能。可设置 `CS2VIBE_PROCESS_REPORTER=redis` 与
  `CS2VIBE_REDIS_URL=redis://127.0.0.1:6379/0`，或使用等价的 `-process_reporter=redis`、`-redis_url=...` 和可选的
  `-redis_prefix=...` 参数。Reporter 会写入不可变 ExecutionPlan、Run/Job/Skill 最新快照、事件 Stream、原子汇总计数
  与带 TTL 的 heartbeat。Redis 暂时不可用不会改变 Analyzer 结果，恢复连接后会重放最新本地快照。

* 可使用 `uv run python process_scheduler_cli.py submit --gamever 14141 --agent codex` 提交任务，再通过
  `uv run python process_scheduler_cli.py run` 启动单并发 Scheduler。Redis Stream Consumer Group 会保持 FIFO 顺序、
  在 Scheduler 重启后恢复 pending entry，并在 Analyzer heartbeat 仍有效时避免重复启动。队列只接受经过校验的结构化
  字段，不执行 Redis payload 中的任意 shell 命令。

* 可使用 `uv run uvicorn process_api:app --host 127.0.0.1 --port 8000` 启动只读进度 API。主要接口包括
  `/api/v1/runs`、`/api/v1/runs/{run_id}/snapshot`、`/tasks`、`/events` 和 `/stream`。页面应先读取 snapshot，
  再以 `snapshot_event_id` 作为 `after` 建立 SSE；断线后可通过 `Last-Event-ID` 恢复。服务默认仅监听本机且不内置认证，
  对外部署时应置于认证反向代理之后。跨域来源可通过 `CS2VIBE_API_CORS_ORIGINS` 配置，SSE block 和 batch 分别使用
  `CS2VIBE_SSE_BLOCK_MS`、`CS2VIBE_SSE_BATCH_SIZE` 调整；`/healthz` 和 `/readyz` 分别用于存活与 Redis 就绪检查。
  `pages/` 中的 React 看板可通过 `npm ci && npm run build` 构建。公网 Pages 页面连接浏览器同机 FastAPI 时，需将
  Pages 的精确 Origin 加入 `CS2VIBE_API_CORS_ORIGINS`，并设置 `CS2VIBE_API_ALLOW_PRIVATE_NETWORK=true` 响应浏览器
  私有网络预检。Pages CDN 无法访问另一台机器的 localhost；启用私有网络访问时也禁止使用通配 Origin。

#### vcall_finder 相关

* `-vcall_finder=g_pNetworkMessages` 会在模块级 `vcall_finder` 配置中筛选同名对象；`-vcall_finder=*` 会处理 `configs/<GAMEVER>.yaml` 中声明的全部对象。

* 当启用 `-vcall_finder` 时，脚本会在每个模块/平台完成 IDA 任务后导出对象引用函数的完整反汇编与伪代码到 `vcall_finder/{gamever}/{object_name}/{module}/{platform}/`，并在全部模块/平台结束后执行 LLM 聚合；若某个 detail YAML 已存在顶层 `found_vcall`，则会跳过该次 LLM 调用，直接复用缓存结果。

* LLM 成功返回后，会立刻将 `found_vcall: [...]` 或 `found_vcall: []` 回写到对应的 detail YAML，后续重跑可直接跳过该函数的 LLM 调用。

* `vcall_finder/{gamever}/{object_name}.txt` 现在是按 YAML document stream 追加的扁平记录；每条记录直接包含 `insn_va`、`insn_disasm`、`vfunc_offset`，不再嵌套 `found_vcall:`。

```bash
uv run ida_analyze_bin.py -gamever=14141 -modules=networksystem -platform=windows -vcall_finder=g_pNetworkMessages -llm_model=gpt-5.4 -llm_apikey=sk -llm_effort=high -llm_fake_as=codex -llm_baseurl=http://127.0.0.1:8080/v1
```

输出示例：

- `vcall_finder/14141/g_pNetworkMessages/networksystem/windows/sub_140123450.yaml`
- `vcall_finder/14141/g_pNetworkMessages.txt`

#### LLM_DECOMPILE reference YAML 相关

reference YAML 存放路径：

- `ida_preprocessor_scripts/references/<module>/<func_name>.<platform>.yaml`

准备步骤：

1. 确认目标函数已有当前版本 YAML 且包含 `func_va`，或可通过 `configs/<GAMEVER>.yaml` 的 symbol name/alias 在 IDA 中定位。
2. 运行独立 CLI：

```bash
uv run generate_reference_yaml.py -gamever 14141 CNetworkGameClient_RecordEntityBandwidth -mcp_host 127.0.0.1 -mcp_port 13337
```

自动启动 `idalib-mcp` 示例：

```bash
uv run generate_reference_yaml.py -gamever 14141 -module engine -platform windows -func_name CNetworkGameClient_RecordEntityBandwidth -auto_start_mcp -binary "bin/14141/engine/engine2.dll"
```

3. 检查生成文件：
   - `func_va` 可信
   - `disasm_code` 非空，且与目标函数语义匹配
   - `procedure` 在可用时应与预期语义一致（Hex-Rays 不可用时允许为空字符串）
   - `func_name` 仅用于确认输出文件对应你请求的规范名，不能单独证明地址解析正确
4. 在目标 `find-*.py` 脚本里接入 `LLM_DECOMPILE`：
   - 生成文件在仓库中的路径：
     - `ida_preprocessor_scripts/references/<module>/<func_name>.<platform>.yaml`
   - 若 `LLM_DECOMPILE` 使用相对路径，应写成：
     - `references/<module>/<func_name>.<platform>.yaml`
   - 每个配置项必须显式声明允许的结果 section：

     ```python
     {
         "symbol_name": "INetworkMessages_FindNetworkGroup",
         "prompt_path": "prompt/call_llm_decompile.md",
         "reference_yaml_paths": [
             "references/engine/CNetworkGameClient_RecordEntityBandwidth.{platform}.yaml",
         ],
         "expected_result_sections": ["found_vcall"],
     }
     ```

   - 合法 section 包括 `found_call`、`found_vcall`、`found_funcptr`、`found_gv` 和 `found_struct_offset`。
   - 同一 symbol 需要多个 reference 时，应写入同一个 `reference_yaml_paths` 列表，不要声明多个重复 spec。
   - `LLM_DECOMPILE` 复用 `ida_analyze_bin.py` 的共享 `-llm_*` 参数：`-llm_model`、`-llm_apikey`、`-llm_baseurl`、`-llm_temperature`、`-llm_effort`、`-llm_fake_as`

### 3. 将 yaml(s) 转换为 gamedata json / txt

```bash
uv run update_gamedata.py -gamever 14168 -snapshot gamesymbols/14168.yaml [-debug]
```

### 4. 运行 C++ 测试并检查 cpp headers 是否与 yaml(s) 匹配

```bash
uv run run_cpp_tests.py -gamever 14168 -snapshot gamesymbols/14168.yaml [-debug]
```

需要修复报告的 `hl2sdk_cs2` header 差异时，使用项目级 `fix-cppheaders` SKILL。该 SKILL 会自行调用
`run_cpp_tests.py` 获取最新 layout diff，并在修改后重复验证。

### 5. 发布、恢复与验证 game-symbol snapshot

单个 symbol YAML 继续作为 ignored 文件保存在 `bin/<GAMEVER>/<module>/`。Git 跟踪的 canonical analysis
lockfile 为 `gamesymbols/<GAMEVER>.yaml`，其正式文件集合由 `configs/<GAMEVER>.yaml` 声明的 required / optional YAML
输出推导。

top-level analysis transaction 成功后立即 strict pack 一次 candidate。两个 downstream consumer 只读取同一个
immutable candidate；全部 validation 成功后，publication 只复制 candidate 原始字节：

```bash
CANDIDATE_DIR="$(mktemp -d)"
CANDIDATE_SNAPSHOT="$CANDIDATE_DIR/14168.yaml"
CANDIDATE_SESSION="$CANDIDATE_DIR/14168.session.json"
uv run gamesymbol_candidate.py build -gamever 14168 -bindir bin -configyaml configs/14168.yaml -output "$CANDIDATE_SNAPSHOT" -session "$CANDIDATE_SESSION"
uv run update_gamedata.py -gamever 14168 -configyaml configs/14168.yaml -snapshot "$CANDIDATE_SNAPSHOT"
uv run gamesymbol_candidate.py mark -candidate "$CANDIDATE_SNAPSHOT" -session "$CANDIDATE_SESSION" -step gamedata
uv run run_cpp_tests.py -gamever 14168 -configyaml configs/14168.yaml -snapshot "$CANDIDATE_SNAPSHOT"
uv run gamesymbol_candidate.py mark -candidate "$CANDIDATE_SNAPSHOT" -session "$CANDIDATE_SESSION" -step cpp_tests
uv run gamesymbol_candidate.py publish -candidate "$CANDIDATE_SNAPSHOT" -session "$CANDIDATE_SESSION" -snapshot gamesymbols/14168.yaml
```

可使用以下命令恢复确定性分析基线，或只读验证当前 workspace：

```bash
uv run gamesymbol_snapshot.py restore -gamever 14168
uv run gamesymbol_snapshot.py restore -gamever 14168 -replace
uv run gamesymbol_snapshot.py verify -gamever 14168
```

默认 restore 只创建缺失 YAML，并拒绝覆盖语义不同的文件。`-replace` 只删除 `bin/<GAMEVER>/` 下的 YAML，
保留二进制与 IDA database，再重建 snapshot 内容。candidate `build` 与 low-level/bootstrap `pack` 会拒绝
缺失 required output 与 undeclared YAML；`verify` 还会强制检查 canonical bytes 和两类 round-trip。

可能影响分析输出的 PR 必须同时提交对应的 `gamesymbols/<GAMEVER>.yaml` 更新。PR CI 会恢复 base snapshot，
按 snapshot / config / source 变化 invalidates producer，运行 analyzer，strict-pack actual candidate，再与 PR
head snapshot 比较。head snapshot 只表示 expected result；两个 downstream consumer 都读取 actual candidate，
普通 PR workflow 不会 publish 或改写 tracked snapshot。

### 当前支持的 gamedata

[CounterStrikeSharp](https://github.com/roflmuffin/CounterStrikeSharp)

`dist/CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json`

 - `GameEventManager`：在CSS中已废弃。
 - `CEntityResourceManifest_AddResource`：游戏更新时基本不会改动。

[CS2Fixes](https://github.com/Source2ZE/CS2Fixes)

`dist/CS2Fixes/gamedata/cs2fixes.games.txt`

 - `CCSPlayerPawn_GetMaxSpeed`，因为它并不存在于 `server.dll` 中。

[swiftlys2](https://github.com/swiftly-solution/swiftlys2)

`dist/swiftlys2/plugin_files/gamedata/cs2/core/offsets.jsonc`

`dist/swiftlys2/plugin_files/gamedata/cs2/core/signatures.jsonc`

[plugify](https://github.com/untrustedmodders/plugify-plugin-s2sdk)

`dist/plugify-plugin-s2sdk/assets/gamedata.jsonc`

[cs2kz-metamod](https://github.com/KZGlobalTeam/cs2kz-metamod)

`dist/cs2kz-metamod/gamedata/cs2kz-core.games.txt`

[modsharp](https://github.com/Kxnrl/modsharp-public)

`dist/modsharp-public/.asset/gamedata/core.games.jsonc`

`dist/modsharp-public/.asset/gamedata/engine.games.jsonc`

`dist/modsharp-public/.asset/gamedata/EntityEnhancement.games.jsonc`

`dist/modsharp-public/.asset/gamedata/log.games.jsonc`

`dist/modsharp-public/.asset/gamedata/server.games.jsonc`

`dist/modsharp-public/.asset/gamedata/tier0.games.jsonc`

 - 已跳过 230 个符号。

[CS2Surf/Timer](https://github.com/CS2Surf-CN/Timer)

`dist/cs2surf/gamedata/cs2surf-core.games.jsonc`

 - 已跳过 26 个符号。

## 如何为 vtable 创建 SKILL

以 `CCSPlayerPawn` 为例。

Claude Code:

```
/create-preprocessor-scripts Create "find-CCSPlayerPawn_vtable" in server.
```

## 如何为函数创建 SKILL

### 以 `CItemDefuser_Spawn` 和 `CBaseModelEntity_SetModel` 为例

#### 1. 在 IDA 中查找目标符号

  - 在 IDA 中搜索字符串 `"weapons/models/defuser/defuser.vmdl"`，在其 xrefs 里找如下模式的代码片段：

```c
    v2 = a2;
    v3 = (__int64)a1;
    sub_180XXXXXX(a1, (__int64)"weapons/models/defuser/defuser.vmdl"); //This is CBaseModelEntity_SetModel, rename it to CBaseModelEntity_SetModel
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

包含该代码片段的函数为： `CItemDefuser_Spawn`

#### 2. 创建预处理脚本并更新 `configs/<GAMEVER>.yaml`

Claude Code:

```
/create-preprocessor-scripts Create "find-CItemDefuser_Spawn" in server by xref_strings "weapons/models/defuser/defuser.vmdl", where CItemDefuser_Spawn is a vfunc of CItemDefuser_vtable.
```

Claude Code:

```
/create-preprocessor-scripts Create "find-CBaseModelEntity_SetModel" in server by LLM_DECOMPILE with "CItemDefuser_Spawn", where CBaseModelEntity_SetModel is a regular function being called in "CItemDefuser_Spawn".
```

## 如何为全局变量创建 SKILL

### 以 `IGameSystem_InitAllSystems_pFirst` 为例

#### 1. 在 IDA 中查找目标符号

  - 在 IDA 中搜索字符串 `"IGameSystem::InitAllSystems"`，查找该字符串的 xrefs。引用该字符串的函数就是 `IGameSystem_InitAllSystems`。

  - 如果还没改名，请将其重命名为 `IGameSystem_InitAllSystems`。

  - 查看 `IGameSystem_InitAllSystems` 开头附近的模式：`( i = qword_XXXXXX; i; i = *(_QWORD *)(i + 8) )`

  - 如果还没改名，将前一步发现的 `qword_XXXXXX` 重命名为 `IGameSystem_InitAllSystems_pFirst`。

#### 2. 创建预处理脚本并更新 `configs/<GAMEVER>.yaml`

Claude Code:

```
/create-preprocessor-scripts Create "find-IGameSystem_InitAllSystems" in server by xref_strings "IGameSystem::InitAllSystems", where IGameSystem_InitAllSystems is a regular func.
```

Claude Code:

```
/create-preprocessor-scripts Create "find-IGameSystem_InitAllSystems_pFirst" in server by LLM_DECOMPILE with "IGameSystem_InitAllSystems", where IGameSystem_InitAllSystems_pFirst is a global variable being used in "IGameSystem_InitAllSystems".
```

## 如何为结构体偏移创建 SKILL

以 `CGameResourceService_m_pEntitySystem` 为例。

#### 1. 在 IDA 中查找目标符号

  - 在 IDA 中搜索字符串 `"CGameResourceService::BuildResourceManifest(start)"`，并查找其 xrefs。

  - xref 应指向一个函数——这就是 `CGameResourceService_BuildResourceManifest`。如果尚未改名，请将其重命名。

#### 2. 创建预处理脚本并更新 `configs/<GAMEVER>.yaml`

Claude Code:

```
/create-preprocessor-scripts Create "find-CGameResourceService_BuildResourceManifest" in engine by xref_strings "CGameResourceService::BuildResourceManifest(start)" , where CGameResourceService_BuildResourceManifest is a vfunc of CGameResourceService_vtable.
```

```
/create-preprocessor-scripts Create "find-CGameResourceService_m_pEntitySystem" in engine by LLM_DECOMPILE with "CGameResourceService_BuildResourceManifest", where CGameResourceService_m_pEntitySystem is a struct offset.
```

## 如何为补丁创建 SKILL

* 补丁 SKILL 会在一个已知函数里定位特定指令，并生成替换字节来修改其运行时行为（例如强制/跳过某分支、NOP 掉某次调用）。目标函数通常应已有对应的 find-SKILL 输出（一般通过 `expected_input` 提供）。

* 务必确保 ida-pro-mcp server 正在运行。

* 对于人类贡献者：当你查找新符号时，应编写新的初始提示词，**不要**从 README 直接复制粘贴！

以 `CCSPlayer_MovementServices_FullWalkMove_SpeedClamp` 为例 —— 在 `CCSPlayer_MovementServices_FullWalkMove` 内把速度限制逻辑对应的 `jbe` 补丁为无条件 `jmp`。

#### 1. 在 IDA 中查找目标符号

  - 反编译 `CCSPlayer_MovementServices_FullWalkMove`，查找类似“某 float > 某 float 平方”的代码模式：

```c
  v20 = (float)((float)(v16 * v16) + (float)(v19 * v19)) + (float)(v17 * v17);
  if ( v20 > (float)(v18 * v18) )
  {
    ...velocity clamping logic...
  }
```

  - 在比较附近反汇编，找到确切的条件跳转指令。

  - 在比较地址附近反汇编，定位 `comiss + jbe` 指令对。

```
  期望的汇编模式：
    addss   xmm2, xmm1          ; v20 = sum of squares
    comiss  xmm2, xmm0          ; compare v20 vs v18*v18
    jbe     loc_XXXXXXXX         ; skip clamp block if v20 <= v18*v18
```

  - 根据指令编码确定补丁字节。

```
  * Near `jbe` (`0F 86 rel32`，6 字节) → `E9 <new_rel32> 90`（无条件 `jmp` + `nop`）
  * Short `jbe` (`76 rel8`，2 字节) → `EB rel8`（无条件 `jmp short`）
```

#### 2. 创建预处理脚本并更新 `configs/<GAMEVER>.yaml`

按照 [`.claude/skills/create-preprocessor-scripts/SKILL.md`](.claude/skills/create-preprocessor-scripts/SKILL.md) 创建预处理脚本，并更新指定的 `configs/<GAMEVER>.yaml`。

## 故障排查

### error: could not create 'ida.egg-info': access denied

处理方式：在 `C:\Program Files\IDA Professional 9.0\idalib\python` 目录下，以**管理员权限**运行 `python py-activate-idalib.py`。

### Could not find idalib64.dll in .........

处理方式：尝试 `set IDADIR=C:\Program Files\IDA Professional 9.0`，或将 `IDADIR=C:\Program Files\IDA Professional 9.0` 添加到系统环境变量。

## Jenkins 工作流参考

```bash
@echo Download latest game binaries

uv run download_bin.py -gamever %CS2_GAMEVER%
```

```bash
@echo Analyze game binaries

uv run ida_analyze_bin.py -gamever %CS2_GAMEVER% -agent="claude.cmd" -platform %CS2_PLATFORM% -debug
```

```bash
@echo Build the immutable candidate immediately after analysis

set CANDIDATE_ID=%RANDOM%
set CANDIDATE_SNAPSHOT=%TEMP%\gamesymbol-%CS2_GAMEVER%-%CANDIDATE_ID%.yaml
set CANDIDATE_SESSION=%TEMP%\gamesymbol-%CS2_GAMEVER%-%CANDIDATE_ID%.session.json
uv run gamesymbol_candidate.py build -gamever %CS2_GAMEVER% -bindir bin -configyaml configs/%CS2_GAMEVER%.yaml -output %CANDIDATE_SNAPSHOT% -session %CANDIDATE_SESSION%
```

```bash
@echo Update gamedata from the candidate snapshot

uv run update_gamedata.py -gamever %CS2_GAMEVER% -snapshot %CANDIDATE_SNAPSHOT% -debug
uv run gamesymbol_candidate.py mark -candidate %CANDIDATE_SNAPSHOT% -session %CANDIDATE_SESSION% -step gamedata
```

```bash
@echo Find mismatches in CS2SDK headers

uv run run_cpp_tests.py -gamever %CS2_GAMEVER% -snapshot %CANDIDATE_SNAPSHOT% -debug
uv run gamesymbol_candidate.py mark -candidate %CANDIDATE_SNAPSHOT% -session %CANDIDATE_SESSION% -step cpp_tests
uv run gamesymbol_candidate.py publish -candidate %CANDIDATE_SNAPSHOT% -session %CANDIDATE_SESSION% -snapshot gamesymbols/%CS2_GAMEVER%.yaml
```
