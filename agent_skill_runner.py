"""Agent Skill CLI execution, MCP preflight, retries, and output validation."""

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
ERROR_MARKER_RE = re.compile(r"(?<![A-Za-z0-9])error(?![A-Za-z0-9])", re.IGNORECASE)
_MCP_PREFLIGHT_DONE = False
_MCP_PREFLIGHT_FAILED = False


@dataclass(frozen=True)
class AgentCommand:
    args: list[str]
    input_text: str | None
    retry_target_desc: str


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
    pattern = re.compile(rf"(?m)^\s*(?:[-*]\s*)?{re.escape(server_name)}(?:\s|:|$)")
    return bool(pattern.search(output))


def _format_mcp_list_output(output, limit=1200):
    text = (output or "").strip()
    if not text:
        return "<empty>"
    if len(text) > limit:
        text = text[:limit] + "... <truncated>"
    return "\n".join(f"      {line}" for line in text.splitlines())


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
        result = _run_process_with_stream_capture(cmd, debug=debug, timeout=MCP_LIST_TIMEOUT)
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


def _run_process_with_stream_capture(cmd, *, agent_input=None, debug=False, timeout=SKILL_TIMEOUT):
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if agent_input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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


def _build_claude_command(agent: str, skill_name: str, session_id: str, is_retry: bool) -> AgentCommand:
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


def _build_codex_command(agent: str, skill_name: str, developer_instructions: str, is_retry: bool) -> AgentCommand:
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
    return AgentCommand(args, f"Run SKILL: .claude/skills/{skill_name}/SKILL.md", "the latest codex session (--last)")


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
                command.args, agent_input=command.input_text, debug=debug, timeout=SKILL_TIMEOUT
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
