"""Agent CLI execution, MCP preflight, retries, and output validation."""

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


SKILL_TIMEOUT = 1200
HEADER_FIX_TIMEOUT = 600
MCP_LIST_TIMEOUT = 30
ERROR_MARKER_RE = re.compile(r"(?<![A-Za-z0-9])error(?![A-Za-z0-9])", re.IGNORECASE)
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MCP_PREFLIGHT_DONE = False
_MCP_PREFLIGHT_FAILED = False
CLAUDE_SKILL_RUNNER_SETTINGS = ".claude/skill_runner.settings.json"
SKILL_RUNNER_SYSTEM_PROMPT = ".claude/SKILL_RUNNER.md"
OPENCODE_SKILL_RUNNER_CONFIG = ".opencode/skill_runner.config.json"


@dataclass(frozen=True)
class AgentCommand:
    args: list[str]
    input_text: str | None
    retry_target_desc: str


@dataclass(frozen=True)
class HeaderFixContext:
    fix_prompt: str
    agent: str
    agent_kind: str
    developer_instructions: str | None
    debug: bool
    max_retries: int
    claude_session_id: str
    is_continuation: bool
    claude_allowed_tools: str
    claude_permission_mode: str
    claude_extra_args: str


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


def _output_contains_error_marker(*texts: str) -> bool:
    merged_output = "\n".join(text for text in texts if text)
    return bool(ERROR_MARKER_RE.search(merged_output))


def _mcp_list_contains_server(output, server_name="ida-pro-mcp"):
    if not output:
        return False
    normalized_output = ANSI_ESCAPE_RE.sub("", output)
    prefix = r"(?:[-*•|│T—]\s*)*(?:[✓✗]\s*)?"
    pattern = re.compile(rf"(?m)^\s*{prefix}{re.escape(server_name)}(?:\s|:|$)")
    return bool(pattern.search(normalized_output))


def _format_mcp_list_output(output, limit=1200):
    text = (output or "").strip()
    if not text:
        return "<empty>"
    if len(text) > limit:
        text = text[:limit] + "... <truncated>"
    return "\n".join(f"      {line}" for line in text.splitlines())


def _agent_process_env(agent_kind: str) -> dict[str, str] | None:
    if agent_kind != "opencode":
        return None
    env = os.environ.copy()
    env.update(
        {
            "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1",
            "OPENCODE_CONFIG": OPENCODE_SKILL_RUNNER_CONFIG,
        }
    )
    return env


def _ensure_agent_mcp_preflight(agent, debug=False, server_name="ida-pro-mcp"):
    global _MCP_PREFLIGHT_DONE, _MCP_PREFLIGHT_FAILED

    if _MCP_PREFLIGHT_DONE:
        return True
    if _MCP_PREFLIGHT_FAILED:
        print("    Error: MCP preflight previously failed; refusing to start agent.")
        return False

    cmd = [agent, "mcp", "list"]
    print(f"    Checking MCP server list: {' '.join(cmd)}")
    try:
        result = _run_process_with_stream_capture(
            cmd,
            debug=debug,
            timeout=MCP_LIST_TIMEOUT,
            env=_agent_process_env(_detect_agent_kind(agent) or ""),
        )
    except subprocess.TimeoutExpired:
        _MCP_PREFLIGHT_FAILED = True
        print(f"    Error: MCP list preflight timeout ({MCP_LIST_TIMEOUT} seconds): {' '.join(cmd)}")
        return False
    except FileNotFoundError:
        _MCP_PREFLIGHT_FAILED = True
        print(f"    Error: Agent '{agent}' not found while running MCP list preflight.")
        return False
    except Exception as error:
        _MCP_PREFLIGHT_FAILED = True
        print(f"    Error executing MCP list preflight: {error}")
        return False

    output = "\n".join(text for text in (result.stdout, result.stderr) if text)
    if _mcp_list_contains_server(output, server_name):
        _MCP_PREFLIGHT_DONE = True
        return True

    _MCP_PREFLIGHT_FAILED = True
    print(f"    Error: Required MCP server '{server_name}' is not listed by '{agent} mcp list'.")
    if result.returncode != 0:
        print(f"    mcp list return code: {result.returncode}")
    print(f"    mcp list output:\n{_format_mcp_list_output(output)}")
    return False


