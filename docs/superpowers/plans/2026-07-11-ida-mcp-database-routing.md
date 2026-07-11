# IDA MCP Database Routing Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every repository-initiated IDA MCP call compatible with both legacy single-database servers and `ida-pro-mcp 2.0.0`, while selecting the correct database safely and cleaning up only workers owned by the current auto-start flow.

**Architecture:** Add a focused `ida_mcp_session.py` compatibility layer that owns transport creation, `tools/list` contract detection, database selection, call routing, and MCP error conversion. Existing analysis helpers keep calling `session.call_tool()` through a database-bound wrapper, so the 75 worker calls do not need individual database edits. Migrate the three raw session entry points and all lifecycle decisions to this layer.

**Tech Stack:** Python 3.10+, `asyncio`, `httpx`, MCP Python SDK, `unittest`, `unittest.mock`, Ruff.

## Global Constraints

- Support legacy worker tools that do not declare `database` and 2.0.0 worker tools that require it.
- Detect the contract from `tools/list`; do not branch on package version strings.
- Select by explicit session id first, expected binary path second, and a single active routable session last.
- Fail when zero or multiple sessions remain; never choose the first or most recently accessed session silently.
- Normalize Windows, POSIX, `/mnt/<drive>`, `.i64`, and `.idb` path variants consistently.
- Use `terminate_on_close=False` for every repository-created streamable HTTP transport.
- Convert `isError=true` into explicit exceptions containing the tool name and server message.
- Only send `qexit` for an auto-started session logically owned by the current flow; never close adopted workers or GUI sessions.
- Keep `tests/bin/ida-mcp-smoke.dll` local and untracked; the existing `bin` ignore rule covers `tests/bin`.
- Do not add dependencies, modify the server, or refactor unrelated analysis logic.
- Do not create Git commits unless the user explicitly requests them.

---

### Task 1: Contract Detection and Database Selection

**Files:**
- Create: `ida_mcp_session.py`
- Create: `tests/test_ida_mcp_session.py`

**Interfaces:**
- Produces: `normalize_binary_identity_path(path: str | os.PathLike[str]) -> str`
- Produces: `detect_database_requirement(tools: Sequence[Any]) -> bool`
- Produces: `select_database_session(sessions: Sequence[Mapping[str, Any]], *, expected_binary=None, explicit_database=None) -> Mapping[str, Any]`
- Produces: `McpContractError`, `McpDatabaseSelectionError`

- [ ] **Step 1: Write failing path-normalization tests**

```python
class TestNormalizeBinaryIdentityPath(unittest.TestCase):
    def test_normalizes_database_suffix_and_windows_case(self) -> None:
        self.assertEqual(
            "d:/repo/bin/server/server.dll",
            normalize_binary_identity_path(r"D:\Repo\bin\server\server.dll.i64"),
        )

    def test_normalizes_wsl_mount_path(self) -> None:
        self.assertEqual(
            "d:/repo/bin/server/libserver.so",
            normalize_binary_identity_path("/mnt/d/repo/bin/server/libserver.so.idb"),
        )
```

- [ ] **Step 2: Write failing contract-detection tests**

```python
class TestDetectDatabaseRequirement(unittest.TestCase):
    def test_legacy_worker_schema_does_not_require_database(self) -> None:
        tools = [SimpleNamespace(name="py_eval", inputSchema={"required": ["code"]})]
        self.assertFalse(detect_database_requirement(tools))

    def test_supervisor_worker_schema_requires_database(self) -> None:
        tools = [SimpleNamespace(name="py_eval", inputSchema={"required": ["code", "database"]})]
        self.assertTrue(detect_database_requirement(tools))

    def test_mixed_worker_contract_is_rejected(self) -> None:
        tools = [
            SimpleNamespace(name="py_eval", inputSchema={"required": ["code", "database"]}),
            SimpleNamespace(name="find_bytes", inputSchema={"required": ["patterns"]}),
        ]
        with self.assertRaisesRegex(McpContractError, "inconsistent database requirement"):
            detect_database_requirement(tools)
```

- [ ] **Step 3: Write failing session-selection tests**

```python
ACTIVE_SERVER = {
    "session_id": "server-db",
    "input_path": r"D:\repo\tests\bin\ida-mcp-smoke.dll.i64",
    "backend": "worker",
    "owned": True,
    "is_active": True,
}

ACTIVE_ENGINE = {
    "session_id": "engine-db",
    "input_path": r"D:\repo\tests\bin\engine.dll.i64",
    "backend": "worker",
    "owned": False,
    "is_active": True,
}

class TestSelectDatabaseSession(unittest.TestCase):
    def test_explicit_database_has_priority(self) -> None:
        selected = select_database_session(
            [ACTIVE_SERVER, ACTIVE_ENGINE],
            expected_binary=r"D:\repo\tests\bin\ida-mcp-smoke.dll",
            explicit_database="engine-db",
        )
        self.assertEqual("engine-db", selected["session_id"])

    def test_expected_binary_matches_ida_database_suffix(self) -> None:
        selected = select_database_session(
            [ACTIVE_SERVER, ACTIVE_ENGINE],
            expected_binary=r"D:\repo\tests\bin\ida-mcp-smoke.dll",
        )
        self.assertEqual("server-db", selected["session_id"])

    def test_single_active_routable_session_is_selected(self) -> None:
        selected = select_database_session([ACTIVE_SERVER])
        self.assertEqual("server-db", selected["session_id"])

    def test_multiple_sessions_without_selector_fail_closed(self) -> None:
        with self.assertRaisesRegex(McpDatabaseSelectionError, "multiple active MCP databases"):
            select_database_session([ACTIVE_SERVER, ACTIVE_ENGINE])

    def test_empty_session_id_is_not_routable(self) -> None:
        discovered = {**ACTIVE_SERVER, "session_id": "", "owned": False}
        with self.assertRaisesRegex(McpDatabaseSelectionError, "no active routable MCP database"):
            select_database_session([discovered])
```

