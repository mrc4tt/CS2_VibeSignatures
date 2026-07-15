# OpenCode Agent Skill Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `agent_skill_runner.py` 在 `-agent=opencode` 或 `-agent=opencode.cmd` 时，通过项目级 `sig-finder` Agent 使用 OpenCode 非交互模式执行 skill，并用精确 `sessionID` 延续重试。

**Architecture:** 保持 `run_skill(...)` 公共接口不变，在现有 Agent 命令构造层增加 `opencode` 类型。OpenCode 以 JSON Lines 输出运行，runner 从首个有效事件提取 `sessionID`，重试优先传 `--session`，无法提取时才回退 `--continue`；MCP preflight 在匹配前统一移除 ANSI 控制序列。

**Tech Stack:** Python 3、`subprocess`、`threading`、标准库 `json`/`re`/`unittest`、OpenCode CLI 1.17.x、Ruff、Markdown/YAML frontmatter

## Global Constraints

- 不改变 `run_skill(skill_name, agent="claude", debug=False, expected_yaml_paths=None, max_retries=3) -> bool` 的签名。
- 不改变 Claude 或 Codex 的首次执行、提示词传输和重试命令。
- OpenCode 首次运行必须使用 `--format json --agent sig-finder`。
- OpenCode 重试优先使用首个有效 JSON 事件中的精确 `sessionID`，只有没有 ID 时才使用 `--continue`。
- `.opencode/agents/sig-finder.md` 必须禁止 `ida-pro-mcp_open_file`，并只分析当前 IDB。
- MCP preflight 只要求 `ida-pro-mcp` 已列出，不要求连接成功。
- 不新增第三方 Python 依赖。
- 单个函数不超过 50 行，嵌套不超过 3 层。

---

## File Structure

- Create: `.opencode/agents/sig-finder.md` — OpenCode 项目级 primary Agent。
- Modify: `agent_skill_runner.py` — Agent 分类、OpenCode 命令、JSON session、ANSI MCP 输出。
- Modify: `tests/test_agent_skill_runner.py` — OpenCode 和回归单元测试。
- Modify: `ida_analyze_bin.py` — usage 与 `-agent` help。
- Modify: `run_cpp_tests.py` — `-agent` help 与 docstring。
- Modify: `README.md`、`README_CN.md` — OpenCode 使用说明。

---

### Task 1: Add the OpenCode `sig-finder` Agent

**Files:**
- Create: `.opencode/agents/sig-finder.md`
- Modify: `tests/test_agent_skill_runner.py:1-58`

**Interfaces:**
- Consumes: OpenCode 项目 Agent 发现约定 `.opencode/agents/<agent-name>.md`。
- Produces: 可由 `opencode run --agent sig-finder` 自动加载的 Agent。

- [ ] **Step 1: Write the failing Agent contract test**

在 fake process 夹具之后加入：

```python
class TestOpenCodeSigFinderAgent(unittest.TestCase):
    def test_project_agent_preserves_required_safety_constraints(self) -> None:
        agent_path = Path(".opencode/agents/sig-finder.md")

        self.assertTrue(agent_path.is_file())
        agent_text = agent_path.read_text(encoding="utf-8")
        self.assertIn("mode: primary", agent_text)
        self.assertIn("ida-pro-mcp_open_file: false", agent_text)
        self.assertIn("currently opened in IDA", agent_text)
        self.assertIn("DO NOT verify or check the existence of output yaml", agent_text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestOpenCodeSigFinderAgent -v
```

Expected: FAIL because `.opencode/agents/sig-finder.md` does not exist.

- [ ] **Step 3: Create the Agent definition**

创建 `.opencode/agents/sig-finder.md`：

