# OpenCode Agent Skill Runner 支持设计

## 背景

`agent_skill_runner.py` 当前只识别 Claude 和 Codex CLI，并负责 Agent 命令构造、MCP preflight、超时、输出采集、失败检测和重试。

本次增加 OpenCode 非交互模式支持。当调用方传入 `-agent=opencode` 或 `-agent=opencode.cmd` 时，runner 应使用项目内的 OpenCode 自定义 Agent 执行 skill，而不是落入 Claude 或 Codex 分支。

## 目标

- 支持 `opencode` 和 `opencode.cmd` 两种可执行文件名。
- 使用 `opencode run` 非交互执行项目 skill。
- 使用项目级 `.opencode/agents/sig-finder.md` 提供逆向分析 Agent 指令。
- 从 OpenCode JSON 事件中捕获精确 `sessionID`，保证重试延续正确会话。
- 保留现有超时、错误标记检测、预期 YAML 校验和 debug 输出行为。
- 让现有 MCP preflight 能识别 OpenCode 的 ANSI 树形输出。

## 非目标

- 不改变 Claude 或 Codex 的命令、提示词和重试语义。
- 不增加 OpenCode provider、model 或认证配置。
- 不调整 `.claude/agents/sig-finder.md` 的现有行为。
- 不引入 OpenCode SDK、常驻服务或远程 attach 模式。
- 不支持一个 runner 进程内并行执行多个 skill。

## Agent 定义

新增 `.opencode/agents/sig-finder.md`。

Frontmatter 使用 OpenCode 当前支持的 Markdown Agent 格式：

```yaml
---
description: Find signatures and related reverse-engineering targets in the IDA database currently open through ida-pro-mcp.
mode: primary
tools:
  ida-pro-mcp_open_file: false
---
```

正文复用 `.claude/agents/sig-finder.md` 去除 Claude 专用 frontmatter 后的核心行为指令，特别保留以下约束：

- 只分析 IDA 当前打开的二进制或 IDB。
- 禁止调用 `ida-pro-mcp` 的 `open_file`。
- 使用 MCP 工具判断目标平台。
- 完成 skill 的全部步骤后才结束。
- 不自行验证输出 YAML 是否存在，由 runner 统一验证。

只显式禁用 `ida-pro-mcp_open_file`，其余工具继承项目 OpenCode 配置。这样 Agent 仍可加载 `.claude/skills/<skill>/SKILL.md` 及其引用资源。

## Agent 识别

runner 将 Agent 分为 `claude`、`codex` 和 `opencode` 三类。

输入值 `opencode` 和 `opencode.cmd` 必须识别为 `opencode`。识别逻辑继续兼容调用方传入可执行文件路径的情况，不改变现有 Claude/Codex 名称匹配结果。

未知 Agent 的错误信息更新为同时列出 `claude`、`codex` 和 `opencode`。

## 命令构造

OpenCode 首次执行使用：

```text
opencode run --format json --agent sig-finder "Run SKILL: .claude/skills/<skill-name>/SKILL.md"
```

提示词作为独立 argv 参数传递，不通过 shell 拼接，也不通过 stdin 传递。

首次执行产生 JSON Lines。每个有效 OpenCode JSON 事件都包含顶层 `sessionID`。runner 从 stdout 中读取第一个非空、可解析且包含非空字符串 `sessionID` 的事件，并将该 ID 保存到当前 skill 的重试循环中。

捕获到 ID 后，重试使用：

```text
opencode run --format json --session <sessionID> --agent sig-finder "Run SKILL: .claude/skills/<skill-name>/SKILL.md"
```

若执行在产生任何有效 JSON 事件前失败，runner 无法取得 ID，则下一次重试回退为：

```text
opencode run --format json --continue --agent sig-finder "Run SKILL: .claude/skills/<skill-name>/SKILL.md"
```

`--session` 优先级始终高于 `--continue`。一旦捕获到 `sessionID`，后续所有重试固定使用该 ID，不再查询或依赖最近会话。

## MCP Preflight

所有 Agent 仍执行 `<agent> mcp list`，并要求输出中列出 `ida-pro-mcp`。连接状态可以是成功或失败，只要 server 已配置即可继续。