- [ ] **Step 4: Run the new tests and confirm the red state**

Run:

```powershell
uv run python -m unittest tests.test_ida_mcp_session -v
```

Expected: import failures for the new interfaces because `ida_mcp_session.py` does not yet implement them.

- [ ] **Step 5: Implement the pure compatibility helpers**

```python
WORKER_TOOL_NAMES = frozenset(
    {"py_eval", "survey_binary", "find_bytes", "rename", "define_func", "set_comments", "get_int"}
)
MANAGEMENT_TOOL_NAMES = frozenset({"idb_open", "idb_list"})
IDA_DATABASE_SUFFIXES = (".i64", ".idb")


class McpContractError(RuntimeError):
    pass


class McpDatabaseSelectionError(RuntimeError):
    pass


def normalize_binary_identity_path(path):
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        return ""
    value = str(path).strip().replace("\\", "/")
    lowered = value.lower()
    for suffix in IDA_DATABASE_SUFFIXES:
        if lowered.endswith(suffix):
            value = value[: -len(suffix)]
            break
    mount = re.match(r"^/mnt/([A-Za-z])/(.*)$", value)
    if mount:
        value = f"{mount.group(1)}:/{mount.group(2)}"
    if not re.match(r"^[A-Za-z]:/", value) and not value.startswith("/"):
        value = os.path.abspath(os.path.normpath(value)).replace("\\", "/")
    else:
        value = os.path.normpath(value).replace("\\", "/")
    return value.rstrip("/").lower()


def detect_database_requirement(tools):
    requirements = {}
    for tool in tools:
        if tool.name not in WORKER_TOOL_NAMES:
            continue
        schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
        requirements[tool.name] = "database" in schema.get("required", [])
    if not requirements:
        raise McpContractError("MCP tools/list returned no known IDA worker tools")
    if len(set(requirements.values())) != 1:
        raise McpContractError(f"inconsistent database requirement across worker tools: {requirements}")
    return next(iter(requirements.values()))


def _session_summary(sessions):
    return "; ".join(
        "session_id={session_id!r}, input_path={input_path!r}, backend={backend!r}, "
        "owned={owned!r}, is_active={is_active!r}".format(**session)
        for session in sessions
    )


def select_database_session(sessions, *, expected_binary=None, explicit_database=None):
    routable = [
        session
        for session in sessions
        if session.get("is_active") is True
        and isinstance(session.get("session_id"), str)
        and session["session_id"].strip()
    ]
    if explicit_database:
        matches = [session for session in routable if session["session_id"] == explicit_database]
        if len(matches) != 1:
            raise McpDatabaseSelectionError(
                f"MCP database {explicit_database!r} is not an active routable session; "
                f"candidates: {_session_summary(sessions)}"
            )
        return matches[0]
    if expected_binary:
        expected = normalize_binary_identity_path(expected_binary)
        matches = [
            session
            for session in routable
            if normalize_binary_identity_path(session.get("input_path", "")) == expected
        ]
        if len(matches) == 1:
            return matches[0]
        label = "no" if not matches else "multiple"
        raise McpDatabaseSelectionError(
            f"{label} active MCP database matched expected binary {expected_binary!r}; "
            f"candidates: {_session_summary(sessions)}"
        )
    if len(routable) == 1:
        return routable[0]
    if not routable:
        raise McpDatabaseSelectionError(
            f"no active routable MCP database; candidates: {_session_summary(sessions)}"
        )
    raise McpDatabaseSelectionError(
        f"multiple active MCP databases require an expected binary or explicit session id; "
        f"candidates: {_session_summary(sessions)}"
    )
```

- [ ] **Step 6: Run Task 1 tests**

Run:

```powershell
uv run python -m unittest tests.test_ida_mcp_session -v
```

Expected: all Task 1 tests pass.

- [ ] **Step 7: Review checkpoint**

Run:

```powershell
git diff -- ida_mcp_session.py tests/test_ida_mcp_session.py
```

Confirm the module contains only pure contract/path/selection logic at this checkpoint.

---

### Task 2: Database-Bound Session and Unified Transport

**Files:**
- Modify: `ida_mcp_session.py`
- Modify: `tests/test_ida_mcp_session.py`