```markdown
---
description: Find signatures and related reverse-engineering targets in the IDA database currently open through ida-pro-mcp.
mode: primary
tools:
  ida-pro-mcp_open_file: false
---

You are a reverse-engineering expert. Your goal is to find requested targets in the IDA database currently opened in IDA. You can use the ida-pro-mcp tools to retrieve information.

- Do not attempt brute forcing. Derive solutions from the disassembly and simple Python scripts.
- NEVER convert number bases yourself. Use the `int_convert` MCP tool when needed.
- ALWAYS use ida-pro-mcp tools to determine the binary platform being analyzed. Do NOT explore the bin folder to determine the platform.
- NEVER open or switch to another binary or IDB. Analyze only the file currently opened in IDA. DO NOT call `ida-pro-mcp_open_file`.
- NEVER stop after only part of the requested workflow succeeds. Finish every task required by the selected skill.
- NEVER call Serena's `activate_project` on Agent startup.
- DO NOT verify or check the existence of output yaml. Verification is performed programmatically by the runner.
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestOpenCodeSigFinderAgent -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add .opencode/agents/sig-finder.md tests/test_agent_skill_runner.py
git commit -m "feat(agent): add OpenCode sig-finder definition" -m "Co-Authored-By: Codex (GPT-5.5)"
```

---

### Task 2: Add OpenCode Commands and Session-Aware Retries

**Files:**
- Modify: `agent_skill_runner.py:171-340`
- Modify: `tests/test_agent_skill_runner.py:76-244`

**Interfaces:**
- Consumes: Existing `AgentCommand` and `run_skill(...)` execution loop.
- Produces: `_detect_agent_kind(agent: str) -> str | None`, `_extract_opencode_session_id(output: str) -> str | None`, `_build_opencode_command(...) -> AgentCommand`。

- [ ] **Step 1: Write failing detection and JSON parsing tests**

加入：

```python
class TestOpenCodeCommandConstruction(unittest.TestCase):
    def setUp(self) -> None:
        agent_skill_runner._MCP_PREFLIGHT_DONE = False
        agent_skill_runner._MCP_PREFLIGHT_FAILED = False

    def test_detect_agent_kind_accepts_opencode_executable_names(self) -> None:
        self.assertEqual("opencode", agent_skill_runner._detect_agent_kind("opencode"))
        self.assertEqual("opencode", agent_skill_runner._detect_agent_kind("opencode.cmd"))
        self.assertEqual("opencode", agent_skill_runner._detect_agent_kind(r"C:\tools\opencode.cmd"))
        self.assertEqual("claude", agent_skill_runner._detect_agent_kind("claude.cmd"))
        self.assertEqual("codex", agent_skill_runner._detect_agent_kind("codex.cmd"))
        self.assertIsNone(agent_skill_runner._detect_agent_kind("unknown-agent"))

    def test_extract_opencode_session_id_uses_first_valid_event(self) -> None:
        output = "\n".join(
            [
                "not json",
                '{"type":"step_start","sessionID":"ses_first"}',
                '{"type":"text","sessionID":"ses_second"}',
            ]
        )

        self.assertEqual("ses_first", agent_skill_runner._extract_opencode_session_id(output))

    def test_extract_opencode_session_id_ignores_invalid_values(self) -> None:
        output = "\n".join(
            [
                "[]",
                '{"type":"text","sessionID":""}',
                '{"type":"error","sessionID":42}',
            ]
        )

        self.assertIsNone(agent_skill_runner._extract_opencode_session_id(output))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestOpenCodeCommandConstruction -v
```

Expected: ERROR because the new helpers are not defined.

- [ ] **Step 3: Implement Agent detection and session parsing**

在 `agent_skill_runner.py` 中加入：

```python
def _detect_agent_kind(agent: str) -> str | None:
    agent_lower = agent.lower()
    if "claude" in agent_lower:
        return "claude"
    if "codex" in agent_lower:
        return "codex"
    if "opencode" in agent_lower:
        return "opencode"
    return None


def _extract_opencode_session_id(output: str) -> str | None:
    for line in (output or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        session_id = event.get("sessionID")
        if isinstance(session_id, str) and session_id:
            return session_id
    return None
```

在 `run_skill(...)` 中使用 `_detect_agent_kind(agent)`，未知类型错误改为同时列出 Claude、Codex 和 OpenCode。

