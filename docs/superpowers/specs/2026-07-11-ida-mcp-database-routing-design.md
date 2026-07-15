# IDA MCP Database Routing 兼容设计

## 背景

仓库通过 Python MCP SDK 主动连接 `ida-pro-mcp`，并在多个入口中调用 `survey_binary`、`py_eval`、
`find_bytes`、`rename`、`define_func`、`set_comments` 与 `get_int` 等 IDA worker 工具。

旧版 `ida-pro-mcp` 使用单数据库模型，worker 工具不需要显式数据库参数。`ida-pro-mcp 2.0.0`
将 `idalib-mcp` 改为多数据库 supervisor：除 `idb_open` 与 `idb_list` 外，每个 worker 工具调用都必须携带
`database=<session_id>`。

当前生产代码共有 75 处主动 `call_tool`，分布在 17 个文件，均未传入 `database`。服务端因此返回
`isError=true`，但部分调用路径没有检查 `isError`，最终将明确的契约错误降级为
`survey_binary returned no metadata`、空结果或静默 fallback。

此外，MCP SDK 默认在 transport 关闭时发送 `DELETE /mcp`，而当前 zeromcp 不支持 session termination，
会产生重复的 `Session termination failed: 501`。2.0.0 还将 supervisor 与 worker 生命周期分离，
worker 会在 supervisor 退出后继续存活，不能继续把二者视为同一个进程。

## 目标

- 同时兼容旧版单数据库 `ida-pro-mcp` 与 2.0.0 多数据库 supervisor。
- 通过 `tools/list` 动态检测 worker 工具是否要求 `database`，不依赖硬编码版本号。
- 在统一 session 适配层中完成 database 选择与参数注入，避免逐个修改 75 个调用点。
- 多数据库选择采用 fail-closed 策略，禁止静默选择错误 binary。
- 保留服务端 `isError` 的真实错误信息，不再降级为无 metadata 或空结果。
- 区分 supervisor health 与目标 worker health。
- 仅关闭当前自动启动流程拥有的 headless worker，不关闭 adopted worker、GUI 或外部服务。
- 所有主动 MCP transport 禁止自动 session termination，消除 zeromcp 501 日志。

## 非目标

- 不修改 `ida-pro-mcp` 或 zeromcp 的服务端实现。
- 不改变 75 个业务调用点的工具参数结构。
- 不为外部 Claude/Codex Agent 的 MCP 工具调用注入 database；外部 Agent 继续依据服务端 schema 调用。
- 不自动关闭 GUI IDA。
- 不关闭由其他 supervisor 或客户端创建、采用或复用的 worker。
- 不引入新的第三方依赖。

## 总体架构

新增独立模块 `ida_mcp_session.py`，集中负责 MCP transport、契约检测、database 解析、工具调用包装和错误转换。

业务入口不再直接创建 `httpx.AsyncClient`、`streamable_http_client` 或 `ClientSession`，而是通过
`open_ida_mcp_session()` 获取 `DatabaseBoundSession`。现有 helper、vcall finder 和 preprocessor scripts 继续调用
`session.call_tool()`；wrapper 在 2.0.0 模式下注入 database，在旧版模式下原样透传。

该边界保证：

- 兼容策略集中在一个文件中。
- 业务代码不需要知道 MCP server 是旧版还是 supervisor 2.0.0。
- 后续新增主动 MCP 入口时，可以通过静态测试阻止绕过统一适配层。

## 核心组件

### `McpDatabaseBinding`

使用 dataclass 保存一次连接解析出的稳定上下文：

```python
@dataclass(frozen=True)
class McpDatabaseBinding:
    database_required: bool
    session_id: str | None
    input_path: str | None
    backend: str | None
    owned: bool
    auto_started: bool
```

- 旧版模式下 `database_required=False`，其余数据库字段允许为空。
- 2.0.0 模式下 `session_id` 必须非空。
- `auto_started` 由调用方提供，表示当前代码是否启动了对应 supervisor。
- `owned` 与 `backend` 来自 `idb_list` 的目标 session 元数据。

### `DatabaseBoundSession`