def _drain_text_stream(stream, chunks, forward_stream=None):
    try:
        for chunk in iter(stream.readline, ""):
            chunks.append(chunk)
            if forward_stream is not None:
                forward_stream.write(chunk)
                forward_stream.flush()
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _run_process_with_stream_capture(cmd, *, agent_input=None, debug=False, timeout=SKILL_TIMEOUT, env=None):
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if agent_input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    if agent_input is not None and process.stdin is not None:
        process.stdin.write(agent_input)
        process.stdin.flush()
        process.stdin.close()

    stdout_chunks, stderr_chunks = [], []
    stdout_thread = threading.Thread(
        target=_drain_text_stream, args=(process.stdout, stdout_chunks, sys.stdout if debug else None)
    )
    stderr_thread = threading.Thread(
        target=_drain_text_stream, args=(process.stderr, stderr_chunks, sys.stderr if debug else None)
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=1)
        except Exception:
            pass
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        raise

    stdout_thread.join()
    stderr_thread.join()
    return subprocess.CompletedProcess(cmd, process.returncode, "".join(stdout_chunks), "".join(stderr_chunks))


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


def _split_cli_args(raw_args: str) -> list[str]:
    text = str(raw_args or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=False)
    except ValueError:
        return text.split()


def _agent_permission_args(agent_kind: str, *, claude_permission_mode: str = "") -> list[str]:
    if agent_kind == "opencode":
        return ["--auto"]
    if agent_kind == "codex":
        return ["--approval-mode", "full-auto"]
    permission_mode = str(claude_permission_mode or "").strip() or "auto"
    return ["--permission-mode", permission_mode]


def _build_claude_base_args(
    *,
    agent: str,
    prompt_arg: str,
    agent_profile: str,
    session_id: str,
    is_retry: bool,
    allowed_tools: str = "",
    disallowed_tools: str = "",
    permission_mode: str = "",
    extra_args: str = "",
) -> list[str]:
    args = [agent, "-p", prompt_arg, "--agent", agent_profile]
    if allowed_tools := str(allowed_tools or "").strip():
        args.extend(["--allowedTools", allowed_tools])
    if disallowed_tools := str(disallowed_tools or "").strip():
        args.extend(["--disallowedTools", disallowed_tools])
    args.extend(["--settings", CLAUDE_SKILL_RUNNER_SETTINGS])
    args.extend(["--append-system-prompt-file", SKILL_RUNNER_SYSTEM_PROMPT])
    args.extend(_agent_permission_args("claude", claude_permission_mode=permission_mode))
    args.extend(_split_cli_args(extra_args))
    args.extend(["--resume" if is_retry else "--session-id", session_id])
    return args


def _build_codex_base_args(agent: str, developer_instructions: str, is_retry: bool) -> list[str]:
    args = [
        agent,
        "--profile",
        "skill_runner",
        "-c",
        developer_instructions,
    ]
    args.extend(_agent_permission_args("codex"))
    args.append("exec")
    if is_retry:
        args.extend(["resume", "--last"])
    return args


def _build_opencode_base_args(
    agent: str,
    agent_profile: str,
    is_retry: bool,
    session_id: str | None,
) -> list[str]:
    args = [agent, "run", "--format", "json"]
    args.extend(_agent_permission_args("opencode"))
    if is_retry and session_id:
        args.extend(["--session", session_id])
    elif is_retry:
        args.append("--continue")
    args.extend(["--agent", agent_profile])
    return args


def _build_claude_command(agent: str, skill_name: str, session_id: str, is_retry: bool) -> AgentCommand:
    args = _build_claude_base_args(
        agent=agent,
        prompt_arg=f"/{skill_name}",
        agent_profile="sig-finder",
        session_id=session_id,
        is_retry=is_retry,
        allowed_tools="mcp__ida-pro-mcp__*",
        disallowed_tools="mcp__ida-pro-mcp__open_file",
    )
    return AgentCommand(args, None, f"session {session_id}")


