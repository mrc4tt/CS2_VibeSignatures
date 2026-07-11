import io
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestOpenCodeSigFinderAgent(unittest.TestCase):
    def test_project_agent_preserves_required_safety_constraints(self) -> None:
        agent_path = Path(".opencode/agents/sig-finder.md")

        self.assertTrue(agent_path.is_file())
        agent_text = agent_path.read_text(encoding="utf-8")
        self.assertIn("mode: primary", agent_text)
        self.assertIn("ida-pro-mcp_open_file: false", agent_text)
        self.assertIn("currently opened in IDA", agent_text)
        self.assertIn("DO NOT verify or check the existence of output yaml", agent_text)


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


class TestRunSkillOutputDetection(unittest.TestCase):
    def setUp(self) -> None:
        agent_skill_runner._MCP_PREFLIGHT_DONE = False
        agent_skill_runner._MCP_PREFLIGHT_FAILED = False

    def test_output_contains_error_marker_only_matches_standalone_tokens(self) -> None:
        self.assertTrue(agent_skill_runner._output_contains_error_marker("Error"))
        self.assertTrue(agent_skill_runner._output_contains_error_marker("prefix [ERROR] suffix"))
        self.assertTrue(agent_skill_runner._output_contains_error_marker("before **ERROR** after"))
        self.assertTrue(agent_skill_runner._output_contains_error_marker("line one\nerror\nline three"))

        self.assertFalse(agent_skill_runner._output_contains_error_marker("myErrorCode"))
        self.assertFalse(agent_skill_runner._output_contains_error_marker("error123"))
        self.assertFalse(agent_skill_runner._output_contains_error_marker("XerrorY"))
        self.assertFalse(agent_skill_runner._output_contains_error_marker("all good"))


class TestRunSkillCodexPromptTransport(unittest.TestCase):
    def setUp(self) -> None:
        agent_skill_runner._MCP_PREFLIGHT_DONE = False
        agent_skill_runner._MCP_PREFLIGHT_FAILED = False

    @patch.object(Path, "read_text", return_value="sig finder prompt")
    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner._run_process_with_stream_capture")
    def test_run_skill_passes_codex_prompt_via_stdin_on_retry(
        self,
        mock_run_process,
        _mock_exists,
        _mock_read_text,
    ) -> None:
        mock_run_process.side_effect = [
            subprocess.CompletedProcess(
                args=["codex", "mcp", "list"],
                returncode=1,
                stdout="Name\nida-pro-mcp  http://127.0.0.1:13337/mcp  enabled\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["codex"],
                returncode=1,
                stdout="",
                stderr="first failure",
            ),
            subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]

        result = agent_skill_runner.run_skill(
            skill_name="find-IGameSystem_vtable",
            agent="codex",
            debug=False,
            max_retries=2,
        )

        self.assertTrue(result)
        self.assertEqual(3, mock_run_process.call_count)

        preflight_call = mock_run_process.call_args_list[0]
        first_call = mock_run_process.call_args_list[1]
        second_call = mock_run_process.call_args_list[2]

        self.assertEqual(["codex", "mcp", "list"], preflight_call.args[0])
        self.assertEqual(["exec", "-"], first_call.args[0][-2:])
        self.assertEqual(["exec", "resume", "--last", "-"], second_call.args[0][-4:])
        expected_prompt = "Run SKILL: .claude/skills/find-IGameSystem_vtable/SKILL.md"
        self.assertEqual(expected_prompt, first_call.kwargs["agent_input"])
        self.assertEqual(expected_prompt, second_call.kwargs["agent_input"])
        self.assertFalse(first_call.kwargs["debug"])
        self.assertFalse(second_call.kwargs["debug"])
        self.assertEqual(agent_skill_runner.SKILL_TIMEOUT, first_call.kwargs["timeout"])
        self.assertEqual(agent_skill_runner.SKILL_TIMEOUT, second_call.kwargs["timeout"])

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_run_skill_debug_true_forwards_stdout_and_stderr(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        preflight_process = _FakePopen(
            stdout_chunks=["ida-pro-mcp: http://127.0.0.1:13337/mcp (HTTP) - Failed\n"],
            stderr_chunks=[],
            returncode=0,
        )
        agent_process = _FakePopen(
            stdout_chunks=["agent stdout line\n"],
            stderr_chunks=["agent stderr line\n"],
            returncode=0,
        )
        mock_popen.side_effect = [preflight_process, agent_process]

        with (
            patch("sys.stdout", new_callable=io.StringIO) as fake_stdout,
            patch("sys.stderr", new_callable=io.StringIO) as fake_stderr,
        ):
            result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="claude",
                debug=True,
                max_retries=1,
            )

        self.assertTrue(result)
        self.assertEqual(["claude", "mcp", "list"], mock_popen.call_args_list[0].args[0])
        self.assertIn("agent stdout line\n", fake_stdout.getvalue())
        self.assertIn("agent stderr line\n", fake_stderr.getvalue())

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_run_skill_disallows_claude_from_opening_another_ida_file(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        preflight_process = _FakePopen(
            stdout_chunks=["ida-pro-mcp: http://127.0.0.1:13337/mcp (HTTP) - Failed\n"],
            stderr_chunks=[],
            returncode=0,
        )
        agent_process = _FakePopen(stdout_chunks=["done\n"], stderr_chunks=[], returncode=0)
        mock_popen.side_effect = [preflight_process, agent_process]

        result = agent_skill_runner.run_skill(
            skill_name="find-IGameSystem_vtable",
            agent="claude",
            debug=False,
            max_retries=1,
        )

        self.assertTrue(result)
        agent_cmd = mock_popen.call_args_list[1].args[0]
        disallowed_index = agent_cmd.index("--disallowedTools")
        self.assertEqual("mcp__ida-pro-mcp__open_file", agent_cmd[disallowed_index + 1])

    @patch.object(Path, "read_text", return_value="sig finder prompt")
    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_run_skill_retries_when_output_contains_error_marker(
        self,
        mock_popen,
        _mock_exists,
        _mock_read_text,
    ) -> None:
        preflight_process = _FakePopen(
            stdout_chunks=["ida-pro-mcp  http://127.0.0.1:13337/mcp  enabled\n"],
            stderr_chunks=[],
            returncode=0,
        )
        first_process = _FakePopen(
            stdout_chunks=["starting\n", "[ERROR] lookup failed\n"],
            stderr_chunks=[],
            returncode=0,
        )
        second_process = _FakePopen(
            stdout_chunks=["done\n"],
            stderr_chunks=[],
            returncode=0,
        )
        mock_popen.side_effect = [preflight_process, first_process, second_process]

        with (
            patch("sys.stdout", new_callable=io.StringIO) as fake_stdout,
            patch("sys.stderr", new_callable=io.StringIO) as fake_stderr,
        ):
            result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="codex",
                debug=False,
                max_retries=2,
            )

        self.assertTrue(result)
        self.assertEqual(3, mock_popen.call_count)
        self.assertEqual(["codex", "mcp", "list"], mock_popen.call_args_list[0].args[0])
        self.assertNotIn("[ERROR] lookup failed\n", fake_stdout.getvalue())
        self.assertEqual("", fake_stderr.getvalue())
        expected_prompt = "Run SKILL: .claude/skills/find-IGameSystem_vtable/SKILL.md"
        self.assertEqual(expected_prompt, "".join(first_process.stdin.writes))
        self.assertEqual(expected_prompt, "".join(second_process.stdin.writes))


