from __future__ import annotations

from contextlib import asynccontextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests import smoke_ida_mcp_2
from ida_mcp_session import McpToolCallError


@asynccontextmanager
async def _async_context(value):
    yield value


class TestSmokeFixturePrecondition(unittest.TestCase):
    def test_missing_binary_is_skipped(self) -> None:
        missing_binary = Path(__file__).parent / "bin" / "missing-smoke-fixture.dll"
        output = StringIO()

        with redirect_stdout(output):
            exit_code = smoke_ida_mcp_2.main(["--binary", str(missing_binary)])

        self.assertEqual(0, exit_code)
        self.assertIn("SKIPPED: smoke fixture does not exist", output.getvalue())

    def test_copies_binary_and_database_to_working_directory(self) -> None:
        with TemporaryDirectory() as source_dir, TemporaryDirectory() as work_dir:
            source_binary = Path(source_dir) / "server.dll"
            source_database = Path(f"{source_binary}.i64")
            source_binary.write_bytes(b"binary")
            source_database.write_bytes(b"database")

            copied_binary = smoke_ida_mcp_2.copy_smoke_fixture(source_binary, Path(work_dir))

            self.assertEqual(b"binary", copied_binary.read_bytes())
            self.assertEqual(b"database", Path(f"{copied_binary}.i64").read_bytes())


class TestSmokeFixtureDatabasePrecondition(unittest.IsolatedAsyncioTestCase):
    async def test_missing_companion_database_is_skipped(self) -> None:
        with TemporaryDirectory() as temp_dir:
            binary_path = Path(temp_dir) / "server.dll"
            binary_path.write_bytes(b"fixture")
            output = StringIO()

            with (
                patch.object(smoke_ida_mcp_2, "_run_autostart", new_callable=AsyncMock) as run_autostart,
                redirect_stdout(output),
            ):
                await smoke_ida_mcp_2.run(SimpleNamespace(binary=str(binary_path), attach_existing=False))

        run_autostart.assert_not_awaited()
        self.assertIn("SKIPPED: smoke fixture database does not exist", output.getvalue())


class TestSmokeWorkerCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_worker_disconnect_after_qexit_is_accepted(self) -> None:
        session = MagicMock()
        session.binding = SimpleNamespace(should_auto_quit=True)
        session.call_tool = AsyncMock(
            side_effect=McpToolCallError("MCP tool py_eval failed: [WinError 10054] 远程主机强迫关闭了一个现有的连接。")
        )
        adapter = SimpleNamespace(
            McpToolCallError=McpToolCallError,
            open_ida_mcp_session=lambda *_args, **_kwargs: _async_context(session),
        )

        with (
            patch.object(smoke_ida_mcp_2, "_mcp_adapter", return_value=adapter),
            patch.object(
                smoke_ida_mcp_2,
                "_ida_analyze_bin",
                return_value=SimpleNamespace(QEXIT_CONNECTION_RESET_MARKER="[WinError 10054]"),
            ),
        ):
            await smoke_ida_mcp_2._quit_explicit_worker("127.0.0.1", 13347, "server-db")