**Interfaces:**
- Consumes: Task 1 contract detection and selection functions.
- Produces: `McpDatabaseBinding`
- Produces: `DatabaseBoundSession.call_tool(name, arguments=None, **kwargs)`
- Produces: `open_ida_mcp_session(host, port, *, expected_binary=None, explicit_database=None, auto_started=False, connect_timeout=10.0, read_timeout=300.0)`
- Produces: `check_ida_mcp_supervisor_health(host, port) -> bool`
- Produces: `McpConnectionError`, `McpToolCallError`

- [ ] **Step 1: Write failing wrapper tests**

```python
class TestDatabaseBoundSession(unittest.IsolatedAsyncioTestCase):
    async def test_injects_database_for_worker_tool(self) -> None:
        raw = MagicMock()
        raw.call_tool = AsyncMock(return_value=SimpleNamespace(isError=False, content=[], structuredContent={"ok": True}))
        bound = DatabaseBoundSession(
            raw,
            McpDatabaseBinding(True, "server-db", "server.dll", "worker", True, True),
        )
        result = await bound.call_tool("py_eval", {"code": "1"})
        self.assertEqual({"ok": True}, result.structuredContent)
        raw.call_tool.assert_awaited_once_with(
            name="py_eval",
            arguments={"code": "1", "database": "server-db"},
        )

    async def test_management_tool_is_not_modified(self) -> None:
        raw = MagicMock()
        raw.call_tool = AsyncMock(return_value=SimpleNamespace(isError=False, content=[], structuredContent={}))
        bound = DatabaseBoundSession(
            raw,
            McpDatabaseBinding(True, "server-db", "server.dll", "worker", True, True),
        )
        await bound.call_tool("idb_list", {})
        raw.call_tool.assert_awaited_once_with(name="idb_list", arguments={})

    async def test_conflicting_database_is_rejected(self) -> None:
        raw = MagicMock()
        raw.call_tool = AsyncMock()
        bound = DatabaseBoundSession(
            raw,
            McpDatabaseBinding(True, "server-db", "server.dll", "worker", True, True),
        )
        with self.assertRaisesRegex(McpDatabaseSelectionError, "conflicts with bound database"):
            await bound.call_tool("py_eval", {"code": "1", "database": "engine-db"})
        raw.call_tool.assert_not_awaited()

    async def test_server_is_error_becomes_typed_exception(self) -> None:
        raw = MagicMock()
        raw.call_tool = AsyncMock(
            return_value=SimpleNamespace(
                isError=True,
                structuredContent=None,
                content=[SimpleNamespace(text='{"error":"database is required"}')],
            )
        )
        bound = DatabaseBoundSession(raw, McpDatabaseBinding(False, None, None, "worker", True, True))
        with self.assertRaisesRegex(McpToolCallError, "py_eval.*database is required"):
            await bound.call_tool("py_eval", {"code": "1"})
```

- [ ] **Step 2: Write failing context-manager tests**

Create async fake contexts for `httpx.AsyncClient`, `streamable_http_client`, and MCP `ClientSession`. Assert:

```python
streamable_client.assert_called_once_with(
    "http://127.0.0.1:13337/mcp",
    http_client=http_client,
    terminate_on_close=False,
)
```

For a legacy `tools/list`, assert `idb_list` is never called and `binding.database_required` is false. For a 2.0.0 schema, return `idb_list` structured content containing `ACTIVE_SERVER` and assert the yielded binding contains `session_id="server-db"`, `owned=True`, and `backend="worker"`.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
uv run python -m unittest tests.test_ida_mcp_session.TestDatabaseBoundSession -v
uv run python -m unittest tests.test_ida_mcp_session.TestOpenIdaMcpSession -v
```

Expected: failures because the dataclass, wrapper, exceptions, and context manager are not implemented.

- [ ] **Step 4: Implement binding and wrapper**

```python
@dataclass(frozen=True)
class McpDatabaseBinding:
    database_required: bool
    session_id: str | None
    input_path: str | None
    backend: str | None
    owned: bool
    auto_started: bool

    @property
    def should_auto_quit(self) -> bool:
        return self.auto_started and self.owned and self.backend == "worker"


class McpToolCallError(RuntimeError):
    pass


class DatabaseBoundSession:
    def __init__(self, raw_session, binding: McpDatabaseBinding):
        self.raw_session = raw_session
        self.binding = binding

    async def call_tool(self, name, arguments=None, **kwargs):
        routed = dict(arguments or {})
        if self.binding.database_required and name not in MANAGEMENT_TOOL_NAMES:
            supplied = routed.get("database")
            if supplied is not None and supplied != self.binding.session_id:
                raise McpDatabaseSelectionError(
                    f"tool {name} database {supplied!r} conflicts with bound database {self.binding.session_id!r}"
                )
            routed["database"] = self.binding.session_id
        result = await self.raw_session.call_tool(name=name, arguments=routed, **kwargs)
        if getattr(result, "isError", False):
            message = _tool_result_error_text(result)
            raise McpToolCallError(f"MCP tool {name} failed: {message}")
        return result