wrapper 持有原始 MCP `ClientSession` 与 `McpDatabaseBinding`，对外保留异步 `call_tool()` 接口。

调用规则：

1. 旧版模式原样转发工具名和 arguments。
2. `idb_open`、`idb_list` 属于 supervisor management tools，永不注入 database。
3. 2.0.0 worker 工具自动加入 `database=binding.session_id`。
4. 调用方未传 database 时正常注入。
5. 调用方传入与 binding 相同的 database 时允许调用。
6. 调用方传入不同 database 时抛出明确的路由冲突异常。
7. 服务端返回 `isError=true` 时抛出包含工具名和服务端文本的 `McpToolCallError`。

wrapper 通过属性代理保留必要的原始 session 能力，但业务代码不得依赖 transport 内部字段。

### `open_ida_mcp_session()`

统一异步 context manager 接口：

```python
@asynccontextmanager
async def open_ida_mcp_session(
    host: str,
    port: int,
    *,
    expected_binary: str | os.PathLike[str] | None = None,
    explicit_database: str | None = None,
    auto_started: bool = False,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
) -> AsyncIterator[DatabaseBoundSession]:
    ...
```

context manager 统一完成：

1. 创建 `httpx.AsyncClient`。
2. 使用 `streamable_http_client(..., terminate_on_close=False)` 建立 transport。
3. 创建并 initialize 原始 `ClientSession`。
4. 调用 `tools/list` 检测契约。
5. 必要时调用 `idb_list` 并解析目标 database。
6. yield `DatabaseBoundSession`。
7. 关闭客户端资源，但不发送 `DELETE /mcp`。

## 契约检测

检测逻辑使用 `tools/list` 返回的 input schema，不读取安装包版本号。

- 若已知 worker 工具的 `required` 包含 `database`，进入 supervisor 2.0.0 模式。
- 若 worker 工具存在但不要求 `database`，进入旧版 passthrough 模式。
- 若不同 worker 工具对 database 要求不一致，视为服务端契约异常并明确失败。
- `idb_open` 与 `idb_list` 不参与 worker 契约判断。
- 至少检查仓库实际使用的工具集合：`py_eval`、`survey_binary`、`find_bytes`、`rename`、
  `define_func`、`set_comments`、`get_int`。

使用 schema 检测而不是版本判断，可以兼容未来回移、分支版本或自定义服务端。

## Database 选择策略

2.0.0 模式下先调用 `idb_list`，仅将满足以下条件的记录视为可路由 session：

- `is_active` 为真。
- `session_id` 是非空字符串。
- session 已被当前 supervisor 采用，能够接受带 database 的 worker 工具调用。

选择优先级：

1. **显式 session id**：必须命中唯一 active、可路由 session，否则失败。
2. **预期 binary 路径**：规范化路径后匹配 `input_path`，必须唯一命中。
3. **唯一 active session**：仅当未提供路径且恰好存在一个可路由 session 时自动选择。
4. **其他情况**：明确失败，不选择最近访问项或列表第一项。

路径规范化复用 opened binary verification 的规则：

- Windows 路径比较不区分大小写。
- 统一 `/` 与 `\\`。
- 去除末尾 `.i64` 或 `.idb`。
- 相对路径转为绝对路径。
- 支持 `/mnt/<drive>/...` 与 Windows drive path 的等价比较。

失败信息必须包含选择条件以及候选 session 的 `session_id`、`input_path`、`backend`、`owned` 与
`is_active`，便于用户显式选择。

## 健康检查

健康检查拆为两个层级：

### Supervisor health

- transport 能建立。
- `session.initialize()` 成功。
- `tools/list` 成功并返回可解析工具列表。

该检查不要求 database，可用于判断端口上的 MCP supervisor 是否响应。

### Worker health

- 先完成 database 解析。
- 通过 bound session 调用 `py_eval(code="1")`。
- `isError` 或调用异常均表示目标 worker 不健康。

`ensure_mcp_available()` 只有在当前流程持有 supervisor process 时才允许根据失败结果重启该 process。
外部服务健康失败时只返回错误，不终止未知进程。

## Binary Verification

