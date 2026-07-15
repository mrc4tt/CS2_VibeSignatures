# Agent Skill Runner Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `run_skill(...)` 及其 Agent 启动、MCP preflight、命令构造、重试和进程输出处理逻辑从 `ida_analyze_bin.py` 提取到独立的 `agent_skill_runner.py`，并把对应单元测试迁移到独立测试文件，同时保持现有行为和 `process_binary(...)` 调用接口不变。

**Architecture:** `agent_skill_runner.py` 作为独立的 Agent Skill 执行层，对外只暴露兼容的 `run_skill(...)`。`ida_analyze_bin.py` 通过直接导入保留模块级 `run_skill` 名称，使主流程和现有 `patch.object(ida_analyze_bin, "run_skill", ...)` 测试 seam 不变；runner 内部按“提示词加载、命令构造、进程执行、preflight、重试编排”拆成小函数。测试同步按模块归属迁移，主流程测试继续留在 `tests/test_ida_analyze_bin.py`。

**Tech Stack:** Python 3.10+、`unittest`、`unittest.mock`、`subprocess`、`threading`、`dataclasses`、Ruff

## Global Constraints

- 本次是行为保持型重构，不改变 `run_skill(...)` 的参数、返回值、日志文本、超时值、重试次数语义或 YAML 产物校验规则。
- 保留当前进程级 `_MCP_PREFLIGHT_DONE` / `_MCP_PREFLIGHT_FAILED` 单一缓存语义；按 Agent/Server 分键缓存另开后续改动。
- `process_binary(...)` 继续通过 `ida_analyze_bin.run_skill` 调用，避免改变现有主流程测试 patch seam。
- 不新增第三方依赖，不调整根配置、CI 或环境模板。
- 遵循函数不超过 50 行、嵌套不超过 3 层的仓库约束；通过小 helper 降低 `run_skill(...)` 复杂度。
- 当前实施计划不要求自动创建 git commit；如用户另行要求，提交信息使用 `refactor(agent): extract skill runner`，并追加规定的 Co-Authored-By。

---

## File Structure

- Create: `agent_skill_runner.py`
  - 定义 Agent Skill 执行层常量、preflight 状态、命令描述数据结构和全部 runner helper。
  - 对外提供与当前完全兼容的 `run_skill(...) -> bool`。
- Modify: `ida_analyze_bin.py`
  - 导入 `agent_skill_runner.run_skill`。
  - 删除已经迁移的 runner 常量、状态、helper 和原 `run_skill(...)` 实现。
  - 保持 `process_binary(...)` 调用代码不变。
- Create: `tests/test_agent_skill_runner.py`
  - 迁移 fake pipe/process 夹具。
  - 迁移输出错误检测、Codex prompt transport、Claude 工具限制、MCP preflight 缓存相关测试。
  - 所有 patch target 改为 `agent_skill_runner.*`。
- Modify: `tests/test_ida_analyze_bin.py`
  - 删除只属于 runner 的夹具与测试类。
  - 保留所有 `process_binary(...)` 对 `ida_analyze_bin.run_skill` 的 mock 测试。

### Task 1: 迁移 Agent runner 专属测试并建立模块边界

**Files:**
- Create: `tests/test_agent_skill_runner.py`
- Modify: `tests/test_ida_analyze_bin.py:3087-3554`

**Interfaces:**
- Consumes: 当前 `ida_analyze_bin.run_skill(...)` 的既有行为和测试断言。
- Produces: 面向新模块的测试入口 `agent_skill_runner.run_skill(...)`，以及 runner 私有 helper 的模块内测试边界。

- [ ] **Step 1: 新建 runner 测试文件并迁移测试夹具**

创建 `tests/test_agent_skill_runner.py`，使用以下导入和已有 fake process 夹具：

```python
import io
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_skill_runner


class _FakePipe:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def readline(self) -> str:
        return self._chunks.pop(0) if self._chunks else ""

    def close(self) -> None:
        self.closed = True


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.closed = False

    def write(self, data: str) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakePopen:
    def __init__(
        self,
        *,
        stdout_chunks: list[str] | None = None,
        stderr_chunks: list[str] | None = None,
        returncode: int = 0,
    ) -> None:
        self.stdout = _FakePipe(stdout_chunks or [])
        self.stderr = _FakePipe(stderr_chunks or [])
        self.stdin = _FakeStdin()
        self.returncode = returncode
        self.killed = False

    def wait(self, timeout: int | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
```

- [ ] **Step 2: 迁移三个 runner 测试类并调整模块引用**

把以下现有测试类从 `tests/test_ida_analyze_bin.py` 移入新文件，测试方法和断言保持不变：