def _build_codex_command(agent: str, skill_name: str, developer_instructions: str, is_retry: bool) -> AgentCommand:
    args = _build_codex_base_args(agent, developer_instructions, is_retry)
    args.append("-")
    return AgentCommand(args, f"Run SKILL: .claude/skills/{skill_name}/SKILL.md", "the latest codex session (--last)")


def _build_opencode_command(
    agent: str,
    skill_name: str,
    is_retry: bool,
    session_id: str | None,
) -> AgentCommand:
    args = _build_opencode_base_args(agent, "sig-finder", is_retry, session_id)
    args.append(f"Run SKILL: .claude/skills/{skill_name}/SKILL.md")
    retry_target = f"OpenCode session {session_id}" if session_id else "the latest OpenCode session (--continue)"
    return AgentCommand(args, None, retry_target)


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


def _build_agent_command(
    *,
    agent: str,
    agent_kind: str,
    skill_name: str,
    session_id: str,
    opencode_session_id: str | None,
    developer_instructions: str | None,
    is_retry: bool,
) -> AgentCommand:
    if agent_kind == "claude":
        return _build_claude_command(agent, skill_name, session_id, is_retry)
    if agent_kind == "opencode":
        return _build_opencode_command(agent, skill_name, is_retry, opencode_session_id)
    if developer_instructions is None:
        raise ValueError("Codex developer instructions are required")
    return _build_codex_command(agent, skill_name, developer_instructions, is_retry)


def _print_command(command: AgentCommand, attempt: int, max_retries: int) -> None:
    attempt_str = f"(attempt {attempt + 1}/{max_retries})" if max_retries > 1 else ""
    retry_str = "[RETRY] " if attempt else ""
    prompt_transport = " <prompt via stdin>" if command.input_text is not None else ""
    print(f"    {retry_str}Running {attempt_str}: {' '.join(_display_command(command.args))}{prompt_transport}")


def _retry_if_available(attempt: int, max_retries: int, retry_target_desc: str) -> None:
    if attempt < max_retries - 1:
        print(f"    Retrying with {retry_target_desc}...")


def _result_failure_reason(result, expected_yaml_paths):
    if result.returncode != 0:
        return "returncode"
    if _output_contains_error_marker(result.stdout, result.stderr):
        return "error_marker"
    missing_files = _missing_expected_outputs(expected_yaml_paths)
    if missing_files:
        return missing_files
    return None


def _report_result_failure(reason, result, debug: bool) -> None:
    if reason == "returncode":
        print(f"    Skill failed with return code: {result.returncode}")
        if not debug and result.stderr:
            print(f"    stderr: {result.stderr[:500]}")
    elif reason == "error_marker":
        print("    Error: Skill output contains error marker")
    elif reason:
        print(f"    Error: Expected yaml files not generated: {reason}")


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
    opencode_session_id = None
    process_env = _agent_process_env(agent_kind)
    for attempt in range(max_retries):
        command = _build_agent_command(
            agent=agent,
            agent_kind=agent_kind,
            skill_name=skill_name,
            session_id=session_id,
            opencode_session_id=opencode_session_id,
            developer_instructions=developer_instructions,
            is_retry=attempt > 0,
        )
        _print_command(command, attempt, max_retries)
        try:
            result = _run_process_with_stream_capture(
                command.args,
                agent_input=command.input_text,
                debug=debug,
                timeout=SKILL_TIMEOUT,
                env=process_env,
            )
            if agent_kind == "opencode" and opencode_session_id is None:
                opencode_session_id = _extract_opencode_session_id(result.stdout)
            reason = _result_failure_reason(result, expected_yaml_paths)
            if reason is None:
                return True
            _report_result_failure(reason, result, debug)
            _retry_if_available(attempt, max_retries, command.retry_target_desc)
        except subprocess.TimeoutExpired:
            print(f"    Error: Skill execution timeout ({SKILL_TIMEOUT} seconds)")
            _retry_if_available(attempt, max_retries, command.retry_target_desc)
        except FileNotFoundError:
            print(f"    Error: Agent '{agent}' not found. Please ensure it is installed and in PATH.")
            return False
        except Exception as error:
            print(f"    Error executing skill: {error}")
            _retry_if_available(attempt, max_retries, command.retry_target_desc)

    print(f"    Failed after {max_retries} attempts")
    return False


