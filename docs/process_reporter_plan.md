# Process Reporter 与 Redis 任务进度系统设计计划

## 背景

`ida_analyze_bin.py` 当前负责解析配置、按 module 和 platform 遍历二进制、对 skills 进行拓扑排序，并依次执行预处理器、Agent fallback、vcall finder 和可选 post-process。执行状态主要通过标准输出和最终的 `success_count`、`fail_count`、`skip_count` 汇总体现。

现有实现缺少以下能力：

- 无法从外部服务查询一次分析任务的完整结构和当前进度。
- Web 页面在任务执行途中上线时，无法取得已经完成的 skill 状态。
- 无法以统一方式展示 skill 依赖、拓扑顺序和跨 module stage 的执行关系。
- 无法可靠区分失败、跳过、因上游中止而未执行等不同结果。
- 多个 Analyzer 任务缺少统一的 FIFO 排队和历史任务索引。

本计划引入独立的 Process Reporter 抽象层，并使用 Redis 作为任务队列、当前状态存储、历史索引和实时事件流。Web 服务通过 FastAPI 提供状态快照查询和 SSE 实时推送。前端可将同一份 DAG 数据投影为思维导图、依赖图或列表。

## 设计结论

整体架构采用：

```text
任务提交方
    │
    ▼
Redis Run Queue
    │
    ▼
单并发 Scheduler
    │ 启动并等待
    ▼
ida_analyze_bin.py
    │ 仅依赖 ProcessReporter 抽象
    ▼
RedisProcessReporter
    ├─ Redis Hash：Run/Skill 最新状态
    ├─ Redis String：ExecutionPlan 和 DAG
    ├─ Redis Streams：实时状态事件
    ├─ Redis Sorted Set：历史任务索引
    └─ Heartbeat TTL：Analyzer 存活检测

FastAPI
    ├─ REST：历史任务、快照、DAG、Skill 详情
    └─ SSE：Redis Stream 增量事件
          │
          ▼
Web 页面
    ├─ 思维导图
    ├─ 真实依赖 DAG
    └─ 状态列表
```

核心依赖方向必须保持为：

```text
ida_analyze_bin.py ──> process_reporter.py <── process_reporter_redis.py
agent_runner.py ──> progress callback
```

`ida_analyze_bin.py` 和 `agent_runner.py` 中禁止直接调用 Redis API。

## 目标

- 为每次 `ida_analyze_bin.py` 运行生成唯一 `run_id`。
- 在 Analyzer 开始实际执行前发布完整 ExecutionPlan，使页面可立即展示全部任务结构。
- 保存每个 Run、Binary Job 和 Skill 的最新状态。
- 使用 Redis Streams 发布可恢复的实时事件，而不是只使用无回放能力的 Pub/Sub。
- 允许页面在任务开始前、执行中或结束后上线，并取得当前完整状态。
- 支持历史任务分页查询和已完成任务详情查看。
- 通过单并发 Scheduler 保证多个 Analyzer 按 FIFO 顺序执行。
- 通过 Heartbeat TTL 识别 Analyzer 崩溃、机器异常或失联。
- 使用 AOF `everysec` 在 Redis 重启后恢复历史任务和最终状态。
- 保留当前 CLI 未配置 Reporter 时的执行行为和测试兼容性。
- 允许未来将 Redis 实现替换为其他上报后端，而不修改分析执行逻辑。

## 非目标

- 本阶段不并行执行多个 Analyzer。
- 本阶段不改变 IDA MCP 的单端口和单二进制执行模型。
- 本阶段不以 Redis 保存完整 Agent stdout、IDA debug 日志或反编译内容。
- 本阶段不通过 Web 页面控制、取消或重试正在执行的 skill。
- 本阶段不重写现有预处理、Agent fallback、vcall finder 或 post-process 业务逻辑。
- 本阶段不要求将所有 module stage 合并为一个新的全局调度算法。
- 本阶段不使用 Redis Pub/Sub 作为唯一实时通道。

## 当前仓库约束

### Skill 依赖是 DAG，不是严格树

`topological_sort_skills()` 当前根据以下关系构造依赖：