def _tool_result_payload(result):
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    text = getattr(content[0], "text", None) if content else None
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tool_result_error_text(result):
    payload = _tool_result_payload(result)
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"]
    content = getattr(result, "content", None) or []
    text = getattr(content[0], "text", None) if content else None
    return text if isinstance(text, str) and text else "unknown MCP tool error"
```

In legacy auto-start mode, construct the binding with `backend="worker"` and `owned=True` so graceful cleanup preserves old behavior. In legacy attach-existing mode, use `owned=False` so external services are never closed automatically.

- [ ] **Step 5: Implement unified context manager**

Use one private raw-session context for both supervisor probing and bound sessions:

```python
@asynccontextmanager
async def _open_raw_ida_mcp_session(host, port, connect_timeout, read_timeout):
    server_url = f"http://{host}:{port}/mcp"
    async with AsyncExitStack() as stack:
        http_client = await stack.enter_async_context(
            httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(connect_timeout, read=read_timeout),
                trust_env=False,
            )
        )
        read_stream, write_stream, _ = await stack.enter_async_context(
            streamable_http_client(
                server_url,
                http_client=http_client,
                terminate_on_close=False,
            )
        )
        raw_session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await raw_session.initialize()
        yield raw_session


async def check_ida_mcp_supervisor_health(host, port):
    try:
        async with _open_raw_ida_mcp_session(host, port, 10.0, 15.0) as raw_session:
            await raw_session.list_tools()
            return True
    except Exception:
        return False


@asynccontextmanager
async def open_ida_mcp_session(
    host,
    port,
    *,
    expected_binary=None,
    explicit_database=None,
    auto_started=False,
    connect_timeout=10.0,
    read_timeout=300.0,
):
    try:
        async with _open_raw_ida_mcp_session(
            host, port, connect_timeout, read_timeout
        ) as raw_session:
            tools = (await raw_session.list_tools()).tools
            database_required = detect_database_requirement(tools)
            if database_required:
                listed = await raw_session.call_tool(name="idb_list", arguments={})
                if getattr(listed, "isError", False):
                    raise McpToolCallError(
                        f"MCP tool idb_list failed: {_tool_result_error_text(listed)}"
                    )
                payload = _tool_result_payload(listed) or {}
                selected = select_database_session(
                    payload.get("sessions", []),
                    expected_binary=expected_binary,
                    explicit_database=explicit_database,
                )
                binding = McpDatabaseBinding(
                    True,
                    selected["session_id"],
                    selected.get("input_path"),
                    selected.get("backend"),
                    bool(selected.get("owned")),
                    auto_started,
                )
            else:
                binding = McpDatabaseBinding(
                    False,
                    None,
                    str(expected_binary) if expected_binary else None,
                    "worker" if auto_started else None,
                    auto_started,
                    auto_started,
                )
            yield DatabaseBoundSession(raw_session, binding)
    except (McpContractError, McpDatabaseSelectionError, McpToolCallError):
        raise
    except Exception as exc:
        raise McpConnectionError(
            f"unable to open IDA MCP session at {host}:{port}: {exc}"
        ) from exc
```

Wrap transport/initialize/list failures as:

```python
raise McpConnectionError(f"unable to open IDA MCP session at {host}:{port}: {exc}") from exc
```

- [ ] **Step 6: Run Task 2 tests**

Run:

```powershell
uv run python -m unittest tests.test_ida_mcp_session -v
```

Expected: all adapter tests pass.

---

### Task 3: Migrate Binary Verification and Health Checks

**Files:**
- Modify: `ida_analyze_bin.py:40-60`
- Modify: `ida_analyze_bin.py:487-778`
- Modify: `tests/test_ida_analyze_bin.py:150-340`

**Interfaces:**
- Consumes: `open_ida_mcp_session()`, `normalize_binary_identity_path()`, `McpToolCallError`.
- Produces: `check_mcp_supervisor_health(host, port) -> bool`
- Produces: `check_mcp_worker_health(host, port, expected_binary) -> bool`
- Updates: `survey_binary_via_mcp(..., expected_binary=None, explicit_database=None)`

- [ ] **Step 1: Replace the transport-specific survey test with adapter wiring tests**

```python
async def test_survey_binary_via_mcp_binds_expected_binary(self) -> None:
    session = MagicMock()
    session.call_tool = AsyncMock(side_effect=[
        _tool_result({"metadata": {"path": "server.dll"}}),
        _tool_result({"result": json.dumps({"metadata": {"path": "server.dll.i64"}})}),
    ])
    context = _async_context(session)
    with patch.object(ida_analyze_bin, "open_ida_mcp_session", return_value=context) as open_session:
        result = await ida_analyze_bin.survey_binary_via_mcp(
            "127.0.0.1",
            13337,
            expected_binary=r"D:\repo\server.dll",
        )
    self.assertEqual("server.dll.i64", result["metadata"]["path"])
    open_session.assert_called_once_with(
        "127.0.0.1",
        13337,
        expected_binary=r"D:\repo\server.dll",
    )
