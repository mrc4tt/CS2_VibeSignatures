"""One module's tasks over several IDA instances (ida_shards, CS2VIBE_SHARDS).

Pinned here: the plan respects the dependency graph and spreads a wide DAG, a
shard waits only for producers in other shards and stops waiting when that shard
has exited, every own task is marked done however the loop ends, and the run
leaves the paid work (hunter, agent, deferral) to the sweep.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import ida_shards  # noqa: E402
import ida_analyze_bin  # noqa: E402


class Planning(unittest.TestCase):
    def test_independent_tasks_spread_evenly(self):
        order = [f"t{i}" for i in range(8)]
        owner = ida_shards.plan_shards(order, {}, 4)
        self.assertEqual(sorted(list(owner.values()).count(k) for k in range(4)), [2, 2, 2, 2])
        self.assertAlmostEqual(ida_shards.simulated_speedup(order, {}, owner), 4.0)

    def test_a_chain_stays_serial_and_gains_nothing(self):
        order = ["a", "b", "c"]
        deps = {"b": {"a"}, "c": {"b"}}
        owner = ida_shards.plan_shards(order, deps, 4)
        self.assertAlmostEqual(ida_shards.simulated_speedup(order, deps, owner), 1.0)

    def test_finished_producers_are_ignored(self):
        # "done" is not pending (its outputs exist), so nothing waits for it
        owner = ida_shards.plan_shards(["x", "y"], {"x": {"done"}, "y": {"done"}}, 2)
        self.assertEqual(sorted(owner.values()), [0, 1])

    def test_env_knobs(self):
        self.assertEqual(ida_shards.configured_shard_count({}), ida_shards.DEFAULT_SHARDS)
        self.assertEqual(ida_shards.configured_shard_count({"CS2VIBE_SHARDS": "0"}), 1)
        self.assertEqual(ida_shards.configured_shard_count({"CS2VIBE_SHARDS": "junk"}), 1)
        self.assertEqual(ida_shards.configured_min_tasks({"CS2VIBE_SHARD_MIN_TASKS": "5"}), 5)


class ChildSide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.order = ["a", "b", "c"]
        self.deps = {"c": {"a", "b"}}
        self.owner = {"a": 0, "b": 1, "c": 0}

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, shard):
        path = self.state / f"plan-{shard}.json"
        ida_shards.write_plan(path, shard=shard, order=self.order, dependencies=self.deps,
                              owner=self.owner, state_dir=self.state, stage=3)
        with mock.patch.dict(os.environ, {ida_shards.SHARD_PLAN_ENV: os.fspath(path)}):
            plan = ida_shards.ShardPlan.from_env()
        plan.parent_pid = os.getppid()  # the test process stands in for the shard's parent
        return plan

    def test_plan_round_trip(self):
        plan = self.plan(0)
        self.assertEqual(plan.order, ["a", "c"])
        self.assertEqual(plan.stage, 3)
        self.assertEqual(plan.deps["c"], ["a", "b"])
        self.assertIsNone(ida_shards.ShardPlan.from_env({}))

    def test_waits_for_the_other_shard_only(self):
        plan = self.plan(0)
        sleeps = []

        def sleep(_seconds):
            sleeps.append(1)
            (self.state / "done" / "b").touch()

        plan.wait_for("c", sleep=sleep)
        self.assertEqual(len(sleeps), 1, "waited for b (shard 1), not for its own a")

    def test_a_dead_parent_releases_its_waiters(self):
        plan = self.plan(0)
        plan.parent_pid = -1
        plan.wait_for("c", sleep=lambda _s: self.fail("must not wait"))

    def test_an_exited_shard_releases_its_waiters(self):
        plan = self.plan(0)
        ida_shards.exit_marker(self.state, 1).touch()
        plan.wait_for("c", sleep=lambda _s: self.fail("must not wait"))

    def test_iterate_marks_done_also_on_break(self):
        plan = self.plan(1)
        for _item in plan.iterate([(0, ("b",))], lambda item: item[1][0]):
            break
        self.assertTrue((self.state / "done" / "b").exists())

    def test_iterate_marks_tasks_that_never_reach_the_loop(self):
        plan = self.plan(0)
        with mock.patch.object(plan, "wait_for"):
            items = plan.iterate([(0, ("c",))], lambda item: item[1][0])
            next(items)
            self.assertTrue((self.state / "done" / "a").exists(), "a had its outputs already")
            self.assertFalse((self.state / "done" / "c").exists(), "c is still running")
            list(items)
        self.assertTrue((self.state / "done" / "c").exists())


class ParentSide(unittest.TestCase):
    def test_sharding_stays_off_where_it_cannot_work(self):
        args = mock.Mock(selected_node_ids=None, force_all=False, skip_pp=False,
                         vcall_finder_filter=None, process_reporter="none")
        self.assertIsNone(ida_analyze_bin._shard_unsupported_reason(args))
        args.skip_pp = True
        self.assertEqual(ida_analyze_bin._shard_unsupported_reason(args), "-skip_pp")
        args.skip_pp = False
        with mock.patch.dict(os.environ, {ida_shards.SHARD_PLAN_ENV: "x"}):
            self.assertEqual(ida_analyze_bin._shard_unsupported_reason(args), "already a shard")

    def test_paid_work_is_left_for_the_sweep(self):
        source = Path(REPO, "ida_analyze_bin.py").read_text(encoding="utf-8")
        body = source[source.index("def _process_binary("):source.index("def _invoke_process_binary(")]
        sweep = body.index('"left for the sweep", "preprocess did not produce every output"')
        self.assertLess(sweep, body.index("run_pipeline_hunt("), "before the hunter")
        missing = body.index('"left for the sweep", f"missing input')
        self.assertLess(missing, body.index("_DEFERRED_INPUT_SKILLS.append"), "before deferral")

    def test_pending_counts_only_tasks_without_outputs(self):
        with tempfile.TemporaryDirectory() as art:
            Path(art, "Done.linux.yaml").write_text("x")
            skills = [
                {"name": "done", "expected_output": ["Done.{platform}.yaml"]},
                {"name": "todo", "expected_output": ["Todo.{platform}.yaml"]},
                {"name": "win", "platform": "windows", "expected_output": ["Win.{platform}.yaml"]},
            ]
            pending = ida_analyze_bin._pending_shard_tasks(skills, "linux", art)
        self.assertEqual([skill["name"] for skill in pending], ["todo"])


if __name__ == "__main__":
    unittest.main()