```text
TestRunSkillOutputDetection
TestRunSkillCodexPromptTransport
TestRunSkillMcpListPreflight
```

对迁移内容执行这些精确替换：

```python
# 目标模块
ida_analyze_bin.run_skill                  -> agent_skill_runner.run_skill
ida_analyze_bin._output_contains_error_marker -> agent_skill_runner._output_contains_error_marker
ida_analyze_bin._mcp_list_contains_server -> agent_skill_runner._mcp_list_contains_server
ida_analyze_bin._MCP_PREFLIGHT_DONE        -> agent_skill_runner._MCP_PREFLIGHT_DONE
ida_analyze_bin._MCP_PREFLIGHT_FAILED      -> agent_skill_runner._MCP_PREFLIGHT_FAILED
ida_analyze_bin.SKILL_TIMEOUT              -> agent_skill_runner.SKILL_TIMEOUT

# 标准库对象
ida_analyze_bin.subprocess.CompletedProcess -> subprocess.CompletedProcess

# patch target
"ida_analyze_bin.os.path.exists"                    -> "agent_skill_runner.os.path.exists"
"ida_analyze_bin.subprocess.Popen"                  -> "agent_skill_runner.subprocess.Popen"
"ida_analyze_bin._run_process_with_stream_capture" -> "agent_skill_runner._run_process_with_stream_capture"
```

保留每个测试类的 `setUp()`，确保每个用例开始前重置 preflight 状态：

```python
def setUp(self) -> None:
    agent_skill_runner._MCP_PREFLIGHT_DONE = False
    agent_skill_runner._MCP_PREFLIGHT_FAILED = False
```

- [ ] **Step 3: 从主流程测试文件删除已迁移内容**

从 `tests/test_ida_analyze_bin.py` 删除 `_FakePipe`、`_FakeStdin`、`_FakePopen` 和上述三个测试类。不要删除文件顶部的 `io`、`subprocess` 或 `Path` 导入，因为该文件其他测试仍在使用它们。

- [ ] **Step 4: 运行新测试，确认模块尚未实现时失败**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner -v
```

Expected: FAIL，错误为 `ModuleNotFoundError: No module named 'agent_skill_runner'`。

### Task 2: 创建行为保持的 `agent_skill_runner.py`

**Files:**
- Create: `agent_skill_runner.py`
- Test: `tests/test_agent_skill_runner.py`

**Interfaces:**
- Consumes: `.claude/skills/<skill_name>/SKILL.md`、`.claude/agents/sig-finder.md`、Claude/Codex CLI、`ida-pro-mcp` 配置。
- Produces: `run_skill(skill_name, agent="claude", debug=False, expected_yaml_paths=None, max_retries=3) -> bool`。

- [ ] **Step 1: 建立模块常量、状态与命令描述结构**

创建模块头部：

```python
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


SKILL_TIMEOUT = 1200
MCP_LIST_TIMEOUT = 30
ERROR_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])error(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_MCP_PREFLIGHT_DONE = False
_MCP_PREFLIGHT_FAILED = False


@dataclass(frozen=True)
class AgentCommand:
    args: list[str]
    input_text: str | None
    retry_target_desc: str
```

- [ ] **Step 2: 迁移无行为变化的输出、preflight 和进程 helper**

从 `ida_analyze_bin.py` 原样迁移 `_output_contains_error_marker`、`_mcp_list_contains_server`、`_format_mcp_list_output`、`_ensure_agent_mcp_preflight`、`_drain_text_stream` 和 `_run_process_with_stream_capture` 的完整函数体，并只调整它们对本模块常量/helper 的引用。源代码位置分别为当前 `ida_analyze_bin.py:128-190` 和 `ida_analyze_bin.py:2093-2153`；迁移后旧文件中的对应定义会在 Task 3 删除。

不得更改以下行为：preflight 成功/失败只缓存一次；只要列表中出现 `ida-pro-mcp` 名称，即使连接状态为 Failed 也视为配置存在；`debug=True` 实时转发双流，`debug=False` 只缓存不转发；超时后 kill 子进程并重新抛出 `TimeoutExpired`。

- [ ] **Step 3: 提取 Codex prompt 加载函数**

实现以下接口，将当前 frontmatter 去除和错误处理完整迁移进来：

```python
def _strip_optional_frontmatter(prompt: str) -> str:
    stripped = prompt.strip()
    if not stripped.startswith("---"):
        return stripped

    lines = stripped.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return stripped


def _load_codex_developer_instructions(
    system_prompt_path: Path = Path(".claude/agents/sig-finder.md"),
) -> str | None:
    try:
        raw_prompt = system_prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"    Error: Codex system prompt file not found: {system_prompt_path}")
        return None
    except OSError as error:
        print(f"    Error: Failed to read Codex system prompt from {system_prompt_path}: {error}")
        return None

    prompt = _strip_optional_frontmatter(raw_prompt)
    if not prompt:
        print(f"    Error: Codex system prompt is empty in {system_prompt_path}")
        return None
    return f"developer_instructions={json.dumps(prompt)}"