def run_skill(skill_name, agent="claude", debug=False, expected_yaml_paths=None, max_retries=3) -> bool:
    """Execute a skill with its configured agent and retry support."""
    agent_kind = _detect_agent_kind(agent)
    if agent_kind is None:
        print(f"    Error: Unknown agent type '{agent}'. Agent name must contain 'claude', 'codex', or 'opencode'.")
        return False

    skill_md_path = os.path.join(".claude", "skills", skill_name, "SKILL.md")
    print(f"    Falling back to: {skill_md_path}")
    if not os.path.exists(skill_md_path):
        print(f"    Error: Skill file not found: {skill_md_path}")
        return False
    if not _ensure_agent_mcp_preflight(agent, debug=debug):
        return False

    developer_instructions = _load_codex_developer_instructions() if agent_kind == "codex" else None
    if agent_kind == "codex" and developer_instructions is None:
        return False
    return _run_skill_attempts(
        skill_name=skill_name,
        agent=agent,
        agent_kind=agent_kind,
        session_id=str(uuid.uuid4()) if agent_kind == "claude" else "",
        developer_instructions=developer_instructions,
        debug=debug,
        expected_yaml_paths=expected_yaml_paths,
        max_retries=max_retries,
    )


def _build_header_fix_command(
    *,
    fix_prompt: str,
    agent: str,
    agent_kind: str,
    developer_instructions: str | None,
    claude_session_id: str,
    opencode_session_id: str | None,
    is_retry: bool,
    claude_allowed_tools: str,
    claude_permission_mode: str,
    claude_extra_args: str,
) -> AgentCommand:
    if agent_kind == "claude":
        args = _build_claude_base_args(
            agent=agent,
            prompt_arg="-",
            agent_profile="vtable-fixer",
            session_id=claude_session_id,
            is_retry=is_retry,
            allowed_tools=claude_allowed_tools,
            permission_mode=claude_permission_mode,
            extra_args=claude_extra_args,
        )
        return AgentCommand(args, fix_prompt, f"session {claude_session_id}")
    if agent_kind == "codex":
        if developer_instructions is None:
            raise ValueError("Codex developer instructions are required")
        args = _build_codex_base_args(agent, developer_instructions, is_retry)
        args.append("-")
        return AgentCommand(args, fix_prompt, "the latest codex session (--last)")
    args = _build_opencode_base_args(agent, "vtable-fixer", is_retry, opencode_session_id)
    args.append(fix_prompt)
    return AgentCommand(args, None, _opencode_retry_target(opencode_session_id))


def _run_header_fix_process(command: AgentCommand, *, agent_kind: str, debug: bool):
    run_kwargs = {
        "timeout": HEADER_FIX_TIMEOUT,
        "check": False,
        "env": _agent_process_env(agent_kind),
    }
    if command.input_text is not None:
        run_kwargs.update({"input": command.input_text, "text": True})
    if debug and agent_kind != "opencode":
        return subprocess.run(command.args, **run_kwargs)
    run_kwargs.update({"capture_output": True, "text": True})
    return subprocess.run(command.args, **run_kwargs)


def _print_header_fix_command(
    command: AgentCommand, agent: str, attempt: int, max_retries: int, is_retry: bool
) -> None:
    retry_tag = "[RETRY] " if is_retry else ""
    attempt_str = f"(attempt {attempt + 1}/{max_retries})" if max_retries > 1 else ""
    prompt_transport = " via stdin" if command.input_text is not None else ""
    print(f"    {retry_tag}Running {attempt_str}: {agent} <vtable-fixer-prompt{prompt_transport}>")