```

- [ ] **Step 2: Add a regression test that real MCP errors do not retry**

```python
def test_verification_does_not_retry_mcp_tool_error(self) -> None:
    with TemporaryDirectory() as temp_dir:
        binary = Path(temp_dir) / "server.dll"
        binary.write_bytes(b"fixture")
        with (
            patch.object(
                ida_analyze_bin,
                "survey_binary_via_mcp",
                new=AsyncMock(side_effect=McpToolCallError("survey_binary: database is required")),
            ) as survey,
            patch.object(ida_analyze_bin.time, "sleep") as sleep,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertFalse(ida_analyze_bin.verify_opened_binary_via_mcp(str(binary), "windows"))
    self.assertEqual(1, survey.await_count)
    sleep.assert_not_called()
    self.assertIn("database is required", stdout.getvalue())
```

- [ ] **Step 3: Add separate supervisor and worker health tests**

Supervisor health delegates to `check_ida_mcp_supervisor_health()` from Task 2, which performs initialize/list-tools without database resolution. Worker health opens a bound session with `expected_binary` and calls `py_eval(code="1")`.

- [ ] **Step 4: Run tests and confirm failure**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin.TestSurveyBinaryViaSession -v
uv run python -m unittest tests.test_ida_analyze_bin.TestOpenedBinaryIdentityValidation -v
```

Expected: failures because `ida_analyze_bin.py` still creates raw sessions and does not expose separate health functions.

- [ ] **Step 5: Migrate imports and path normalization**

Remove direct `ClientSession` and `streamable_http_client` imports from `ida_analyze_bin.py`. Import:

```python
from ida_mcp_session import (
    McpConnectionError,
    McpDatabaseSelectionError,
    McpToolCallError,
    normalize_binary_identity_path,
    open_ida_mcp_session,
)
```

Delete `_strip_ida_database_suffix()` and `_normalize_binary_identity_path()`. Update opened-binary validation to call `normalize_binary_identity_path()`.

- [ ] **Step 6: Migrate survey and verification**

Change `survey_binary_via_mcp()` to use the unified context and pass `expected_binary`. Let typed MCP exceptions propagate to `verify_opened_binary_via_mcp()`. Retry only when a successful call returns no metadata or an empty opened path; typed connection, contract, selection, and tool errors must print once and stop.

- [ ] **Step 7: Split health semantics**

Implement supervisor health from initialize/tools-list and worker health from a bound `py_eval`. Change `ensure_mcp_available()` to call worker health with the current `binary_path`; only restart the `process` object supplied by the current flow.

- [ ] **Step 8: Run Task 3 tests**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin -v
```

Expected: the existing `ida_analyze_bin` suite and new verification/health regressions pass.

---

### Task 4: Migrate Analysis, Post-Process, Vcall, and Preprocessor Entry Points

**Files:**
- Modify: `ida_analyze_bin.py:741-890`
- Modify: `ida_analyze_bin.py:1299-1368`
- Modify: `ida_analyze_bin.py:2600-2880`
- Modify: `ida_skill_preprocessor.py:1-180`
- Modify: `tests/test_ida_analyze_bin.py:913-1180`
- Modify: `tests/test_ida_preprocessor_scripts.py:1790-2225`

**Interfaces:**
- Consumes: unified session context.
- Updates: `validate_expected_input_artifacts_via_mcp(..., expected_binary=None, explicit_database=None)`
- Updates: `post_process_expected_outputs_via_mcp(..., expected_binary=None, explicit_database=None)`
- Updates: `preprocess_single_vcall_object_via_mcp(..., expected_binary=None, explicit_database=None)`
- Updates: `preprocess_single_skill_via_mcp(..., expected_binary=None, explicit_database=None)`

- [ ] **Step 1: Add failing parameter-forwarding tests**

For each entry point, patch `open_ida_mcp_session` and assert it receives the current `binary_path`. Update process-loop tests to assert `_run_validate_expected_input_artifacts_via_mcp`, `_run_preprocess_single_skill_via_mcp`, `preprocess_single_vcall_object_via_mcp`, and `_run_post_process_expected_outputs_via_mcp` receive `expected_binary=binary_path`.

Representative assertion:

```python
mock_preprocess.assert_called_once_with(
    host="127.0.0.1",
    port=13337,
    skill_name="find-example",
    expected_outputs=expected_outputs,
    old_yaml_map=None,
    new_binary_dir=binary_dir,
    platform="windows",
    expected_binary=binary_path,
    debug=False,
    llm_model=None,
    llm_apikey=None,
    llm_baseurl=None,
    llm_temperature=None,
    llm_effort=None,
    llm_fake_as=None,
    llm_max_retries=None,
)
```

- [ ] **Step 2: Run the affected tests and confirm failure**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin.TestPostProcessMcpExecution -v
uv run python -m unittest tests.test_ida_preprocessor_scripts.TestPreprocessSingleSkillViaMcp -v
```

Expected: parameter and patch-target failures because the entry points still construct raw sessions.

- [ ] **Step 3: Migrate the remaining `ida_analyze_bin.py` contexts**

Replace raw transport blocks in expected-input validation, post-process, and vcall export with:

```python
async with open_ida_mcp_session(
    host,
    port,
    expected_binary=expected_binary,
    explicit_database=explicit_database,
) as session:
    return await existing_via_session_helper(session, ...)
```

Add `expected_binary=binary_path` at every process-loop call site.

- [ ] **Step 4: Migrate `ida_skill_preprocessor.py`**

Remove direct HTTP/MCP imports. Add `expected_binary=None` and `explicit_database=None` to `preprocess_single_skill_via_mcp()`. Open one bound session, query image base through that session, and pass the same wrapper into the selected preprocessor script.

- [ ] **Step 5: Preserve the compatibility fallback in `_run_preprocess_single_skill_via_mcp()`**

Include `expected_binary` in `preprocess_kwargs`. When supporting tests or injected legacy functions with older signatures, remove `expected_binary` and `explicit_database` together with the existing optional LLM arguments only after confirming `TypeError` reports an unexpected keyword.

- [ ] **Step 6: Run Task 4 tests**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin -v
uv run python -m unittest tests.test_ida_preprocessor_scripts -v
uv run python -m unittest tests.test_ida_analyze_util -v
uv run python -m unittest tests.test_ida_vcall_finder -v
```

Expected: all existing downstream helpers pass unchanged through the bound wrapper.

---

### Task 5: Implement Safe Targeted Cleanup

**Files:**
- Modify: `ida_analyze_bin.py:932-1045`
- Modify: `ida_analyze_bin.py:2379-2895`
- Modify: `tests/test_ida_analyze_bin.py:64-148`
- Modify: `tests/test_ida_analyze_bin.py:2399-2635`

**Interfaces:**
- Consumes: `DatabaseBoundSession.binding.should_auto_quit`.
- Updates: `quit_ida_via_mcp(host, port, *, expected_binary, auto_started) -> bool`
- Updates: `quit_ida_gracefully_async(process, host, port, *, expected_binary, debug=False)`
- Updates: `quit_ida_gracefully(process, host, port, *, expected_binary, debug=False)`

- [ ] **Step 1: Write the cleanup decision matrix tests**

```python
async def test_quit_owned_auto_started_worker(self) -> None:
    session = MagicMock()
    session.binding = McpDatabaseBinding(True, "server-db", "server.dll", "worker", True, True)
    session.call_tool = AsyncMock()
    with patch.object(ida_analyze_bin, "open_ida_mcp_session", return_value=_async_context(session)):
        self.assertTrue(
            await ida_analyze_bin.quit_ida_via_mcp(
                "127.0.0.1", 13337, expected_binary="server.dll", auto_started=True
            )
        )
    session.call_tool.assert_awaited_once_with("py_eval", {"code": "import idc; idc.qexit(0)"})

async def test_does_not_quit_adopted_worker(self) -> None:
    session = MagicMock()
    session.binding = McpDatabaseBinding(True, "server-db", "server.dll", "worker", False, True)
    session.call_tool = AsyncMock()
    with patch.object(ida_analyze_bin, "open_ida_mcp_session", return_value=_async_context(session)):
        self.assertFalse(
            await ida_analyze_bin.quit_ida_via_mcp(
                "127.0.0.1", 13337, expected_binary="server.dll", auto_started=True
            )
        )
    session.call_tool.assert_not_awaited()
```

Add equivalent no-quit tests for `backend="gui"` and `auto_started=False`.

- [ ] **Step 2: Add failure-path tests**

Assert that a database-selection failure skips `qexit`, and `quit_ida_gracefully_async()` still calls `stop_idalib_mcp_process(process)` only for the supplied process. Preserve the opened-binary verification failure behavior: if the target cannot be verified or safely selected, stop the local supervisor without contacting an unknown worker.

- [ ] **Step 3: Run cleanup tests and confirm failure**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin.TestQuitIdaGracefully -v
uv run python -m unittest tests.test_ida_analyze_bin.TestProcessBinaryOpenedBinaryVerification -v
```

Expected: failures because current cleanup does not inspect binding ownership/backend and does not receive the binary path.

- [ ] **Step 4: Implement targeted qexit**

Open a bound session using `expected_binary` and `auto_started=True`. Send `qexit` only when `binding.should_auto_quit` is true. Return false without calling any tool for adopted workers, GUI sessions, attach-existing flows, or unresolved databases.

- [ ] **Step 5: Thread `binary_path` through process cleanup**

Update every `quit_ida_gracefully()` and `quit_ida_gracefully_async()` call to provide `expected_binary=binary_path`. Keep `stop_idalib_mcp_process()` limited to the supplied `Popen` object; do not add PID enumeration.

- [ ] **Step 6: Run Task 5 tests**

Run:

```powershell
uv run python -m unittest tests.test_ida_analyze_bin -v
```

Expected: cleanup matrix, verification failure, and process ownership tests pass.

---

### Task 6: Migrate Reference YAML Generation and Add Explicit Database CLI

**Files:**
- Modify: `generate_reference_yaml.py:15-25`
- Modify: `generate_reference_yaml.py:107-143`
- Modify: `generate_reference_yaml.py:585-790`
- Modify: `tests/test_generate_reference_yaml.py:350-430`
- Modify: `tests/test_generate_reference_yaml.py:947-1265`
- Modify: `tests/test_generate_reference_yaml.py:1331-1590`

**Interfaces:**
- Consumes: `open_ida_mcp_session()`.
- Produces CLI option: `-mcp_database <session_id>`.
- Updates: `attach_existing_mcp_session(..., expected_binary=None, explicit_database=None)`.
- Updates: `autostart_mcp_session(..., explicit_database=None)`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_parse_args_accepts_explicit_mcp_database(self) -> None:
    args = generate_reference_yaml.parse_args(
        ["-func_name", "Example", "-mcp_database", "server-db"]
    )
    self.assertEqual("server-db", args.mcp_database)
```

Keep `-binary` paired with `-auto_start_mcp`; attach-existing callers select by `-mcp_database` when multiple sessions exist.

- [ ] **Step 2: Write failing session-mode tests**

Assert attach-existing passes `explicit_database`, autostart passes `expected_binary=args.binary` and `auto_started=True`, and both yield the bound session returned by the unified context manager. Remove assertions against local `streamable_http_client` and `ClientSession` fakes.

- [ ] **Step 3: Write a regression test that target resolution does not open a second session**

```python
async def test_resolve_generation_target_uses_existing_bound_session_only(self) -> None:
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=_tool_result({"metadata": {"path": "D:/repo/bin/14168/server/server.dll.i64"}})
    )
    target = await generate_reference_yaml.resolve_generation_target(
        session=session,
        gamever=None,
        module=None,
        platform=None,
    )
    self.assertEqual({"gamever": "14168", "module": "server", "platform": "windows"}, target)