- `expected_output` 到 `expected_input` 的 artifact 生产/消费关系。
- platform-specific input/output。
- 兼容旧配置的 `prerequisite`。

一个 skill 可以依赖多个生产者，一个生产者也可以被多个 skill 消费，因此真实结构是 Directed Acyclic Graph。可视化可以采用思维导图，但后端数据模型必须保留全部节点和边，不能只保存单父树。

### Module 名称不能作为唯一阶段标识

`config.yaml` 中允许同名 module 多次出现，用来表达跨二进制或跨阶段依赖。例如 engine 可以在 client 后再次执行，随后 client/server 又依赖这个后期 engine 阶段生成的 artifact。

因此必须引入稳定的 `stage_index`，不能仅用 `module_name` 标识任务阶段。

### 当前执行顺序需要保留

当前执行顺序是：

```text
config module stage 顺序
  -> platform 顺序
    -> stage 内 skill 拓扑顺序
      -> vcall finder
        -> post-process
```

第一阶段只对当前执行过程进行建模和上报，不应因可视化需求改变实际调度语义。

### 未执行任务不应统一记为失败

当前部分 MCP 或 binary verification 错误会把剩余工作量累加到 `fail_count`。新状态模型需要区分：

- 已实际执行并失败。
- 因上游或基础设施错误而未开始。
- 因平台、已有输出或 absent result 而跳过。

旧的最终计数可以继续兼容，但 API 应提供更精确的状态。

## ExecutionPlan 与 DAG

### 构图函数

将现有排序逻辑拆分为：

```python
def build_skill_graph(skills: list[dict]) -> SkillGraph:
    ...


def topological_sort_skills(skills: list[dict]) -> list[str]:
    return build_skill_graph(skills).order
```

`topological_sort_skills()` 保持现有公开行为，避免影响调用点和现有测试。

建议数据模型：

```python
@dataclass(frozen=True)
class SkillEdge:
    source: str
    target: str
    edge_type: str
    artifact: str | None = None


@dataclass(frozen=True)
class SkillGraph:
    nodes: dict[str, dict]
    edges: list[SkillEdge]
    order: list[str]
    layers: dict[str, int]
    cycles: list[list[str]]
```

### Edge 类型

- `artifact`：stage 内由 output/input 推导的依赖。
- `prerequisite`：显式旧配置依赖。
- `cross_stage_artifact`：解析完整 artifact 路径后识别的跨阶段依赖。
- `stage_order`：表示当前配置和执行流程中的控制顺序。

artifact 依赖和控制顺序需要在 API 中区分，前端分别以实线和虚线展示。

### Layer 计算

使用拓扑顺序计算节点层级：

```text
无依赖节点：layer = 0
其他节点：layer = 1 + max(layer[dependency])
```

层级仅用于布局，不替代真实依赖边。

### 循环依赖

第一阶段保留当前循环检测后的兼容执行行为，但 ExecutionPlan 必须记录：

- 检测到的循环节点。
- graph warning。
- fallback order。

页面应明确显示图异常，不能把 fallback order 误认为合法 DAG。

## 任务层级与标识

任务层级定义为：

```text
Run
  -> Module Stage
    -> Binary Job / Platform
      -> Skill
      -> VCall Target
      -> Post-process
```

建议标识格式：

```text
run_id      = ULID
stage_id    = stage-{stage_index:04d}-{module_name}
job_id      = {stage_id}-{platform}
skill_id    = {job_id}/{skill_name}
```

例如：

```text
01JABC.../stage-0008-engine/windows/find-CNetworkClientService_SendNetMessage
```

标识必须包含 `stage_index`，从而区分配置中重复出现的 engine、client、server 或 networksystem 阶段。

## 状态模型

### Run 状态

```text
queued
starting
running
succeeded
failed
aborted
stale
```

`stale` 可以由 API 根据 heartbeat 派生，也可以在 Scheduler 确认进程死亡后写入最终状态。

### Job 和 Skill 状态

```text
pending
running
succeeded
failed
skipped
aborted
```

### 执行 Phase

状态表示生命周期结果，phase 表示当前正在执行的内部步骤：