`verify_opened_binary_via_mcp()` 必须将预期 binary 路径传入统一 session context。

- 旧版模式继续直接调用 `survey_binary`。
- 2.0.0 模式先按预期路径选择 session，再调用绑定后的 `survey_binary`。
- `survey_binary` 的真实 `isError` 不可进入 metadata retry。
- 只有成功调用但 metadata/path 暂时为空时才允许重试。
- database 缺失、选择冲突、工具错误和 schema 错误均立即失败并输出真实原因。

## 安全退出与进程生命周期

2.0.0 中 supervisor 与 worker 是独立进程。清理逻辑使用以下条件决定是否定向 `qexit`：

```text
binding.auto_started is True
and binding.owned is True
and binding.backend == "worker"
and binding.session_id is not None
```

全部满足时，通过同一个 bound session 调用：

```python
py_eval(code="import idc; idc.qexit(0)")
```

以下情况永不自动发送 `qexit`：

- `owned=false` 的 adopted worker。
- `backend=gui` 的 IDA GUI。
- attach existing MCP 模式。
- database 未通过预期 binary 或显式 session id 安全解析。
- 连接到了无法确认目标身份的旧版外部服务。

完成或失败后，只允许 terminate 当前代码持有的 supervisor `Popen` 对象。不得枚举或终止其他 IDA、Python、
worker 或 supervisor 进程。

若定向 `qexit` 失败：

- 输出目标 session id 与真实错误。
- 继续停止当前持有的 supervisor process。
- 不尝试终止未知 worker PID。

## 错误模型

新增明确异常类型：

- `McpContractError`：工具 schema 缺失、database 要求不一致或服务端契约无法识别。
- `McpDatabaseSelectionError`：显式 session 不存在、路径无匹配、路径多匹配或无条件多 session。
- `McpToolCallError`：服务端 `isError=true`，错误中包含 tool name 与服务端文本。
- `McpConnectionError`：transport、initialize 或 tools/list 失败。

业务入口根据现有返回类型捕获这些异常并打印上下文，但不得无提示地转换为空 dict、空 list、`None` 或成功状态。

## 入口迁移

### `ida_analyze_bin.py`

迁移以下主动连接路径：

- supervisor/worker health。
- opened binary survey verification。
- expected-input artifact validation。
- expected-output post-process。
- vcall object export。
- targeted worker quit。

这些函数增加 `expected_binary` 或 `explicit_database` 参数，并由当前 binary processing loop 传入已知 binary path。

### `generate_reference_yaml.py`

- `_open_mcp_session()` 改为调用统一 context manager。
- autostart 模式始终传入 `binary_path` 和 `auto_started=True`。
- attach existing 模式可传 binary path；无法提供路径且存在多个 active session 时明确失败。
- CLI 增加可选 `--mcp_database`，用于显式选择 supervisor session。
- generation target survey 和后续 `py_eval` 使用同一个 bound session，避免重复选择或跨 session。

### `ida_skill_preprocessor.py`

- 使用统一 context manager 创建 bound session。
- 调用方传入当前 binary path 或显式 database。
- image base 查询与下游 preprocessor 共用同一个 bound session。

### 下游 helpers

`ida_analyze_util.py`、`ida_vcall_finder.py` 和 `ida_preprocessor_scripts` 继续接收 session 并调用
`session.call_tool()`，不逐处增加 database 参数。

## 测试设计

新增 `tests/test_ida_mcp_session.py`，覆盖统一适配层：

- 旧版 schema 进入 passthrough 模式且不调用 `idb_list`。
- 2.0.0 schema 正确识别 database requirement。
- worker schema 要求不一致时失败。
- 显式 session id 优先且必须 active。
- 预期 binary 路径匹配，包含 `.i64`、`.idb`、大小写和分隔符变化。
- 未提供 selector 且仅一个 active session 时自动选择。
- 多个 active session 时失败并包含候选详情。
- 无 active session 或 session id 为空时失败。
- worker 工具自动注入 database。
- management tools 不注入 database。
- 相同显式 database 被接受，不同 database 被拒绝。
- `isError=true` 转换为 `McpToolCallError` 并保留服务端文本。
- transport 始终使用 `terminate_on_close=False`。