OpenCode 输出可能包含 ANSI 控制序列和如下树形行：

```text
opencode mcp list

┌  MCP Servers
│
●  ✗ ida-pro-mcp failed
│      SSE error: Unable to connect. Is the computer able to access the url?
│      http://127.0.0.1:13337/mcp
│
●  ✓ serena connected
│      http://127.0.0.1:9131/mcp
│
└  2 server(s)
```

匹配前先移除 ANSI CSI 序列，再允许常见列表符、树形符和状态符出现在 server 名称前。匹配仍限定为单独的 server 名，不能把 `not-ida-pro-mcp`、URL 或错误描述中的子串误判为目标 server。

## 输出与失败处理

OpenCode 使用 `--format json` 后，stdout 保持原始 JSON Lines：

- `debug=True` 时继续实时转发原始 stdout/stderr。
- `debug=False` 时继续静默采集。
- 返回码非零时判定失败。
- 输出中出现独立 `error` 标记时沿用现有失败检测并重试；OpenCode 的 `{"type":"error"}` 事件会自然命中该规则。
- 缺少 required YAML 输出时沿用现有失败检测并重试。
- 超时、找不到可执行文件和其他异常沿用现有处理。

本次不把 JSON 事件重新渲染成人类可读文本，避免扩大 runner 的展示职责。

## 代码边界

生产代码修改集中在：

- `agent_skill_runner.py`：Agent 分类、OpenCode 命令构造、session ID 提取、ANSI MCP 输出兼容和重试状态传递。
- `.opencode/agents/sig-finder.md`：OpenCode 项目 Agent 定义。
- `ida_analyze_bin.py`、`run_cpp_tests.py`：更新 `-agent` help 文本。
- `README.md`、`README_CN.md`：列出 `opencode` 和 `opencode.cmd`。

不改变 `run_skill(...)` 的公开函数签名，现有调用点无需适配。

## 测试设计

在 `tests/test_agent_skill_runner.py` 增加定向单元测试：

1. `opencode` 与 `opencode.cmd` 均进入 OpenCode 分支。
2. 首次命令包含 `run --format json --agent sig-finder` 和 skill 提示词。
3. 首次失败输出中的 `sessionID` 被提取，重试命令使用精确 `--session <id>`。
4. 未取得 `sessionID` 时重试使用 `--continue`。
5. 后续事件包含其他 ID 或其他 OpenCode session 存在时，不覆盖首次捕获的 ID。
6. OpenCode ANSI 树形 MCP 列表能识别 `ida-pro-mcp`。
7. 相似 server 名仍不能通过 preflight。
8. Claude/Codex 现有命令断言保持不变。

增加对 `.opencode/agents/sig-finder.md` 的轻量文件测试，确认：

- Agent 为 `primary` 模式。
- 禁用 `ida-pro-mcp_open_file`。
- 包含只分析当前 IDB 和不自行验证 YAML 的核心约束。

## 验证

实现后执行：

```powershell
uv run ruff format agent_skill_runner.py ida_analyze_bin.py run_cpp_tests.py tests/test_agent_skill_runner.py
uv run ruff check agent_skill_runner.py ida_analyze_bin.py run_cpp_tests.py tests/test_agent_skill_runner.py
uv run python -m unittest tests.test_agent_skill_runner -v
uv run python -m unittest tests.test_ida_analyze_bin tests.test_run_cpp_tests -v
```

若本机 OpenCode 配置和 provider 可用，再进行一次不触发真实 IDA 修改的手工命令构造或最小 smoke 验证；自动化验收不依赖外部模型调用。

## 验收标准

- `-agent=opencode` 和 `-agent=opencode.cmd` 使用 OpenCode 非交互模式。
- OpenCode 使用项目 `.opencode/agents/sig-finder.md`。
- 正常产生 JSON 事件后，重试精确恢复同一个 `sessionID`。
- 无法取得 ID 时才使用 `--continue` 回退。
- OpenCode 的 ANSI MCP 列表可以通过现有 preflight 门禁。
- Claude/Codex 行为和 `run_skill(...)` API 保持兼容。
- 定向格式化、lint 和单元测试通过。