def _handle_header_fix_result(
    result,
    *,
    agent_kind: str,
    debug: bool,
    opencode_session_id: str | None,
    session_state: dict[str, str | None] | None,
) -> tuple[bool, str | None]:
    if agent_kind == "opencode" and opencode_session_id is None:
        opencode_session_id = _extract_opencode_session_id(result.stdout)
        if session_state is not None:
            session_state["opencode_session_id"] = opencode_session_id
    if agent_kind == "opencode" and debug:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode == 0:
        return True, opencode_session_id
    print(f"    Agent failed with return code: {result.returncode}")
    if not debug and result.stderr:
        print(f"    stderr: {result.stderr[:500]}")
    return False, opencode_session_id


def _run_header_fix_attempts(
    context: HeaderFixContext,
    session_state: dict[str, str | None] | None,
) -> bool:
    opencode_session_id = (session_state or {}).get("opencode_session_id")
    for attempt in range(context.max_retries):
        is_retry = attempt > 0 or context.is_continuation
        command = _build_header_fix_command(
            fix_prompt=context.fix_prompt,
            agent=context.agent,
            agent_kind=context.agent_kind,
            developer_instructions=context.developer_instructions,
            claude_session_id=context.claude_session_id,
            opencode_session_id=opencode_session_id,
            is_retry=is_retry,
            claude_allowed_tools=context.claude_allowed_tools,
            claude_permission_mode=context.claude_permission_mode,
            claude_extra_args=context.claude_extra_args,
        )
        _print_header_fix_command(command, context.agent, attempt, context.max_retries, is_retry)
        try:
            result = _run_header_fix_process(command, agent_kind=context.agent_kind, debug=context.debug)
            succeeded, opencode_session_id = _handle_header_fix_result(
                result,
                agent_kind=context.agent_kind,
                debug=context.debug,
                opencode_session_id=opencode_session_id,
                session_state=session_state,
            )
            if succeeded:
                return True
            retry_target = (
                _opencode_retry_target(opencode_session_id)
                if context.agent_kind == "opencode"
                else command.retry_target_desc
            )
            _retry_if_available(attempt, context.max_retries, retry_target)
        except subprocess.TimeoutExpired:
            print(f"    Error: Agent execution timeout ({HEADER_FIX_TIMEOUT} seconds)")
            _retry_if_available(attempt, context.max_retries, command.retry_target_desc)
        except FileNotFoundError:
            print(f"    Error: Agent '{context.agent}' not found. Please ensure it is installed and in PATH.")
            return False
        except Exception as error:
            print(f"    Error executing fix-header agent: {error}")
            _retry_if_available(attempt, context.max_retries, command.retry_target_desc)
    print(f"    Failed after {context.max_retries} attempts")
    return False


def run_fix_header_agent(
    *,
    fix_prompt: str,
    agent: str,
    debug: bool,
    max_retries: int,
    session_id: str = "",
    is_continuation: bool = False,
    claude_allowed_tools: str = "",
    claude_permission_mode: str = "",
    claude_extra_args: str = "",
    session_state: dict[str, str | None] | None = None,
    agent_prompt_path: Path = Path(".claude/agents/vtable-fixer.md"),
) -> bool:
    """Invoke the configured Claude, Codex, or OpenCode agent to apply header fixes."""
    agent_kind = _detect_agent_kind(agent)
    if agent_kind is None:
        print(f"    Error: Unknown agent type '{agent}'. Agent name must contain 'claude', 'codex', or 'opencode'.")
        return False
    developer_instructions = None
    if agent_kind == "codex":
        developer_instructions = _load_codex_developer_instructions(agent_prompt_path)
        if not developer_instructions:
            return False
    context = HeaderFixContext(
        fix_prompt=fix_prompt,
        agent=agent,
        agent_kind=agent_kind,
        developer_instructions=developer_instructions,
        debug=debug,
        max_retries=max(1, int(max_retries)),
        claude_session_id=session_id or str(uuid.uuid4()),
        is_continuation=is_continuation,
        claude_allowed_tools=claude_allowed_tools,
        claude_permission_mode=claude_permission_mode,
        claude_extra_args=claude_extra_args,
    )
    return _run_header_fix_attempts(context, session_state)


def _opencode_retry_target(session_id: str | None) -> str:
    if session_id:
        return f"OpenCode session {session_id}"
    return "the latest OpenCode session (--continue)"