```text
preflight
waiting_for_mcp
validating_binary
validating_inputs
preprocessing
validating_outputs
agent_fallback
vcall_export
postprocessing
finished
```

### Reason

终态必须附带结构化原因，至少支持：

```text
existing_outputs
skip_if_exists
platform_mismatch
missing_binary
missing_input
invalid_input
preprocess_absent
optional_output_absent
preprocess_failed
agent_failed
mcp_unavailable
binary_verification_failed
upstream_aborted
graph_invalid
unknown_error
```

### 合法状态转换

典型转换：

```text
pending -> running -> succeeded
pending -> running -> failed
pending -> skipped
pending -> aborted
running -> aborted
```

禁止终态回退到 `pending` 或 `running`。如未来支持重试整个 Run，应创建新的 attempt 或新的 Run，而不是覆盖历史终态。

## Process Reporter 抽象

### `process_reporter.py`

该文件只包含领域抽象，不得导入 `redis`、FastAPI 或 Scheduler 实现。

建议包含：

- `RunStatus`
- `TaskStatus`
- `ProcessPhase`
- `ProcessEventType`
- `ProcessEvent`
- `ProcessReporter` Protocol 或 ABC
- `NullProcessReporter`
- Reporter 相关通用异常和 best-effort 策略

建议接口：

```python
class ProcessReporter(Protocol):
    def initialize_run(self, plan: dict, run_id: str | None = None) -> str:
        ...

    def emit(self, event: ProcessEvent) -> None:
        ...

    def heartbeat(self, run_id: str) -> None:
        ...

    def finalize_run(
        self,
        run_id: str,
        status: RunStatus,
        summary: dict[str, int],
    ) -> None:
        ...

    def flush(self) -> None:
        ...

    def close(self) -> None:
        ...
```

`NullProcessReporter` 是默认实现，确保未配置 Redis 时现有分析行为不变。

### `process_reporter_redis.py`

该文件实现真正的 Redis 写入操作：

- Redis 连接和健康检查。
- Run 初始化。
- ExecutionPlan/DAG 写入。
- Skill 最新状态写入。
- Redis Stream 事件发布。
- Run 汇总计数原子更新。
- Heartbeat TTL 刷新。
- `flush()` 和 `close()`。
- Redis 临时错误处理和重连。

`ida_analyze_bin.py` 和 `agent_runner.py` 中不得出现 `HSET`、`XADD`、Lua script 或 Redis key 拼接。

### `process_reporter_factory.py`

工厂负责根据 CLI 或环境配置构造 Reporter，并使用 lazy import 避免未启用 Redis 时要求导入 Redis 客户端：

```python
def create_process_reporter(args) -> ProcessReporter:
    if args.process_reporter == "redis":
        from process_reporter_redis import RedisProcessReporter

        return RedisProcessReporter(...)
    return NullProcessReporter()
```

建议配置：

```text
-process_reporter=none|redis
-redis_url=redis://127.0.0.1:6379/0
-redis_prefix=cs2vibe:analysis:v1
-run_id=<scheduler-created-id>
```

对应环境变量：

```text
CS2VIBE_PROCESS_REPORTER
CS2VIBE_REDIS_URL
CS2VIBE_REDIS_PREFIX
CS2VIBE_RUN_ID
```

### Reporter 失败策略

默认采用 best-effort：

- Redis 短暂不可用不能改变 IDA 分析本身的成功或失败结果。
- Reporter 错误需要输出清晰 warning。
- Reporter 恢复连接后应能够重新发送当前完整快照。
- Run/Skill 终态和进程退出前必须调用 `flush()`。

可选增加 strict 模式，用于要求状态上报失败即终止任务的部署环境，但不作为默认行为。

## `agent_runner.py` 接入边界

`agent_runner.py` 不直接依赖 Redis，也可以不直接依赖 `ProcessReporter`。推荐只新增通用 progress callback：

```python
def run_skill(
    ...,
    progress_callback=None,
):
    ...
```

Agent retry 循环上报：

- attempt 开始。
- attempt 失败原因。
- timeout。
- cybersecurity block。
- expected output 缺失。
- 最终成功或失败。