class TestRunSkillMcpListPreflight(unittest.TestCase):
    def setUp(self) -> None:
        agent_skill_runner._MCP_PREFLIGHT_DONE = False
        agent_skill_runner._MCP_PREFLIGHT_FAILED = False

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_claude_mcp_list_accepts_failed_connection_when_server_is_listed(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        preflight_process = _FakePopen(
            stdout_chunks=["ida-pro-mcp: http://127.0.0.1:13337/mcp (HTTP) - Failed to connect\n"],
            stderr_chunks=[],
            returncode=0,
        )
        agent_process = _FakePopen(stdout_chunks=["done\n"], stderr_chunks=[], returncode=0)
        mock_popen.side_effect = [preflight_process, agent_process]

        result = agent_skill_runner.run_skill(
            skill_name="find-IGameSystem_vtable",
            agent="claude",
            debug=False,
            max_retries=1,
        )

        self.assertTrue(result)
        self.assertEqual(["claude", "mcp", "list"], mock_popen.call_args_list[0].args[0])
        self.assertEqual(2, mock_popen.call_count)

    @patch.object(Path, "read_text", return_value="sig finder prompt")
    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner._run_process_with_stream_capture")
    def test_codex_mcp_list_accepts_table_row_when_server_is_listed(
        self,
        mock_run_process,
        _mock_exists,
        _mock_read_text,
    ) -> None:
        mock_run_process.side_effect = [
            subprocess.CompletedProcess(
                args=["codex", "mcp", "list"],
                returncode=0,
                stdout=(
                    "Name         Url                         Status\n"
                    "ida-pro-mcp  http://127.0.0.1:13337/mcp  enabled\n"
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]

        result = agent_skill_runner.run_skill(
            skill_name="find-IGameSystem_vtable",
            agent="codex",
            debug=False,
            max_retries=1,
        )

        self.assertTrue(result)
        self.assertEqual(["codex", "mcp", "list"], mock_run_process.call_args_list[0].args[0])
        self.assertEqual(2, mock_run_process.call_count)

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_missing_ida_pro_mcp_blocks_agent_start(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        preflight_process = _FakePopen(
            stdout_chunks=["serena: http://127.0.0.1:9131/mcp (HTTP) - Connected\n"],
            stderr_chunks=[],
            returncode=0,
        )
        mock_popen.return_value = preflight_process

        with patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="claude",
                debug=False,
                max_retries=1,
            )

        self.assertFalse(result)
        self.assertEqual(1, mock_popen.call_count)
        self.assertEqual(["claude", "mcp", "list"], mock_popen.call_args.args[0])
        self.assertIn("Required MCP server 'ida-pro-mcp' is not listed", fake_stdout.getvalue())

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_mcp_list_timeout_blocks_agent_start(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        timeout_process = _FakePopen(stdout_chunks=[], stderr_chunks=[], returncode=0)
        timeout_process.wait = MagicMock(
            side_effect=subprocess.TimeoutExpired(
                ["claude", "mcp", "list"],
                30,
            )
        )
        mock_popen.return_value = timeout_process

        with patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="claude",
                debug=False,
                max_retries=1,
            )

        self.assertFalse(result)
        self.assertEqual(1, mock_popen.call_count)
        self.assertIn("MCP list preflight timeout", fake_stdout.getvalue())
        self.assertTrue(timeout_process.killed)

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen", side_effect=FileNotFoundError)
    def test_mcp_list_missing_agent_blocks_agent_start(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="claude",
                debug=False,
                max_retries=1,
            )

        self.assertFalse(result)
        self.assertEqual(1, mock_popen.call_count)
        self.assertIn(
            "Agent 'claude' not found while running MCP list preflight",
            fake_stdout.getvalue(),
        )

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_empty_mcp_list_output_blocks_agent_start(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        mock_popen.return_value = _FakePopen(stdout_chunks=[], stderr_chunks=[], returncode=0)

        with patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="claude",
                debug=False,
                max_retries=1,
            )

        self.assertFalse(result)
        self.assertEqual(1, mock_popen.call_count)
        self.assertIn("Required MCP server 'ida-pro-mcp' is not listed", fake_stdout.getvalue())

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_preflight_runs_only_once_for_multiple_skills(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        preflight_process = _FakePopen(
            stdout_chunks=["ida-pro-mcp: http://127.0.0.1:13337/mcp (HTTP) - Failed\n"],
            stderr_chunks=[],
            returncode=0,
        )
        first_agent = _FakePopen(stdout_chunks=["first\n"], stderr_chunks=[], returncode=0)
        second_agent = _FakePopen(stdout_chunks=["second\n"], stderr_chunks=[], returncode=0)
        mock_popen.side_effect = [preflight_process, first_agent, second_agent]

        first_result = agent_skill_runner.run_skill(
            skill_name="find-IGameSystem_vtable",
            agent="claude",
            debug=False,
            max_retries=1,
        )
        second_result = agent_skill_runner.run_skill(
            skill_name="find-CBaseEntity_vtable",
            agent="claude",
            debug=False,
            max_retries=1,
        )

        self.assertTrue(first_result)
        self.assertTrue(second_result)
        commands = [call_args.args[0] for call_args in mock_popen.call_args_list]
        self.assertEqual(1, commands.count(["claude", "mcp", "list"]))
        self.assertEqual(3, mock_popen.call_count)

    @patch("agent_skill_runner.os.path.exists", return_value=True)
    @patch("agent_skill_runner.subprocess.Popen")
    def test_failed_preflight_is_not_retried_for_later_skills(
        self,
        mock_popen,
        _mock_exists,
    ) -> None:
        mock_popen.return_value = _FakePopen(
            stdout_chunks=["serena: http://127.0.0.1:9131/mcp (HTTP) - Connected\n"],
            stderr_chunks=[],
            returncode=0,
        )

        with patch("sys.stdout", new_callable=io.StringIO) as fake_stdout:
            first_result = agent_skill_runner.run_skill(
                skill_name="find-IGameSystem_vtable",
                agent="claude",
                debug=False,
                max_retries=1,
            )
            second_result = agent_skill_runner.run_skill(
                skill_name="find-CBaseEntity_vtable",
                agent="claude",
                debug=False,
                max_retries=1,
            )

        self.assertFalse(first_result)
        self.assertFalse(second_result)
        self.assertEqual(1, mock_popen.call_count)
        self.assertIn("MCP preflight previously failed", fake_stdout.getvalue())

    def test_mcp_list_server_matching_requires_list_item_name(self) -> None:
        self.assertTrue(
            agent_skill_runner._mcp_list_contains_server("ida-pro-mcp: http://127.0.0.1:13337/mcp (HTTP) - Failed\n")
        )
        self.assertTrue(
            agent_skill_runner._mcp_list_contains_server("ida-pro-mcp  http://127.0.0.1:13337/mcp  enabled\n")
        )
        self.assertFalse(
            agent_skill_runner._mcp_list_contains_server(
                "not-ida-pro-mcp: http://127.0.0.1:13337/mcp (HTTP) - Failed\n"
            )
        )
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
