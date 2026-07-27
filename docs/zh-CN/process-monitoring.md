[返回中文 README](../../README_CN.md) | [English](../en/process-monitoring.md)

# 进度上报、调度与看板

## Redis 进度上报

Redis 进度上报是可选功能。设置：

```text
CS2VIBE_PROCESS_REPORTER=redis
CS2VIBE_REDIS_URL=redis://127.0.0.1:6379/0
```

也可以向 Analyzer 传入 `-process_reporter=redis`、`-redis_url=...` 和可选的 `-redis_prefix=...` 参数。

Reporter 会发布不可变 execution graph、Run/Job/Skill 最新快照、事件 Stream、原子汇总计数和带 TTL 的 heartbeat。Redis 暂时不可用不会改变 Analyzer 结果，恢复连接后会重放最新本地快照。

## Scheduler

先提交 Analyzer 任务，再启动单并发 worker：

```bash
uv run python process_scheduler_cli.py submit --gamever 14141 --agent codex
uv run python process_scheduler_cli.py run
```

Redis Stream Consumer Group 会保持 FIFO 顺序，在 Scheduler 重启后恢复 pending entry，并在 Analyzer heartbeat 仍有效时避免重复启动。队列 payload 是经过校验的结构化字段，不是可执行的 shell 命令。

## 只读进度 API

在本地启动 API：

```bash
uv run uvicorn process_api:app --host 127.0.0.1 --port 8000
```

主要接口包括 `/api/v1/runs`、`/api/v1/runs/{run_id}/snapshot`、`/tasks`、`/events` 和 `/stream`。客户端应先读取 snapshot，再以 `snapshot_event_id` 作为 `after` 建立 SSE；断线后可通过 `Last-Event-ID` 恢复。

服务默认只监听本机且不内置认证。对外部署时应置于带认证的反向代理之后。使用 `CS2VIBE_API_CORS_ORIGINS` 配置浏览器来源，通过 `CS2VIBE_SSE_BLOCK_MS` 和 `CS2VIBE_SSE_BATCH_SIZE` 调整 SSE，并使用 `/healthz` 与 `/readyz` 检查存活状态和 Redis 就绪状态。

构建 `pages/` 中的 React 看板：

```bash
npm ci
npm run build
```

若公网 Pages 页面需要连接浏览器同机的 FastAPI，应将准确 Origin 添加到 `CS2VIBE_API_CORS_ORIGINS`，并设置 `CS2VIBE_API_ALLOW_PRIVATE_NETWORK=true`。Pages CDN 无法访问另一台机器的 localhost；启用私有网络访问时也禁止使用通配 Origin。