`ida_analyze_bin.py` 负责把 callback 转换为 `ProcessEvent`：

```python
def report_agent_progress(**progress):
    reporter.emit(
        ProcessEvent(
            run_id=run_id,
            task_id=skill_id,
            event_type=ProcessEventType.SKILL_PROGRESS,
            phase=ProcessPhase.AGENT_FALLBACK,
            payload=progress,
        )
    )
```

这样 `agent_runner.py` 仍可被其他脚本复用，不需要知道 Run、Redis key 或 API 协议。

## `ida_analyze_bin.py` 接入边界

### 初始化

在解析配置、应用 module/skill filter 并构造 ExecutionPlan 后：

```python
reporter = create_process_reporter(args)
run_id = reporter.initialize_run(plan, run_id=args.run_id)
```

ExecutionPlan 应在启动第一个 IDA 进程前写入 Redis，使页面能看到完整任务结构和全部 `pending` 节点。

### 过程上报

现有每个状态分支映射到明确事件，例如：

```text
Start skill                -> running/preflight
MCP available              -> running/validating_binary
Input validation           -> running/validating_inputs
Preprocessor start         -> running/preprocessing
Agent fallback start       -> running/agent_fallback
Output validation success  -> succeeded/finished
Existing outputs           -> skipped/existing_outputs
Missing input              -> failed/missing_input
Remaining after abort      -> aborted/upstream_aborted
```

### 收尾

顶层必须使用 `try/finally`：

```python
try:
    execute_plan(...)
except BaseException:
    reporter.finalize_run(run_id, RunStatus.FAILED, summary)
    raise
finally:
    reporter.flush()
    reporter.close()
```

正常退出时需要把所有未终结节点协调为 `aborted` 或相应的终态，避免历史任务永久保留 `running`。

## Redis 数据设计

### Key 前缀

默认前缀：

```text
cs2vibe:analysis:v1
```

所有 key 必须通过统一 Key Builder 生成，业务代码不得手写拼接。

### 历史 Run 索引

```text
cs2vibe:analysis:v1:runs
```

类型：Sorted Set。

```text
score  = created_at Unix timestamp
member = run_id
```

用于按时间倒序分页查询历史任务。

### 当前运行集合

```text
cs2vibe:analysis:v1:running
```

类型：Set。Run 进入运行状态时加入，进入终态后移除。

### Run 元数据

```text
cs2vibe:analysis:v1:run:{run_id}:meta
```

类型：Hash。建议字段：

```text
status
gamever
agent
created_at
started_at
finished_at
current_stage_id
current_job_id
current_skill_id
last_event_id
total
pending
running
succeeded
failed
skipped
aborted
config_path
```

敏感 CLI 参数、API key 和完整环境变量不得写入 Redis。

### ExecutionPlan/DAG

```text
cs2vibe:analysis:v1:run:{run_id}:graph
```

类型：String，内容为 JSON。该数据在 Run 初始化后视为不可变，包含：

```json
{
  "schema_version": 1,
  "stages": [],
  "jobs": [],
  "nodes": [],
  "edges": [],
  "warnings": []
}
```

### Skill 状态

```text
cs2vibe:analysis:v1:run:{run_id}:skill-status
cs2vibe:analysis:v1:run:{run_id}:skill-data
```

类型：Hash。

`skill-status` 保存精简状态，方便 Lua script 读取旧状态并调整汇总计数；`skill-data` 保存完整 JSON payload。

示例：

```json
{
  "status": "running",
  "phase": "agent_fallback",
  "reason": null,
  "attempt": 2,
  "max_attempts": 3,
  "started_at": "2026-07-13T10:00:00Z",
  "updated_at": "2026-07-13T10:02:10Z",
  "finished_at": null,
  "message": "Retrying Codex agent",
  "error": null,
  "revision": 4
}
```

### 实时事件流

```text
cs2vibe:analysis:v1:run:{run_id}:events
```

类型：Redis Stream。Redis Stream ID 直接作为事件位置和 SSE resume token。

事件示例：