```

- [ ] **Step 4: 提取 Claude/Codex 命令构造函数**

实现两个纯命令构造 helper：

```python
def _build_claude_command(
    agent: str,
    skill_name: str,
    session_id: str,
    is_retry: bool,
) -> AgentCommand:
    args = [
        agent,
        "-p",
        f"/{skill_name}",
        "--agent",
        "sig-finder",
        "--allowedTools",
        "mcp__ida-pro-mcp__*",
        "--disallowedTools",
        "mcp__ida-pro-mcp__open_file",
        "--settings",
        '{"alwaysThinkingEnabled": false}',
    ]
    args.extend(["--resume" if is_retry else "--session-id", session_id])
    return AgentCommand(args, None, f"session {session_id}")


def _build_codex_command(
    agent: str,
    skill_name: str,
    developer_instructions: str,
    is_retry: bool,
) -> AgentCommand:
    args = [
        agent,
        "-c",
        developer_instructions,
        "-c",
        "model_reasoning_effort=high",
        "-c",
        "model_reasoning_summary=none",
        "-c",
        "model_verbosity=low",
        "exec",
    ]
    if is_retry:
        args.extend(["resume", "--last"])
    args.append("-")
    input_text = f"Run SKILL: .claude/skills/{skill_name}/SKILL.md"
    return AgentCommand(args, input_text, "the latest codex session (--last)")
```

- [ ] **Step 5: 提取日志脱敏和单次结果校验 helper**

实现：

```python
def _display_command(args: list[str]) -> list[str]:
    display_args = args
    for index, arg in enumerate(args[:-1]):
        if arg == "-c" and args[index + 1].startswith("developer_instructions="):
            if display_args is args:
                display_args = args.copy()
            display_args[index + 1] = "developer_instructions=<sig-finder-system-prompt>"
    return display_args


def _missing_expected_outputs(expected_yaml_paths) -> list[str]:
    if expected_yaml_paths is None:
        return []
    return [path for path in expected_yaml_paths if not os.path.exists(path)]
```

保持当前输出格式，Codex developer instructions 不得以明文打印到终端。

- [ ] **Step 6: 实现精简后的公开 `run_skill(...)`**

公开签名必须保持为一行等价定义：

```python
def run_skill(skill_name, agent="claude", debug=False, expected_yaml_paths=None, max_retries=3) -> bool:
```

实现顺序必须为：

1. 通过 agent 名称包含 `claude` / `codex` 判定类型，未知类型打印原错误并返回 `False`。
2. 校验 `.claude/skills/<skill_name>/SKILL.md` 存在。
3. 调用 `_ensure_agent_mcp_preflight(...)`。
4. Codex 模式只加载一次 developer instructions；Claude 模式只生成一次 UUID session id。
5. 每次 attempt 调用对应 command builder，并保持首次/重试命令差异。
6. 调用 `_run_process_with_stream_capture(...)`，超时使用 `SKILL_TIMEOUT`。
7. 按原顺序检查非零返回码、独立 error marker、缺失 expected YAML。
8. 任一检查失败且仍有次数时打印原 retry 文本；成功立即返回 `True`。
9. `FileNotFoundError` 立即返回 `False`；其他异常按原逻辑进入下一次重试。
10. 次数耗尽打印 `Failed after ... attempts` 并返回 `False`。

为满足函数长度约束，将 attempt 循环放入私有 helper，签名固定为：

```python
def _run_skill_attempts(
    *,
    skill_name: str,
    agent: str,
    agent_kind: str,
    session_id: str,
    developer_instructions: str | None,
    debug: bool,
    expected_yaml_paths,
    max_retries: int,
) -> bool:
```

该 helper 的完整循环逻辑直接取自当前 `run_skill(...)` 的 `for attempt in range(max_retries)` 段，并把内联命令构造替换为 `_build_claude_command(...)` / `_build_codex_command(...)`；不得省略任何现有异常分支或日志。

- [ ] **Step 7: 运行 runner 定向测试**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner -v
```

Expected: 全部 PASS；测试数量与迁移前三个测试类的方法数量一致。

### Task 3: 将主入口切换到新 runner 并清理旧实现

**Files:**
- Modify: `ida_analyze_bin.py:34-99`
- Modify: `ida_analyze_bin.py:128-190`
- Modify: `ida_analyze_bin.py:2093-2348`
- Test: `tests/test_ida_analyze_bin.py`

