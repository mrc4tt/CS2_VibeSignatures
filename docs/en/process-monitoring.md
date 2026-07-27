[Back to README](../../README.md) | [中文](../zh-CN/process-monitoring.md)

# Process reporting, scheduling, and dashboard

## Redis process reporting

Redis process reporting is optional. Set:

```text
CS2VIBE_PROCESS_REPORTER=redis
CS2VIBE_REDIS_URL=redis://127.0.0.1:6379/0
```

Alternatively, pass `-process_reporter=redis`, `-redis_url=...`, and the optional `-redis_prefix=...` arguments to the Analyzer.

The Reporter publishes the immutable execution graph, current Run/Job/Skill snapshots, an event Stream, atomic summary counters, and a TTL heartbeat. Temporary Redis failures do not change the Analyzer result; the latest local snapshots are replayed after reconnection.

## Scheduler

Queue an Analyzer run, then start the single-concurrency worker:

```bash
uv run python process_scheduler_cli.py submit --gamever 14141 --agent codex
uv run python process_scheduler_cli.py run
```

The Redis Stream consumer group preserves FIFO order, recovers pending entries after Scheduler restarts, and does not relaunch a recovered Run while its Analyzer heartbeat is still alive. Queue payloads are validated fields rather than executable shell commands.

## Read-only progress API

Start the API locally:

```bash
uv run uvicorn process_api:app --host 127.0.0.1 --port 8000
```

The primary routes are `/api/v1/runs`, `/api/v1/runs/{run_id}/snapshot`, `/tasks`, `/events`, and `/stream`. Clients should load a snapshot first, then open SSE with its `snapshot_event_id` as `after`; reconnects can resume through `Last-Event-ID`.

The service binds to localhost by default and has no built-in authentication. Put external deployments behind an authenticated reverse proxy. Configure browser origins with `CS2VIBE_API_CORS_ORIGINS`, tune SSE through `CS2VIBE_SSE_BLOCK_MS` and `CS2VIBE_SSE_BATCH_SIZE`, and use `/healthz` and `/readyz` for liveness and Redis readiness.

The React dashboard in `pages/` is built with:

```bash
npm ci
npm run build
```

For a public Pages origin that connects to FastAPI on the same browser machine, add the exact origin to `CS2VIBE_API_CORS_ORIGINS` and set `CS2VIBE_API_ALLOW_PRIVATE_NETWORK=true`. A Pages CDN cannot reach another machine\'s localhost, and wildcard origins are rejected when private-network access is enabled.