```text
XADD ...:events MAXLEN ~ 10000 *
  type skill.status_changed
  task_id stage-0008-engine-windows/find-A
  status running
  phase agent_fallback
  attempt 2
```

### Heartbeat

```text
cs2vibe:analysis:v1:run:{run_id}:heartbeat
```

类型：带 TTL 的 String。

```text
SET heartbeat <worker_id> EX 30
```

Analyzer 每 5 到 10 秒刷新一次。Heartbeat 消失但 Run 仍为 `running` 时，API 显示 `stale`，Scheduler 负责确认进程状态并最终协调。

### Run Queue

```text
cs2vibe:analysis:v1:run-queue
```

类型：Redis Stream。提交请求包含：

```text
run_id
gamever
platforms
modules
skill_filter
agent
created_at
```

敏感配置通过受控环境或 secret 管理传给 Analyzer，不放入队列 payload。

## 原子状态更新

一次 Skill transition 必须原子完成：

1. 读取旧状态。
2. 校验状态转换是否合法或是否为幂等重放。
3. 更新 `skill-status`。
4. 更新 `skill-data`。
5. 调整 Run 汇总计数。
6. 更新 Run 当前节点字段。
7. `XADD` 状态事件。
8. 将返回的 Stream ID 写入 `last_event_id`。

推荐使用 Lua script 完成上述操作，避免 API 短暂读取到状态和计数不一致的快照。

每个 Skill payload 包含单调递增的 `revision`。重复或旧 revision 必须被忽略，从而支持 Reporter 重连后的幂等快照重放。

## Scheduler

### 职责

`process_scheduler_redis.py` 单独负责：

- 从 Run Queue 按 FIFO 获取任务。
- 将 Run 从 `queued` 更新为 `starting`。
- 启动 `ida_analyze_bin.py` 子进程并传入 `run_id`。
- 保持单并发执行。
- 等待子进程结束并 ACK queue entry。
- 处理 Scheduler 重启后的 pending entry。
- 协调失联或异常退出的 Run。

Scheduler 不负责写 Skill 细粒度状态，这些状态由 `RedisProcessReporter` 上报。

### 单并发保证

首个版本只部署一个 active Scheduler worker，执行并发度固定为 1。若未来部署多个 Scheduler 实例，需要额外引入带续租的 executor lease，确保任一时刻只有一个实例启动 Analyzer。

### 手工 CLI 兼容

直接运行 `ida_analyze_bin.py` 时：

- 未指定 `run_id`：Reporter 创建新的 Run。
- 指定 Scheduler 生成的 `run_id`：Reporter attach 到现有 `queued/starting` Run。
- 未启用 Reporter：使用 `NullProcessReporter`，行为与当前版本一致。

## Redis 读模型与 FastAPI

### `process_status_reader_redis.py`

该文件作为 Redis 读适配器，负责：

- 历史 Run 分页。
- Run meta 和 summary 查询。
- ExecutionPlan/DAG 查询。
- Skill 当前状态查询。
- Skill 详情查询。
- Redis Stream `XREAD`。

API 不应复用 `RedisProcessReporter` 作为查询对象，避免写模型和读模型职责混合。

### REST API

建议提供：

```text
GET /api/v1/runs
GET /api/v1/runs/{run_id}
GET /api/v1/runs/{run_id}/graph
GET /api/v1/runs/{run_id}/skills
GET /api/v1/runs/{run_id}/skills/{skill_id}
GET /api/v1/runs/{run_id}/events?after=<stream-id>
GET /api/v1/runs/{run_id}/stream?after=<stream-id>
```

`GET /runs` 支持：

- cursor 或 offset 分页。
- status filter。
- gamever filter。
- 时间倒序。

### 快照加增量协议

Web 页面加载流程：

1. 获取 Run meta、graph 和所有 Skill 最新状态。
2. 记录响应中的 `last_event_id`。
3. 使用 `after=last_event_id` 建立 SSE。
4. 按 Stream ID 顺序应用增量事件。
5. 根据 `task_id + revision` 忽略重复或旧事件。

即使在快照读取期间产生新事件，客户端也可以通过 revision 保证最终一致。

### SSE