在现有入口测试中补充：

- verification 将 expected binary 传入统一 session context。
- 真实工具错误不进入 metadata retry。
- supervisor health 不依赖 worker database。
- worker health 通过 bound `py_eval` 检查。
- post-process、vcall export 和 preprocessor 使用 bound session。
- reference generator 正确传递 binary path 与 `--mcp_database`。
- 仅 `auto_started + owned + worker` 执行 `qexit`。
- adopted worker、GUI 和外部服务不执行 `qexit`。
- `qexit` 失败仍只停止当前持有的 supervisor process。

增加静态回归测试：除 `ida_mcp_session.py` 外，生产业务模块不得直接导入或实例化
`streamable_http_client` 与 MCP `ClientSession`。该测试防止未来新增入口绕过统一适配层。

## 验证策略

定向验证：

```powershell
uv run python -m unittest tests.test_ida_mcp_session
uv run python -m unittest tests.test_ida_analyze_bin
uv run python -m unittest tests.test_generate_reference_yaml
uv run python -m unittest tests.test_ida_preprocessor_scripts
```

完整 Python 回归：

```powershell
uv run python -m unittest discover -s tests
```

静态质量门禁：

```powershell
uv run ruff format --check ida_mcp_session.py ida_analyze_bin.py generate_reference_yaml.py ida_skill_preprocessor.py tests
uv run ruff check ida_mcp_session.py ida_analyze_bin.py generate_reference_yaml.py ida_skill_preprocessor.py tests
git diff --check
```

真实 2.0.0 smoke test：

1. 将 `tests/bin/server.dll` 或 `tests/bin/libserver.so` 及其同名 `.i64` 放入本地夹具目录。
   `tests/bin` 已被现有 `bin` ignore 规则覆盖，二进制与 IDB 均不纳入 Git。
2. 缺少 binary 或配套 `.i64` 时 harness 输出 `SKIPPED` 并以退出码 `0` 结束。
3. harness 在临时工作目录中复制 binary 与 `.i64` 后再启动 `idalib-mcp 2.0.0`，不直接打开或修改
   `tests/bin` 的源夹具。
4. 验证 survey 能返回匹配路径的 metadata。
5. 验证不存在重复 `Session termination failed: 501`。
6. 启动第二个 database，验证无 selector 时明确失败。
7. 指定 binary path 或 session id 后验证选择正确 session。
8. 验证自动启动且 owned 的 worker 被定向退出。
9. 定向退出 smoke harness 为多数据库测试创建的第二个 owned worker，避免留下测试进程。
10. 验证 adopted worker 与 GUI 不被关闭。

手动 smoke harness 位于 `tests/smoke_ida_mcp_2.py`。默认使用本地忽略的
`tests/bin/server.dll`，并启动自己的 supervisor：

```powershell
uv run python tests/smoke_ida_mcp_2.py
```

使用外部 supervisor 验证非 owned 安全性时，传入其 active session id；该模式不会发送 `qexit`：

```powershell
uv run python tests/smoke_ida_mcp_2.py --attach-existing --mcp-database <session-id> --binary tests/bin/libserver.so
```

旧版 smoke test：

1. 连接不要求 database 的旧版 server。
2. 验证工具调用 arguments 未被修改。
3. 验证 survey、preprocessor 和 reference generation 保持原行为。

## 验收标准

- 旧版单数据库 server 的现有主动 MCP 流程保持可用。
- 2.0.0 supervisor 下所有主动 worker 工具调用携带正确 database。
- 多 database 且无安全选择条件时明确失败，不操作任意 session。
- `survey_binary returned no metadata` 不再掩盖 database-required 或其他服务端错误。
- 所有主动 MCP 连接关闭时不再触发 session termination 501。
- 自动启动流程只关闭其拥有的 headless worker。
- adopted worker、GUI 与外部 MCP 服务不被自动关闭。
- 业务模块不再直接创建 MCP transport 或原始 `ClientSession`。
- 定向测试、完整回归、ruff 与 `git diff --check` 全部通过。