```

Remove the host/port fallback parameters from `resolve_generation_target()` so survey cannot silently reconnect to a different database.

- [ ] **Step 4: Run affected tests and confirm failure**

Run:

```powershell
uv run python -m unittest tests.test_generate_reference_yaml.TestReferenceYamlPureHelpers -v
uv run python -m unittest tests.test_generate_reference_yaml.TestMcpSessionModes -v
uv run python -m unittest tests.test_generate_reference_yaml.TestRunReferenceGeneration -v
```

Expected: failures because the CLI and session managers do not expose database selection.

- [ ] **Step 5: Migrate generator session creation**

Remove local HTTP/MCP imports and `_open_mcp_session()`. Implement attach/autostart contexts as thin wrappers around `open_ida_mcp_session()`. Convert `McpConnectionError`, `McpDatabaseSelectionError`, and `McpToolCallError` into `ReferenceGenerationError` while preserving their messages.

- [ ] **Step 6: Keep the whole generation run on one bound session**

Use the yielded session for survey, function resolution, and export. Do not call `survey_binary_via_mcp(host, port)` as fallback.

- [ ] **Step 7: Run Task 6 tests**

Run:

```powershell
uv run python -m unittest tests.test_generate_reference_yaml -v
```

Expected: all generator tests pass with the new CLI and shared bound session.

---

### Task 7: Add Boundary Guard and 2.0.0 Smoke Harness

**Files:**
- Modify: `tests/test_ida_mcp_session.py`
- Create: `tests/smoke_ida_mcp_2.py`
- Local fixture only: `tests/bin/ida-mcp-smoke.dll`
- Modify: `docs/superpowers/specs/2026-07-11-ida-mcp-database-routing-design.md`

**Interfaces:**
- Produces: static test preventing raw MCP transport creation outside `ida_mcp_session.py`.
- Produces: manually invoked 2.0.0 smoke harness.

- [ ] **Step 1: Add the static boundary test**

Parse production Python files with `ast`. Fail when a file other than `ida_mcp_session.py` imports `ClientSession` from `mcp` or `streamable_http_client` from `mcp.client.streamable_http`.

```python
class TestMcpSessionBoundary(unittest.TestCase):
    def test_only_adapter_creates_raw_mcp_sessions(self) -> None:
        violations = []
        for path in Path(__file__).resolve().parents[1].rglob("*.py"):
            if any(part in {"tests", ".venv", "bin", ".git"} for part in path.parts):
                continue
            if path.name == "ida_mcp_session.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in {
                    "mcp",
                    "mcp.client.streamable_http",
                }:
                    names = {alias.name for alias in node.names}
                    if names & {"ClientSession", "streamable_http_client"}:
                        violations.append(f"{path}:{node.lineno}")
        self.assertEqual([], violations)