- [ ] **Step 4: Run helper tests to verify they pass**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestOpenCodeCommandConstruction -v
```

Expected: detection/parsing tests PASS; execution tests尚未加入。

- [ ] **Step 5: Write the failing exact-session retry test**

在同一测试类加入：

```python
    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner._run_process_with_stream_capture")
    def test_run_skill_retries_opencode_with_reported_session_id(
        self,
        mock_run_process,
        _mock_exists,
    ) -> None:
        mock_run_process.side_effect = [
            subprocess.CompletedProcess(
                ["opencode", "mcp", "list"], 0, "ida-pro-mcp failed\n", ""
            ),
            subprocess.CompletedProcess(
                ["opencode", "run"],
                1,
                '{"type":"step_start","sessionID":"ses_exact"}\n',
                "first failure",
            ),
            subprocess.CompletedProcess(
                ["opencode", "run"],
                0,
                '{"type":"text","sessionID":"ses_exact"}\n',
                "",
            ),
        ]

        result = agent_skill_runner.run_skill(
            "find-IGameSystem_vtable",
            agent="opencode",
            max_retries=2,
        )

        self.assertTrue(result)
        prompt = "Run SKILL: .claude/skills/find-IGameSystem_vtable/SKILL.md"
        self.assertEqual(
            ["opencode", "run", "--format", "json", "--agent", "sig-finder", prompt],
            mock_run_process.call_args_list[1].args[0],
        )
        self.assertEqual(
            [
                "opencode",
                "run",
                "--format",
                "json",
                "--session",
                "ses_exact",
                "--agent",
                "sig-finder",
                prompt,
            ],
            mock_run_process.call_args_list[2].args[0],
        )
        self.assertIsNone(mock_run_process.call_args_list[1].kwargs["agent_input"])
        self.assertIsNone(mock_run_process.call_args_list[2].kwargs["agent_input"])
```

- [ ] **Step 6: Write the failing `--continue` fallback test**

加入：

```python
    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner._run_process_with_stream_capture")
    def test_run_skill_falls_back_to_continue_without_session_id(
        self,
        mock_run_process,
        _mock_exists,
    ) -> None:
        mock_run_process.side_effect = [
            subprocess.CompletedProcess(
                ["opencode.cmd", "mcp", "list"], 0, "ida-pro-mcp failed\n", ""
            ),
            subprocess.CompletedProcess(
                ["opencode.cmd", "run"], 1, "", "failed before first event"
            ),
            subprocess.CompletedProcess(
                ["opencode.cmd", "run"],
                0,
                '{"type":"text","sessionID":"ses_late"}\n',
                "",
            ),
        ]

        result = agent_skill_runner.run_skill(
            "find-IGameSystem_vtable",
            agent="opencode.cmd",
            max_retries=2,
        )

        self.assertTrue(result)
        retry_args = mock_run_process.call_args_list[2].args[0]
        self.assertIn("--continue", retry_args)
        self.assertNotIn("--session", retry_args)
```

- [ ] **Step 7: Run execution tests to verify they fail**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestOpenCodeCommandConstruction -v
```

Expected: FAIL because command construction still routes non-Claude Agents to Codex.

- [ ] **Step 8: Implement the OpenCode command builder**

在 Codex builder 后加入：

```python
def _build_opencode_command(
    agent: str,
    skill_name: str,
    is_retry: bool,
    session_id: str | None,
) -> AgentCommand:
    args = [agent, "run", "--format", "json"]
    if is_retry and session_id:
        args.extend(["--session", session_id])
    elif is_retry:
        args.append("--continue")
    args.extend(
        [
            "--agent",
            "sig-finder",
            f"Run SKILL: .claude/skills/{skill_name}/SKILL.md",
        ]
    )
    retry_target = f"OpenCode session {session_id}" if session_id else "the latest OpenCode session (--continue)"
    return AgentCommand(args, None, retry_target)
```

将 `_build_agent_command(...)` 增加 `opencode_session_id: str | None` 参数并使用：