**Interfaces:**
- Consumes: `agent_skill_runner.run_skill(...) -> bool`。
- Produces: 继续可 patch 的 `ida_analyze_bin.run_skill` 模块级名称。

- [ ] **Step 1: 在主入口直接导入公开函数**

在项目模块导入区加入：

```python
from agent_skill_runner import run_skill
```

必须使用直接导入，不能把调用改为 `agent_skill_runner.run_skill(...)`，这样现有主流程测试中的：

```python
patch.object(ida_analyze_bin, "run_skill", return_value=False)
```

仍然有效。

- [ ] **Step 2: 删除旧 runner 实现和专属状态**

从 `ida_analyze_bin.py` 删除：

```text
SKILL_TIMEOUT
MCP_LIST_TIMEOUT
ERROR_MARKER_RE
_MCP_PREFLIGHT_DONE
_MCP_PREFLIGHT_FAILED
_output_contains_error_marker
_mcp_list_contains_server
_format_mcp_list_output
_ensure_agent_mcp_preflight
_drain_text_stream
_run_process_with_stream_capture
run_skill
```

然后依据实际引用清理不再使用的标准库导入。预期可删除：

```python
import re
import threading
import uuid
```

必须保留 `json`、`subprocess`、`sys` 和 `Path`，因为主文件其他逻辑仍在使用。

- [ ] **Step 3: 确认 `process_binary(...)` 调用代码无变化**

保留现有调用形态：

```python
if run_skill(
    skill_name,
    agent,
    debug,
    expected_yaml_paths=required_outputs,
    max_retries=skill_max_retries,
):
    success_count += 1
    print("    Success")
else:
    fail_count += 1
    print("    Failed")
    print("  Aborting remaining skills after fallback skill failure")
    abort_binary_processing = True
    break
```

不修改参数顺序、统计逻辑或 fallback 条件。

- [ ] **Step 4: 运行主入口回归测试**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin -v
```

Expected: 全部 PASS，尤其所有 patch `ida_analyze_bin.run_skill` 的 `process_binary(...)` 测试继续通过。

### Task 4: 格式化、静态检查与整合验证

**Files:**
- Verify: `agent_skill_runner.py`
- Verify: `ida_analyze_bin.py`
- Verify: `tests/test_agent_skill_runner.py`
- Verify: `tests/test_ida_analyze_bin.py`

**Interfaces:**
- Consumes: 完成拆分后的生产代码与测试。
- Produces: 行为保持、格式一致、可进入后续 review 的整合结果。

- [ ] **Step 1: 格式化本次涉及文件**

Run:

```powershell
uv run ruff format agent_skill_runner.py ida_analyze_bin.py tests/test_agent_skill_runner.py tests/test_ida_analyze_bin.py
```

Expected: 命令退出码为 0。

- [ ] **Step 2: 执行 Ruff 检查**

Run:

```powershell
uv run ruff check agent_skill_runner.py ida_analyze_bin.py tests/test_agent_skill_runner.py tests/test_ida_analyze_bin.py
```

Expected: `All checks passed!`。

- [ ] **Step 3: 重新执行两个直接相关测试模块**

Run:

```powershell
uv run python -m unittest tests.test_agent_skill_runner tests.test_ida_analyze_bin -v
```

Expected: 全部 PASS。

- [ ] **Step 4: 执行全量测试**

Run:

```powershell
uv run python -m unittest discover -s tests
```

Expected: 退出码为 0，且无新增 failure/error。

- [ ] **Step 5: 审查最终 diff 和模块边界**

Run:

```powershell
git diff --check
git diff --stat
git status --short
```

Expected:

- `git diff --check` 无输出且退出码为 0。
- 生产代码变化集中在新增 `agent_skill_runner.py` 和精简 `ida_analyze_bin.py`。
- runner 专属测试集中在 `tests/test_agent_skill_runner.py`。
- 用户现有未跟踪文件 `1.log` 保持未修改、未纳入变更。

## Acceptance Criteria

- `ida_analyze_bin.py` 不再包含 Agent CLI 命令构造、MCP list preflight、流式子进程捕获或 `run_skill(...)` 实现。
- `agent_skill_runner.py` 对外提供兼容的 `run_skill(...)`，Claude/Codex 首次执行与重试命令保持不变。
- `process_binary(...)` 调用和 `ida_analyze_bin.run_skill` patch seam 保持不变。
- 原三个 runner 测试类完整迁移，新旧测试文件职责清晰且没有重复测试。
- 定向测试、主入口测试、全量测试及 Ruff 检查均通过。
- 本次不改变 preflight 缓存粒度，不引入任何额外行为调整。
