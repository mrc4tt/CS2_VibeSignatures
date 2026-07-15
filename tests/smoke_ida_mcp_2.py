#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = Path(__file__).parent / "bin" / "server.dll"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _ida_analyze_bin() -> Any:
    return importlib.import_module("ida_analyze_bin")


def _mcp_adapter() -> Any:
    return importlib.import_module("ida_mcp_session")


def _fixture_database_path(binary_path: Path) -> Path:
    return binary_path.with_name(f"{binary_path.name}.i64")


def copy_smoke_fixture(binary_path: Path, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    copied_binary = work_dir / binary_path.name
    shutil.copy2(binary_path, copied_binary)
    shutil.copy2(_fixture_database_path(binary_path), _fixture_database_path(copied_binary))
    return copied_binary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test ida-pro-mcp 2.0.0 database routing")
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=13347)
    parser.add_argument("--ida-args", default="")
    parser.add_argument("--attach-existing", action="store_true")
    parser.add_argument("--mcp-database", default=None)
    return parser.parse_args(argv)


def _tool_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    text = getattr(content[0], "text", None) if content else None
    if not isinstance(text, str):
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _survey_path(session: Any) -> str:
    survey = await _ida_analyze_bin().survey_binary_via_session(session, detail_level="minimal")
    metadata = survey.get("metadata") if isinstance(survey, Mapping) else None
    path = metadata.get("path") if isinstance(metadata, Mapping) else None
    if not isinstance(path, str) or not path:
        raise RuntimeError("survey_binary returned no metadata path")
    return path


async def _list_sessions(session: Any) -> list[Mapping[str, Any]]:
    result = await session.call_tool("idb_list", {})
    sessions = _tool_payload(result).get("sessions", [])
    if not isinstance(sessions, list):
        raise RuntimeError("idb_list returned no session list")
    return [item for item in sessions if isinstance(item, Mapping)]