FastAPI 使用异步 Redis 客户端执行：

```text
XREAD BLOCK <timeout> STREAMS <events-key> <last-event-id>
```

SSE 使用 Redis Stream ID 作为 `id:`，浏览器断线重连时可以通过 `Last-Event-ID` 恢复。

定期发送 SSE heartbeat comment，避免代理或负载均衡器关闭空闲连接。

## 可视化

### 后端数据保持 DAG

API 始终返回扁平结构：

```json
{
  "nodes": [],
  "edges": []
}
```

不能在后端永久丢弃多父关系并只保存嵌套树。

### 思维导图投影

页面默认可以使用可折叠思维导图：

```text
Run
  -> Stage
    -> Platform/Binary Job
      -> Root Skill
        -> Dependent Skill
```

多父 skill 的展示规则：

1. 无依赖：挂在对应 Binary Job 下。
2. 单依赖：挂在该依赖下。
3. 多依赖：选择 layer 最深、距离当前节点最近的依赖作为 display parent。
4. 其余依赖保留为 secondary dependency cross-link。

display parent 仅用于布局，不写回真实 DAG 数据。

### 依赖图视图

辅助视图直接展示真实 DAG：

- artifact dependency 使用实线。
- prerequisite 使用不同颜色实线。
- stage/control order 使用虚线。
- 选中节点时高亮 dependencies 和 dependents。

### 状态视觉

建议颜色：

```text
pending    灰色
running    蓝色并带轻量动态效果
succeeded  绿色
skipped    黄色
failed     红色
aborted    深灰色
```

节点详情显示：

- Skill 名称。
- 当前 status/phase。
- attempt/max attempts。
- expected inputs/outputs。
- 开始时间、结束时间和耗时。
- reason/error summary。
- dependencies/dependents。

### 大规模节点

部分 module stage 包含数百个 skills，因此必须：

- 默认折叠到 Stage/Platform/Root Skill。
- 自动展开当前运行节点路径。
- 提供仅看 running/failed/skipped 的过滤器。
- 支持按 skill 名称搜索和定位。
- 按 Stage 或 Job 延迟加载节点。
- 避免一次性渲染所有历史 Run 的节点。

前端可以选择 AntV G6，或在 React 项目中使用 React Flow 配合 ELK.js。技术选择不能影响后端 DAG 契约。

## 进度计算

进度由后端统一计算，页面不自行推断：

```text
completed = succeeded + failed + skipped + aborted
percent = completed / total * 100
```

返回示例：

```json
{
  "total": 511,
  "pending": 123,
  "running": 1,
  "succeeded": 280,
  "failed": 2,
  "skipped": 100,
  "aborted": 5,
  "percent": 75.93
}
```

第一阶段使用任务数量进度，不根据历史耗时做权重估算。

## Redis 持久化与保留策略

### 持久化

网页需要在 Redis 重启后继续访问历史任务，因此推荐：

```conf
appendonly yes
appendfsync everysec
```

该配置通常最多损失约一秒事件，同时保持主要访问路径在内存中。

### 历史快照

以下数据保留用于历史查询：

- Run meta 和最终 summary。
- ExecutionPlan/DAG。
- 每个 Skill 的最终状态和错误摘要。

### Event Stream

活动 Run 使用近似长度裁剪，例如：

```text
MAXLEN ~ 10000
```

Run 结束后可以进一步裁剪事件，只保留排障所需的最近事件。最终状态查询不依赖完整事件重放。

### 日志

Redis 不保存完整 stdout/stderr。可保存：

- `last_message`。
- `error_summary`。
- 有限长度的 log tail。
- 外部日志路径或日志系统引用。

### 历史清理

提供独立清理策略：

- 保留最近 N 个 Run；或
- 保留最近 N 天；或
- 仅清理 event stream，长期保留最终快照。

清理操作必须同时维护 Runs Sorted Set，不能留下无法访问的孤立索引。

## 异常恢复

### Reporter 暂时失联

- Analyzer 继续执行并输出 warning。
- Reporter 标记本地状态需要 full resync。
- 重连后发送 Run 和全部非终态/已变更节点的最新快照。
- Redis 根据 revision 幂等应用。