```

- [ ] **Step 2: Run the boundary test and confirm failure before final migration cleanup**

Run:

```powershell
uv run python -m unittest tests.test_ida_mcp_session.TestMcpSessionBoundary -v
```

Expected before stale imports are removed: FAIL listing `ida_analyze_bin.py`, `generate_reference_yaml.py`, or `ida_skill_preprocessor.py`. Remove those imports and rerun until PASS.

- [ ] **Step 3: Create the smoke harness**

`tests/smoke_ida_mcp_2.py` must:

1. Resolve its default binary to `tests/bin/ida-mcp-smoke.dll`.
2. Refuse to run when the fixture does not exist.
3. Start `idalib-mcp --unsafe --host <host> --port <port> <binary>` using the repository startup helper.
4. Wait for the supervisor port.
5. Open a bound session with `expected_binary=<fixture>` and `auto_started=True`.
6. Call `survey_binary(detail_level="minimal")` and assert normalized metadata path equals the fixture.
7. Copy the fixture into a temporary directory, call management tool `idb_open` for the copy, then assert a selector-free connection raises `McpDatabaseSelectionError` because two active sessions exist.
8. Reconnect with `explicit_database=<first_session_id>` and verify survey still targets the original fixture.
9. Close the owned original worker through targeted cleanup.
10. Reconnect with `explicit_database=<second_session_id>` and issue a targeted `qexit` for the second worker created by the harness.
11. Stop only the supervisor process created by the harness.
12. Capture server stderr and fail if it contains `Session termination failed: 501`.

Expose exact CLI arguments:

```python
parser.add_argument("--binary", default=str(Path(__file__).parent / "bin" / "ida-mcp-smoke.dll"))
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=13347)
parser.add_argument("--ida-args", default="")
```

- [ ] **Step 4: Verify the fixture is ignored**

Run:

```powershell
git check-ignore -v tests/bin/ida-mcp-smoke.dll
```

Expected: `.gitignore` reports the existing `bin` rule.

- [ ] **Step 5: Run the smoke harness against 2.0.0**

Precondition: place a small valid Windows DLL at `tests/bin/ida-mcp-smoke.dll`.

Run:

```powershell
uv run python tests/smoke_ida_mcp_2.py --binary tests/bin/ida-mcp-smoke.dll
```

Expected output includes:

```text
contract=database-required
selected_database=<non-empty-session-id>
survey_path=<absolute-path-to-tests/bin/ida-mcp-smoke.dll.i64>
multiple_database_guard=passed
targeted_owned_worker_quit=passed
session_termination_501=absent
```

- [ ] **Step 6: Perform the non-owned safety smoke check**

Start a separate `idalib-mcp 2.0.0` supervisor manually for the fixture, then run the harness in attach-existing mode with its session id. Confirm the harness reports `owned=false` or `auto_started=false` and does not call `qexit`. Verify the manually started worker remains listed as active after the harness exits.

---

### Task 8: Full Regression and Delivery Verification

**Files:**
- Verify all files changed by Tasks 1-7.

**Interfaces:**
- Consumes: complete compatibility implementation.
- Produces: verified working tree ready for user review.

- [ ] **Step 1: Run focused adapter and entry-point tests**

```powershell
uv run python -m unittest tests.test_ida_mcp_session -v
uv run python -m unittest tests.test_ida_analyze_bin -v
uv run python -m unittest tests.test_generate_reference_yaml -v
uv run python -m unittest tests.test_ida_preprocessor_scripts -v
uv run python -m unittest tests.test_ida_analyze_util -v
uv run python -m unittest tests.test_ida_vcall_finder -v
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Run complete Python regression**