```python
    if agent_kind == "claude":
        return _build_claude_command(agent, skill_name, session_id, is_retry)
    if agent_kind == "opencode":
        return _build_opencode_command(agent, skill_name, is_retry, opencode_session_id)
    if developer_instructions is None:
        raise ValueError("Codex developer instructions are required")
    return _build_codex_command(agent, skill_name, developer_instructions, is_retry)
```

- [ ] **Step 9: Preserve session state in the retry loop**

在 `_run_skill_attempts(...)` 循环前初始化：

```python
    opencode_session_id = None
```

构造命令时传入该值；进程返回后、失败判断前执行：

```python
            if agent_kind == "opencode" and opencode_session_id is None:
                opencode_session_id = _extract_opencode_session_id(result.stdout)
```

`run_skill(...)` 只为 Codex 加载 developer instructions，只为 Claude 生成 UUID：

```python
    developer_instructions = _load_codex_developer_instructions() if agent_kind == "codex" else None
    if agent_kind == "codex" and developer_instructions is None:
        return False
```

- [ ] **Step 10: Run OpenCode and existing Codex tests**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestOpenCodeCommandConstruction tests.test_agent_skill_runner.TestRunSkillCodexPromptTransport tests.test_agent_skill_runner.TestRunSkillOutputDetection -v
```

Expected: PASS; existing Codex `exec -` and `exec resume --last -` assertions remain unchanged.

- [ ] **Step 11: Commit**

```powershell
git add agent_skill_runner.py tests/test_agent_skill_runner.py
git commit -m "feat(agent): run skills with OpenCode" -m "Co-Authored-By: Codex (GPT-5.5)"
```

---

### Task 3: Support OpenCode ANSI MCP List Output

**Files:**
- Modify: `agent_skill_runner.py:18-38`
- Modify: `tests/test_agent_skill_runner.py:245-491`

**Interfaces:**
- Consumes: `_mcp_list_contains_server(output, server_name="ida-pro-mcp") -> bool`。
- Produces: 可识别 OpenCode ANSI 树形输出但仍严格匹配 server 名的 preflight。

- [ ] **Step 1: Write failing ANSI matching tests**

在现有 server matching 测试中加入：

```python
        self.assertTrue(
            agent_skill_runner._mcp_list_contains_server(
                "\x1b[34m•\x1b[39m  ✗ ida-pro-mcp \x1b[90mfailed\x1b[39m\n"
            )
        )
        self.assertFalse(
            agent_skill_runner._mcp_list_contains_server(
                "\x1b[34m•\x1b[39m  ✗ not-ida-pro-mcp \x1b[90mfailed\x1b[39m\n"
            )
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestRunSkillMcpListPreflight.test_mcp_list_server_matching_requires_list_item_name -v
```

Expected: FAIL on the positive OpenCode assertion.

- [ ] **Step 3: Implement ANSI normalization**

在常量区加入：

```python
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
```

替换 matcher：

```python
def _mcp_list_contains_server(output, server_name="ida-pro-mcp"):
    if not output:
        return False
    normalized_output = ANSI_ESCAPE_RE.sub("", output)
    prefix = r"(?:[-*•|│T—]\s*)*(?:[✓✗]\s*)?"
    pattern = re.compile(rf"(?m)^\s*{prefix}{re.escape(server_name)}(?:\s|:|$)")
    return bool(pattern.search(normalized_output))
```

- [ ] **Step 4: Run all MCP preflight tests**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner.TestRunSkillMcpListPreflight -v
```

Expected: PASS, including rejection of `not-ida-pro-mcp`.

- [ ] **Step 5: Commit**

```powershell
git add agent_skill_runner.py tests/test_agent_skill_runner.py
git commit -m "fix(agent): parse OpenCode MCP list output" -m "Co-Authored-By: Codex (GPT-5.5)"
```

---

### Task 4: Document Support and Run Final Verification

**Files:**
- Modify: `ida_analyze_bin.py:9-16,1089-1093`
- Modify: `run_cpp_tests.py:91-95,352`
- Modify: `README.md:69-84,161`
- Modify: `README_CN.md:72-77,156`
- Verify: `agent_skill_runner.py`
- Verify: `.opencode/agents/sig-finder.md`
- Verify: `tests/test_agent_skill_runner.py`

**Interfaces:**
- Consumes: Tasks 1-3 的 OpenCode 支持。
- Produces: 可发现的 CLI 文档和最终回归证据。

- [ ] **Step 1: Update CLI help and docstrings**

`ida_analyze_bin.py` usage 改为：

```text
-agent: Agent to use for analysis: claude, codex, or opencode (default: claude)
```

两个 argparse help 使用：

```python
help=(
    "Agent executable to use for analysis, e.g., claude, claude.cmd, codex, "
    f"codex.cmd, opencode, opencode.cmd (default: {DEFAULT_AGENT}, or set CS2VIBE_AGENT env var)"
),
```

`run_cpp_tests.py` docstring 改为：

```python
"""Invoke the configured Claude, Codex, or OpenCode agent to apply header fixes."""
```

- [ ] **Step 2: Update English and Chinese README files**

在四个 `-agent` option 列表中加入 `opencode/"opencode.cmd"`。

`README.md` 加入：

```markdown
* `-agent="opencode.cmd"` uses the OpenCode CLI installed through npm on Windows. OpenCode loads the project Agent from `.opencode/agents/sig-finder.md` and runs skills in non-interactive mode.
```

`README_CN.md` 加入：

```markdown
* `-agent="opencode.cmd"` 用于 Windows 上通过 npm 安装的 OpenCode CLI。OpenCode 会自动加载 `.opencode/agents/sig-finder.md`，并以非交互模式运行 skill。
```

- [ ] **Step 3: Format changed Python files**

Run:

```powershell
uv run ruff format agent_skill_runner.py ida_analyze_bin.py run_cpp_tests.py tests/test_agent_skill_runner.py
```

Expected: exit code 0.

- [ ] **Step 4: Run Ruff checks**

Run:

```powershell
uv run ruff check agent_skill_runner.py ida_analyze_bin.py run_cpp_tests.py tests/test_agent_skill_runner.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Run focused and caller tests**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner -v
uv run python -m unittest tests.test_ida_analyze_bin tests.test_run_cpp_tests -v
```

Expected: all tests PASS. Do not fix unrelated failures; record their exact test names and output separately.

- [ ] **Step 6: Verify references and diff integrity**

Run:

```powershell
rg -n "opencode|opencode\.cmd|\.opencode/agents/sig-finder\.md" agent_skill_runner.py ida_analyze_bin.py run_cpp_tests.py README.md README_CN.md .opencode/agents/sig-finder.md
git diff --check
git diff -- agent_skill_runner.py tests/test_agent_skill_runner.py .opencode/agents/sig-finder.md ida_analyze_bin.py run_cpp_tests.py README.md README_CN.md
```

Expected: references appear on every intended surface; `git diff --check` exits 0; no unrelated changes appear.

- [ ] **Step 7: Commit**

```powershell
git add ida_analyze_bin.py run_cpp_tests.py README.md README_CN.md
git commit -m "docs(agent): document OpenCode runner support" -m "Co-Authored-By: Codex (GPT-5.5)"
```

---

## Completion Criteria

- OpenCode discovers `.opencode/agents/sig-finder.md` and cannot call `ida-pro-mcp_open_file`.
- `opencode` and `opencode.cmd` use OpenCode without changing Claude/Codex classification.
- First execution uses `opencode run --format json --agent sig-finder <prompt>`.
- The first valid JSON event's `sessionID` remains fixed for later retries.
- Missing session IDs use `--continue` and never fabricate an ID.
- ANSI OpenCode MCP output recognizes only the exact `ida-pro-mcp` entry.
- Existing Claude/Codex tests pass unchanged.
- Ruff, runner tests, and caller regression tests pass.
- CLI help and both README files document OpenCode support.