### Analyzer 崩溃

- Heartbeat 到期。
- API 将 Run 展示为 `stale`。
- Scheduler 检查子进程是否存活。
- 确认死亡后把当前和未完成任务协调为 `aborted`。
- queue entry 根据策略 ACK、重试或移入失败队列。

### Scheduler 重启

- 使用 Redis Stream Consumer Group pending entries 恢复未 ACK 请求。
- 检查已有 Run heartbeat 和进程信息。
- 不得在旧 Analyzer 仍存活时重复启动同一 Run。

### Redis 重启

- 使用 AOF 恢复队列、历史索引、快照和事件。
- Scheduler 启动时执行一次运行中任务协调。
- 已失去 heartbeat 的 `running` Run 标记为 stale，并进入人工或自动恢复流程。

## 安全与隐私

- 不在 Redis 中保存 LLM API key、完整环境变量、认证 token 或 secret。
- CLI 参数写入 meta 前必须经过 allowlist 和脱敏。
- FastAPI 不直接暴露内部 Redis key。
- API 对外部署时需要认证、CORS allowlist 和访问日志。
- Scheduler 不能直接执行来自 Redis payload 的任意 shell 字符串；请求必须解析为受控参数数组。
- Redis 不应直接暴露到公网。

## 文件边界

计划新增：

```text
process_reporter.py
process_reporter_factory.py
process_reporter_redis.py
process_status_reader_redis.py
process_scheduler_redis.py
```

FastAPI 入口和 schema 可按项目最终目录组织，例如：

```text
process_api.py
process_api_schemas.py
```

计划修改：

```text
ida_analyze_bin.py
agent_runner.py
tests/test_ida_analyze_bin.py
tests/test_agent_runner.py
```

Redis、FastAPI、Uvicorn 等直接依赖需要显式加入项目依赖，不能依赖 `uv.lock` 中的传递依赖。由于这会修改根依赖配置，实施时应作为独立步骤确认和执行。

## 测试设计

### Graph 单元测试

1. `build_skill_graph()` 的 `order` 与当前 `topological_sort_skills()` 一致。
2. 多父依赖保留全部 edges。
3. platform-specific input/output 正确推导。
4. `prerequisite` 正确保留。
5. 相同 module 名的不同 stage 生成不同 ID。
6. cross-stage artifact edge 使用解析后的完整路径推导。
7. 循环依赖记录 warning 和 fallback order。

### Reporter 单元测试

使用 `FakeProcessReporter` 或 recording reporter：

1. Run 初始化事件完整。
2. Skill 状态和 phase 顺序正确。
3. existing output 映射为 skipped。
4. missing input 映射为 failed。
5. 未执行的剩余节点映射为 aborted，而不是实际 failed。
6. 顶层异常仍调用 finalize、flush 和 close。
7. Null Reporter 不改变现有行为。

### Agent callback 测试

1. 每次 Agent attempt 开始时触发 callback。
2. retry 传出正确 attempt/max attempts。
3. timeout 和失败原因能够上报。
4. callback 缺省时现有 Agent 行为不变。
5. callback 异常按 Reporter 失败策略处理，不改变 Agent 结果。

### Redis 单元/集成测试

1. Run 初始化写入 meta、graph、skill hashes 和历史索引。
2. Lua transition 原子更新快照、summary 和 event stream。
3. 重复 revision 幂等忽略。
4. 非法终态回退被拒绝。
5. Heartbeat TTL 正常刷新和过期。
6. Stream trimming 不影响最终状态查询。
7. AOF/Redis 重启后的恢复通过环境允许时的集成测试验证。

Lua、Streams、Consumer Group 等关键行为不能只依赖与真实 Redis 行为可能不同的 mock。单元测试可 mock 客户端，关键契约应在可用的真实 Redis 测试环境执行。

已在.env配置测试用的redis: CS2VIBE_REDIS_URL=redis://localhost:6379

### Scheduler 测试