```powershell
uv run python -m unittest discover -s tests
```

Expected: zero failures and zero errors.

- [ ] **Step 3: Format changed Python files**

```powershell
uv run ruff format ida_mcp_session.py ida_analyze_bin.py generate_reference_yaml.py ida_skill_preprocessor.py tests/test_ida_mcp_session.py tests/test_ida_analyze_bin.py tests/test_generate_reference_yaml.py tests/test_ida_preprocessor_scripts.py tests/smoke_ida_mcp_2.py
```

Expected: command exits with code 0.

- [ ] **Step 4: Run formatting and lint checks**

```powershell
uv run ruff format --check ida_mcp_session.py ida_analyze_bin.py generate_reference_yaml.py ida_skill_preprocessor.py tests/test_ida_mcp_session.py tests/test_ida_analyze_bin.py tests/test_generate_reference_yaml.py tests/test_ida_preprocessor_scripts.py tests/smoke_ida_mcp_2.py
uv run ruff check ida_mcp_session.py ida_analyze_bin.py generate_reference_yaml.py ida_skill_preprocessor.py tests/test_ida_mcp_session.py tests/test_ida_analyze_bin.py tests/test_generate_reference_yaml.py tests/test_ida_preprocessor_scripts.py tests/smoke_ida_mcp_2.py
```

Expected: both commands exit with code 0 and report no violations.

- [ ] **Step 5: Run diff and workspace checks**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; `1.log` and `tests/bin/ida-mcp-smoke.dll` remain untracked/ignored user-local assets and are not modified or staged.

- [ ] **Step 6: Run final 2.0.0 smoke verification**

```powershell
uv run python tests/smoke_ida_mcp_2.py --binary tests/bin/ida-mcp-smoke.dll
```

Expected: the six success markers from Task 7 appear and no 501 message is present.

- [ ] **Step 7: Review checkpoint**

Inspect:

```powershell
git diff --stat
git diff -- ida_mcp_session.py ida_analyze_bin.py generate_reference_yaml.py ida_skill_preprocessor.py
```

Confirm the implementation remains focused on MCP compatibility and contains no dependency, configuration, schema, or unrelated analysis changes.