def _find_session_id(sessions: Sequence[Mapping[str, Any]], binary_path: Path) -> str:
    normalize_path = _mcp_adapter().normalize_binary_identity_path
    expected = normalize_path(binary_path)
    matches = [
        item.get("session_id")
        for item in sessions
        if normalize_path(item.get("input_path", "")) == expected
        and isinstance(item.get("session_id"), str)
        and item["session_id"].strip()
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one opened session for {binary_path}, got {matches!r}")
    return matches[0]


async def _verify_selected_binary(host: str, port: int, session_id: str, binary_path: Path) -> None:
    adapter = _mcp_adapter()
    async with adapter.open_ida_mcp_session(
        host,
        port,
        explicit_database=session_id,
        auto_started=True,
    ) as session:
        survey_path = await _survey_path(session)
    if adapter.normalize_binary_identity_path(survey_path) != adapter.normalize_binary_identity_path(binary_path):
        raise RuntimeError(f"explicit database selected {survey_path!r}, expected {binary_path!s}")


async def _quit_explicit_worker(host: str, port: int, session_id: str) -> None:
    adapter = _mcp_adapter()
    async with adapter.open_ida_mcp_session(
        host,
        port,
        explicit_database=session_id,
        auto_started=True,
    ) as session:
        if not session.binding.should_auto_quit:
            raise RuntimeError(f"database {session_id!r} is not an owned headless worker")
        try:
            await session.call_tool("py_eval", {"code": "import idc; idc.qexit(0)"})
        except adapter.McpToolCallError as exc:
            if _ida_analyze_bin().QEXIT_CONNECTION_RESET_MARKER not in str(exc):
                raise


def _drain_stderr(process: subprocess.Popen[Any], chunks: list[str]) -> threading.Thread | None:
    if process.stderr is None:
        return None

    def _drain() -> None:
        data = process.stderr.read()
        if isinstance(data, bytes):
            chunks.append(data.decode(errors="replace"))
        elif isinstance(data, str):
            chunks.append(data)

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    return thread


async def _run_attach_existing(binary_path: Path, args: argparse.Namespace) -> None:
    if not args.mcp_database:
        raise RuntimeError("--attach-existing requires --mcp-database")
    adapter = _mcp_adapter()
    async with adapter.open_ida_mcp_session(
        args.host,
        args.port,
        explicit_database=args.mcp_database,
        auto_started=False,
    ) as session:
        survey_path = await _survey_path(session)
        print(f"selected_database={session.binding.session_id}")
        print(f"owned={str(session.binding.owned).lower()}")
        print(f"auto_started={str(session.binding.auto_started).lower()}")
    if adapter.normalize_binary_identity_path(survey_path) != adapter.normalize_binary_identity_path(binary_path):
        raise RuntimeError(f"attached database selected {survey_path!r}, expected {binary_path!s}")
    print("non_owned_safety=passed")


async def _run_autostart(binary_path: Path, args: argparse.Namespace) -> None:
    stderr_chunks: list[str] = []
    ida_analyze_bin = _ida_analyze_bin()
    adapter = _mcp_adapter()
    with tempfile.TemporaryDirectory(prefix="ida-mcp-smoke-") as temp_dir:
        work_dir = Path(temp_dir)
        opened_binary = copy_smoke_fixture(binary_path, work_dir / "primary")
        copied_binary = copy_smoke_fixture(binary_path, work_dir / "secondary")
        process = ida_analyze_bin.start_idalib_mcp(
            str(opened_binary),
            args.host,
            args.port,
            args.ida_args,
            stderr=subprocess.PIPE,
        )
        if process is None:
            raise RuntimeError("failed to start idalib-mcp")
        stderr_thread = _drain_stderr(process, stderr_chunks)
        try:
            async with adapter.open_ida_mcp_session(
                args.host,
                args.port,
                expected_binary=opened_binary,
                auto_started=True,
            ) as session:
                if not session.binding.database_required or not session.binding.session_id:
                    raise RuntimeError("ida-pro-mcp did not expose a database-required worker contract")
                first_session_id = session.binding.session_id
                survey_path = await _survey_path(session)
                if adapter.normalize_binary_identity_path(survey_path) != adapter.normalize_binary_identity_path(
                    opened_binary
                ):
                    raise RuntimeError(f"survey selected {survey_path!r}, expected {opened_binary!s}")
                print("contract=database-required")
                print(f"selected_database={first_session_id}")
                print(f"survey_path={survey_path}")
                await session.call_tool("idb_open", {"input_path": str(copied_binary)})
                second_session_id = _find_session_id(await _list_sessions(session), copied_binary)

            try:
                async with adapter.open_ida_mcp_session(args.host, args.port):
                    raise RuntimeError("selector-free connection unexpectedly selected a database")
            except adapter.McpDatabaseSelectionError:
                print("multiple_database_guard=passed")

            await _verify_selected_binary(args.host, args.port, first_session_id, opened_binary)
            if not await ida_analyze_bin.quit_ida_via_mcp(
                args.host,
                args.port,
                expected_binary=str(opened_binary),
                auto_started=True,
            ):
                raise RuntimeError("failed to quit the owned original worker")
            await _quit_explicit_worker(args.host, args.port, second_session_id)
            print("targeted_owned_worker_quit=passed")
        finally:
            await asyncio.to_thread(ida_analyze_bin.stop_idalib_mcp_process, process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=5)
    if "Session termination failed: 501" in "".join(stderr_chunks):
        raise RuntimeError("Session termination failed: 501")
    print("session_termination_501=absent")


async def run(args: argparse.Namespace) -> None:
    binary_path = Path(args.binary).expanduser().resolve()
    if not binary_path.is_file():
        print(f"SKIPPED: smoke fixture does not exist: {binary_path}")
        return
    database_path = _fixture_database_path(binary_path)
    if not database_path.is_file():
        print(f"SKIPPED: smoke fixture database does not exist: {database_path}")
        return
    if args.attach_existing:
        await _run_attach_existing(binary_path, args)
        return
    await _run_autostart(binary_path, args)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        asyncio.run(run(parse_args(argv)))
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