1. Run 按提交顺序执行。
2. 任一时刻最多启动一个 Analyzer。
3. 子进程正常退出后 ACK 并启动下一项。
4. 子进程失败时 Run 正确终结。
5. Scheduler 重启后能够处理 pending entry。
6. 已存在有效 heartbeat 时不会重复启动同一 Run。

### API/SSE 测试

1. 历史 Run 按时间倒序分页。
2. 页面晚加入时可以取得完整 graph 和 Skill 快照。
3. SSE 从指定 Stream ID 继续读取。
4. 重复事件通过 revision 幂等处理。
5. stale Run 正确展示。
6. 不返回敏感配置。

## 实施阶段

### Phase 1：Graph 和领域模型

- 提取 `build_skill_graph()`。
- 定义 ExecutionPlan、ID 和状态模型。
- 保持现有拓扑排序测试兼容。

### Phase 2：Reporter 抽象接入

- 新增 `process_reporter.py`。
- 新增 `NullProcessReporter` 和 factory。
- 为 `ida_analyze_bin.py` 接入 Run/Job/Skill 生命周期事件。
- 为 `agent_runner.py` 增加通用 callback。
- 使用 Fake Reporter 完成定向测试。

### Phase 3：Redis 写模型

- 实现 Key Builder、RedisProcessReporter 和 Lua transition。
- 实现 heartbeat、revision、reconnect 和 resync。
- 增加 Redis 集成测试。

### Phase 4：Scheduler

- 实现 Redis Stream Run Queue。
- 实现单并发 Scheduler 和 pending recovery。
- 保留手工 CLI 运行方式。

### Phase 5：FastAPI 读模型和 SSE

- 实现 `process_status_reader_redis.py`。
- 实现历史查询、快照、graph、Skill 详情和 SSE。
- 增加 API 集成测试。

### Phase 6：Web 可视化

- 默认提供可折叠思维导图。
- 提供真实 DAG 和列表视图。
- 接入 SSE 实时节点状态更新。
- 增加搜索、过滤、自动展开和节点详情。

### Phase 7：恢复、保留与运行验证

- 配置 AOF `everysec`。
- 验证 Redis/Scheduler/Analyzer 重启恢复。
- 实现历史清理和 Stream trimming。
- 完成端到端 smoke test。

## 验证计划

实施完成后至少执行：

```powershell
uv run ruff format <modified-python-files> <modified-test-files>
uv run ruff check <modified-python-files> <modified-test-files>
uv run python -m unittest tests.test_ida_analyze_bin tests.test_agent_runner -v
```

新增模块的测试应加入对应 unittest 命令。Redis 可用时执行真实 Redis 集成测试，并进行一次端到端 smoke：

1. 提交两个 Run。
2. 确认 Scheduler 严格顺序启动。
3. 第一个 Run 执行途中打开页面。
4. 页面取得完整历史快照和当前 Skill。
5. SSE 持续收到状态变化。
6. 第一个 Run 完成后第二个 Run 才开始。
7. 重启 API 后仍可从 Redis 读取完整状态。
8. 重启 Redis 后通过 AOF 恢复历史 Run。

## 验收标准

- `ida_analyze_bin.py` 和 `agent_runner.py` 中不存在直接 Redis 操作。
- 未配置 Reporter 时，现有 CLI 行为和测试保持兼容。
- 每个 Run 在实际执行前拥有完整 ExecutionPlan 和 DAG。
- 重复 module 名通过 `stage_index` 正确区分。
- 页面在任务执行途中上线时能先取得完整快照，再接收实时事件。
- 页面可查询已完成的历史 Run 和每个 Skill 的最终状态。
- 多父依赖在 DAG 中完整保留，思维导图仅作为展示投影。
- 多个 Run 由 Scheduler 严格按 FIFO、单并发执行。
- Skill 的 failed、skipped 和 aborted 状态语义清晰且可追溯。
- Redis 状态更新、汇总计数和 Stream 事件保持原子一致。
- Analyzer 异常退出可以通过 heartbeat 被识别和协调。
- Redis 重启后可通过 AOF 恢复历史任务。
- Redis 中不包含 API key、secret 或未脱敏环境信息。
- 定向格式化、lint、单元测试、Redis 集成测试和端到端 smoke 验证通过。
