import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv
from redis import Redis
from redis.exceptions import RedisError

from process_reporter import RunStatus
from process_reporter_redis import RedisProcessReporter
from process_scheduler_redis import RedisProcessScheduler, RedisRunQueue, RunRequest


class FakePopenFactory:
    def __init__(self, exit_codes=None):
        self.exit_codes = exit_codes or {}
        self.calls = []
        self.active = 0
        self.max_active = 0

    def __call__(self, command, *, cwd, env):
        run_id = env["CS2VIBE_RUN_ID"]
        self.calls.append({"run_id": run_id, "command": command, "cwd": cwd, "env": env})
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        return FakeProcess(self, self.exit_codes.get(run_id, 0), len(self.calls) + 1000)


class FakeProcess:
    def __init__(self, factory, exit_code, pid):
        self.factory = factory
        self.exit_code = exit_code
        self.pid = pid

    def wait(self):
        self.factory.active -= 1
        return self.exit_code


class TestRunRequest(unittest.TestCase):
    def test_validates_queue_fields(self) -> None:
        request = RunRequest.create("14141", platforms="windows", modules="engine,server", agent="codex")

        self.assertEqual("windows", request.platforms)
        self.assertEqual("engine,server", request.modules)
        with self.assertRaisesRegex(ValueError, "platforms"):
            RunRequest.create("14141", platforms="macos")
        with self.assertRaisesRegex(ValueError, "agent"):
            RunRequest.create("14141", agent="powershell.exe")


class TestSchedulerConfigResolution(unittest.TestCase):
    def test_default_config_is_resolved_per_request_and_override_is_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            configs = root / "configs"
            configs.mkdir()
            first = configs / "14168.yaml"
            second = configs / "14169.yaml"
            first.write_bytes(b"modules: []\n")
            second.write_bytes(b"modules: []\n")
            with patch("analysis_config.REPO_ROOT", root):
                scheduler = RedisProcessScheduler(object(), analyzer_script=root / "analyzer.py")
                first_command = scheduler.build_command(RunRequest.create("14168"))
                second_command = scheduler.build_command(RunRequest.create("14169"))
            self.assertIn(f"-configyaml={first.resolve()}", first_command)
            self.assertIn(f"-configyaml={second.resolve()}", second_command)

            override = root / "scratch.yaml"
            override.write_bytes(b"modules: []\n")
            scheduler = RedisProcessScheduler(object(), analyzer_script=root / "analyzer.py", config_path=str(override))
            command = scheduler.build_command(RunRequest.create("14168"))
            self.assertIn(f"-configyaml={override.resolve()}", command)


class TestRedisProcessSchedulerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_dotenv()
        cls.redis_url = os.environ.get("CS2VIBE_REDIS_URL", "redis://127.0.0.1:6379/0")
        cls.redis = Redis.from_url(cls.redis_url, decode_responses=True)
        try:
            cls.redis.ping()
        except RedisError as exc:
            raise unittest.SkipTest(f"Redis integration server is unavailable: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        cls.redis.close()

    def setUp(self) -> None:
        self.prefix = f"cs2vibe:scheduler-test:{uuid.uuid4().hex}"

    def tearDown(self) -> None:
        keys = list(self.redis.scan_iter(f"{self.prefix}:*"))
        if keys:
            self.redis.delete(*keys)

    def _queue(self, **overrides) -> RedisRunQueue:
        settings = {
            "redis_url": self.redis_url,
            "prefix": self.prefix,
            "consumer": f"consumer-{uuid.uuid4().hex}",
            "recovery_idle_ms": 0,
        }
        settings.update(overrides)
        queue = RedisRunQueue(**settings)
        self.addCleanup(queue.close)
        return queue

    def _scheduler(self, queue, popen_factory) -> RedisProcessScheduler:
        return RedisProcessScheduler(
            queue,
            analyzer_script="ida_analyze_bin.py",
            python_executable="python",
            popen_factory=popen_factory,
        )

    def test_submit_creates_fifo_stream_and_safe_queued_metadata(self) -> None:
        queue = self._queue()
        first = RunRequest.create("100", run_id="run-first", agent="codex")
        second = RunRequest.create("101", run_id="run-second", agent="claude")

        first_id = queue.submit(first)
        second_id = queue.submit(second)

        self.assertLess(tuple(map(int, first_id.split("-"))), tuple(map(int, second_id.split("-"))))
        meta = self.redis.hgetall(queue.keys.run_meta(first.run_id))
        self.assertEqual("queued", meta["status"])
        self.assertEqual("100", meta["gamever"])
        self.assertNotIn("redis_url", meta)
        self.assertEqual(
            [first.run_id, second.run_id], [fields["run_id"] for _, fields in self.redis.xrange(queue.keys.run_queue)]
        )

    def test_runs_in_fifo_order_with_single_active_process_and_acks(self) -> None:
        queue = self._queue()
        requests = [RunRequest.create(str(gamever), run_id=f"run-{gamever}") for gamever in (100, 101)]
        for request in requests:
            queue.submit(request)
        popen = FakePopenFactory()
        scheduler = self._scheduler(queue, popen)

        self.assertTrue(scheduler.run_once(block_ms=1))
        self.assertTrue(scheduler.run_once(block_ms=1))

        self.assertEqual([request.run_id for request in requests], [call["run_id"] for call in popen.calls])
        self.assertEqual(1, popen.max_active)
        self.assertEqual(0, queue.client.xpending(queue.keys.run_queue, queue.group)["pending"])
        for request in requests:
            self.assertEqual("succeeded", queue.status(request.run_id))

    def test_failed_process_finalizes_run_and_acks(self) -> None:
        queue = self._queue()
        request = RunRequest.create("100", run_id="run-failed")
        queue.submit(request)
        scheduler = self._scheduler(queue, FakePopenFactory({request.run_id: 7}))

        scheduler.run_once(block_ms=1)

        meta = self.redis.hgetall(queue.keys.run_meta(request.run_id))
        self.assertEqual("failed", meta["status"])
        self.assertEqual("7", meta["scheduler_exit_code"])
        self.assertEqual(0, queue.client.xpending(queue.keys.run_queue, queue.group)["pending"])

    def test_pending_entry_is_claimed_and_executed_after_restart(self) -> None:
        original = self._queue(consumer="old-consumer")
        request = RunRequest.create("100", run_id="run-recovered-queued")
        original.submit(request)
        original.ensure_group()
        original.client.xreadgroup(original.group, original.consumer, {original.keys.run_queue: ">"}, count=1)
        recovered = self._queue(consumer="new-consumer")
        popen = FakePopenFactory()

        self._scheduler(recovered, popen).run_once(block_ms=1)

        self.assertEqual([request.run_id], [call["run_id"] for call in popen.calls])
        self.assertEqual("succeeded", recovered.status(request.run_id))
        self.assertEqual(0, recovered.client.xpending(recovered.keys.run_queue, recovered.group)["pending"])

    def test_reporter_attaches_to_scheduler_created_run(self) -> None:
        queue = self._queue()
        request = RunRequest.create("100", run_id="run-attach")
        queue.submit(request)
        entry = queue.next_entry(block_ms=1)
        queue.transition(entry, RunStatus.STARTING)
        reporter = RedisProcessReporter(
            self.redis_url,
            self.prefix,
            heartbeat_interval=60,
            worker_id="attached-analyzer",
        )
        self.addCleanup(reporter.close)
        plan = {"schema_version": 1, "stages": [], "jobs": [], "nodes": [], "edges": [], "warnings": []}

        run_id = reporter.initialize_run(plan, run_id=request.run_id)

        meta = self.redis.hgetall(queue.keys.run_meta(request.run_id))
        self.assertEqual(request.run_id, run_id)
        self.assertEqual("starting", meta["status"])
        self.assertIn("initialized_at", meta)
        self.assertEqual(plan, json.loads(self.redis.get(queue.keys.graph(request.run_id))))

    def test_live_heartbeat_prevents_duplicate_then_expiry_aborts(self) -> None:
        original = self._queue(consumer="old-consumer")
        request = RunRequest.create("100", run_id="run-live")
        original.submit(request)
        original.ensure_group()
        response = original.client.xreadgroup(
            original.group,
            original.consumer,
            {original.keys.run_queue: ">"},
            count=1,
        )
        entry_id = response[0][1][0][0]
        original.client.hset(original.keys.run_meta(request.run_id), "status", RunStatus.STARTING.value)
        original.client.set(original.keys.heartbeat(request.run_id), "old-worker", ex=10)
        recovered = self._queue(consumer="new-consumer")
        popen = FakePopenFactory()
        scheduler = self._scheduler(recovered, popen)

        scheduler.run_once(block_ms=1)

        self.assertEqual([], popen.calls)
        self.assertEqual("starting", recovered.status(request.run_id))
        self.assertEqual(1, recovered.client.xpending(recovered.keys.run_queue, recovered.group)["pending"])
        recovered.client.delete(recovered.keys.heartbeat(request.run_id))
        scheduler.run_once(block_ms=1)
        self.assertEqual("aborted", recovered.status(request.run_id))
        self.assertEqual(0, recovered.client.xpending(recovered.keys.run_queue, recovered.group)["pending"])
        self.assertEqual(entry_id, self.redis.hget(recovered.keys.run_meta(request.run_id), "queue_entry_id"))

    def test_redis_connection_details_are_only_passed_via_environment(self) -> None:
        queue = self._queue()
        request = RunRequest.create("100", run_id="run-command", skill_filter="find-A", agent="codex")
        scheduler = self._scheduler(queue, FakePopenFactory())

        command = scheduler.build_command(request)
        environment = scheduler.build_environment(request)

        self.assertFalse(any(self.redis_url in argument for argument in command))
        self.assertIn("-skill=find-A", command)
        self.assertEqual(self.redis_url, environment["CS2VIBE_REDIS_URL"])
        self.assertEqual(request.run_id, environment["CS2VIBE_RUN_ID"])

    def test_real_subprocess_smoke_runs_two_requests_strictly_in_sequence(self) -> None:
        queue = self._queue()
        requests = [RunRequest.create(str(gamever), run_id=f"run-smoke-{gamever}") for gamever in (100, 101)]
        for request in requests:
            queue.submit(request)
        analyzer = Path(__file__).parent / "fixtures" / "process_scheduler_smoke_analyzer.py"
        scheduler = RedisProcessScheduler(queue, analyzer_script=analyzer, python_executable=sys.executable)

        scheduler.run_once(block_ms=1)
        scheduler.run_once(block_ms=1)

        first_meta = self.redis.hgetall(queue.keys.run_meta(requests[0].run_id))
        second_meta = self.redis.hgetall(queue.keys.run_meta(requests[1].run_id))
        self.assertEqual("succeeded", first_meta["status"])
        self.assertEqual("succeeded", second_meta["status"])
        self.assertLessEqual(first_meta["finished_at"], second_meta["started_at"])
        self.assertEqual(0, queue.client.xpending(queue.keys.run_queue, queue.group)["pending"])


if __name__ == "__main__":
    unittest.main()
