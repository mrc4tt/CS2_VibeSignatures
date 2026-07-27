[返回中文 README](../../README_CN.md) | [English](../en/analysis.md)

# 二进制获取与符号分析

## 下载 CS2 depot

下载配置的 depot 版本，再将目标二进制复制到工作区：

```bash
uv run download_depot.py -tag 14156

uv run copy_depot_bin.py -gamever 14156 -platform all-platform
uv run copy_depot_bin.py -gamever 14156 -platform all-platform -checkonly
```

当只需要确认 `bin/<gamever>/...` 下的目标二进制是否齐全时，可在 CI 或预检查脚本中使用 `-checkonly`。该模式只检查目标路径，不要求 `cs2_depot` 已准备完成；全部就绪时返回 `0`，缺少任一目标文件时返回 `1`，配置或参数错误时返回 `2`。

定时的 `Bump Download` GitHub Actions 工作流会维护 `download.yaml`。它通过 `bump_download.py` 查询 CS2 default branch，仅在发现的 `PatchVersion` 和 depot manifest 需要新增记录时追加条目，创建对应的本地 commit 与 tag，并由工作流推送。

在不写入 Git 状态的情况下本地预览：

```bash
uv run bump_download.py -config download.yaml -depotdir cs2_depot -dry-run
```

如果 DepotDownloader 需要登录，可追加工作流中使用的 `-username`、`-password` 和 `-remember-password` 参数。

## 分析配置中的符号

Analyzer 为 `configs/<GAMEVER>.yaml` 声明的符号查找并生成 signatures。

命令概要：

```bash
uv run ida_analyze_bin.py -gamever 14156 [-oldgamever=14155] [-configyaml=path/to/custom.yaml] [-modules=server] [-skill=find-CBaseEntity_vtable] [-platform=windows] [-agent=claude/codex/opencode/"claude.cmd"/"codex.cmd"/"opencode.cmd"] [-maxretry=3] [-vcall_finder=g_pNetworkMessages] [-llm_model=gpt-4o] [-llm_apikey=your-key] [-llm_baseurl=https://api.example.com/v1] [-llm_temperature=0.2] [-llm_effort=medium] [-llm_fake_as=codex] [-rename] [-debug]
```

共享 LLM 参数：

- `-llm_apikey`：启用 LLM 流程时必需，包括 `vcall_finder` 聚合与 `LLM_DECOMPILE`。
- `-llm_baseurl`：可选的兼容 base URL；使用 `-llm_fake_as=codex` 时必填。
- `-llm_model`：可选，默认 `gpt-4o`。
- `-llm_temperature`：可选，仅在显式设置时发送。
- `-llm_effort`：可选，默认 `medium`；支持 `none|minimal|low|medium|high|xhigh`。
- `-llm_fake_as`：可选；设为 `codex` 时改用直连 `/v1/responses` 的 SSE 传输。
- 环境变量 fallback：`CS2VIBE_LLM_APIKEY`、`CS2VIBE_LLM_BASEURL`、`CS2VIBE_LLM_MODEL`、`CS2VIBE_LLM_TEMPERATURE`、`CS2VIBE_LLM_EFFORT` 和 `CS2VIBE_LLM_FAKE_AS`。
- LLM 流程不会读取 `OPENAI_API_KEY`、`OPENAI_API_BASE` 或 `OPENAI_API_MODEL`。

Analyzer 行为：

- 在运行 Agent skills 前，先通过 MCP 尝试复用 `bin/{previous_gamever}/{module}/{symbol}.{platform}.yaml` 中的旧 signature。成功复用时不会消耗 Agent token。
- `-agent="claude.cmd"` 选择 Windows 上通过 npm 安装的 Claude CLI。
- `-agent="opencode.cmd"` 选择 Windows 上通过 npm 安装的 OpenCode CLI。OpenCode 会加载 `.opencode/agents/sig-finder.md` 并以非交互模式运行 skills。
- 推荐顺序为：纯程序化 preprocessor、`LLM_DECOMPILE` preprocessor、Agent skill。
- `-skill=<exact-name>` 只在当前 `-modules` 过滤范围内运行名称完全匹配的 skill。它不会自动运行前置 skill；必需的 `expected_input` artifact 必须已存在。
- `-rename` 对已有 expected-output YAML 执行 rename/comment 后处理。

进度上报、Redis Scheduler 和进度看板见[进度上报、调度与看板](process-monitoring.md)。

## `vcall_finder`

- `-vcall_finder=g_pNetworkMessages` 显式选择一个或多个逗号分隔的对象名。使用时必须显式传入 `-modules=...`；每个对象都会在每个选定模块中处理，且不支持 `*`。
- `vcall_finder` 对象不注册到 `configs/<GAMEVER>.yaml`。如果对象在所有选定模块和平台中均不存在，命令会失败，不会聚合旧的 detail 文件。
- 脚本会把引用函数的完整反汇编与伪代码导出到 `vcall_finder/{gamever}/{object_name}/{module}/{platform}/`，所有模块与平台的 IDA 任务结束后再运行 LLM 聚合。
- 若 detail YAML 已有顶层 `found_vcall`，该函数会跳过 LLM 调用并复用缓存。成功响应会立即把 `found_vcall: [...]` 或 `found_vcall: []` 回写到 detail YAML。
- `vcall_finder/{gamever}/{object_name}.txt` 是追加写入的 YAML document stream；每条记录直接包含 `insn_va`、`insn_disasm` 和 `vfunc_offset`，不再嵌套 `found_vcall`。

示例：

```bash
uv run ida_analyze_bin.py -gamever=14141 -modules=networksystem -platform=windows -vcall_finder=g_pNetworkMessages -llm_model=gpt-5.4 -llm_apikey=your-key -llm_effort=high -llm_fake_as=codex -llm_baseurl=http://127.0.0.1:8080/v1
```

输出示例：

- `vcall_finder/14141/g_pNetworkMessages/networksystem/windows/sub_140123450.yaml`
- `vcall_finder/14141/g_pNetworkMessages.txt`

## IDA preprocessor 字符串配置

`CS2VIBE_STRING_MIN_LENGTH` 只控制 preprocessor 枚举字符串时可选的 IDA string-list 配置：

- 未设置或为空：不调用 `idautils.Strings.setup`，使用 IDB 当前 string-list 状态。
- 整数 `>=1`：当前 IDB 尚未用同样参数配置时，调用 `idautils.Strings.setup(strtypes=[ida_nalt.STRTYPE_C], minlen=<value>)`。
- 非整数或 `<1`：回退到 `4`，并使用同一个 IDB 级 setup guard。
- setup 状态按 IDB 保存；修改有效 `minlen` 会再次触发 setup。
- 该变量不是 LLM 参数。

准备 `LLM_DECOMPILE` 输入时继续阅读[`LLM_DECOMPILE` reference YAML](reference-yaml.md)。创建 immutable candidate 并执行 downstream validation 时继续阅读[Snapshot 与 gamedata](snapshot-and-gamedata.md)。
