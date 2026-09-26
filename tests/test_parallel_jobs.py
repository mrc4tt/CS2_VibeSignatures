import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import agent_runner
import ida_analyze_bin


class TestResolveJobs(unittest.TestCase):
    def test_one_is_the_default_and_numbers_are_capped_by_binaries(self) -> None:
        self.assertEqual(1, ida_analyze_bin._resolve_jobs(None, 9))
        self.assertEqual(1, ida_analyze_bin._resolve_jobs("1", 9))
        self.assertEqual(4, ida_analyze_bin._resolve_jobs("4", 9))
        self.assertEqual(9, ida_analyze_bin._resolve_jobs("32", 9))

    def test_auto_takes_the_smaller_of_cores_and_memory(self) -> None:
        with (
            patch("ida_analyze_bin.os.cpu_count", return_value=32),
            patch.object(ida_analyze_bin, "_memory_bound_jobs", return_value=5),
        ):
            self.assertEqual(5, ida_analyze_bin._resolve_jobs("auto", 9))
        with (
            patch("ida_analyze_bin.os.cpu_count", return_value=2),
            patch.object(ida_analyze_bin, "_memory_bound_jobs", return_value=20),
        ):
            self.assertEqual(2, ida_analyze_bin._resolve_jobs("AUTO", 9))

    def test_garbage_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            ida_analyze_bin._resolve_jobs("many", 9)


class TestParallelGroups(unittest.TestCase):
    def test_stages_of_one_binary_share_a_group_and_the_heaviest_goes_first(self) -> None:
        modules = [
            {"name": "engine", "path_linux": "x", "skills": [1, 2]},
            {"name": "server", "path_linux": "x", "skills": [1, 2, 3]},
            {"name": "client", "path_linux": "x", "skills": [1]},
            {"name": "engine", "path_linux": "x", "skills": [1, 2]},
            {"name": "SDL3", "path_windows": "x", "skills": [1, 2, 3, 4, 5]},
        ]
        self.assertEqual(
            [("engine", "linux"), ("server", "linux"), ("client", "linux")],
            ida_analyze_bin._parallel_groups(modules, ["linux"]),
        )


class TestParallelFallback(unittest.TestCase):
    def test_modes_that_need_one_process_stay_sequential(self) -> None:
        base = {"selected_execution": None, "force_all": False, "vcall_finder_filter": None,
                "process_reporter": "none"}
        self.assertIsNone(ida_analyze_bin._parallel_unsupported_reason(SimpleNamespace(**base)))
        self.assertEqual(
            "-vcall_finder",
            ida_analyze_bin._parallel_unsupported_reason(SimpleNamespace(**{**base, "vcall_finder_filter": {}})),
        )
        self.assertEqual(
            "-process_reporter redis",
            ida_analyze_bin._parallel_unsupported_reason(SimpleNamespace(**{**base, "process_reporter": "redis"})),
        )

    def test_child_overrides_come_last_so_argparse_keeps_them(self) -> None:
        with patch.object(sys, "argv", ["ida_analyze_bin.py", "-gamever", "1", "-modules", "*", "-platform", "linux"]):
            cmd = ida_analyze_bin._child_command(SimpleNamespace(), "server", "linux", "/tmp/r.json")
        self.assertEqual(["-modules", "server", "-platform", "linux", "-jobs", "1", "-deferred_out", "/tmp/r.json"],
                         cmd[-8:])


class TestChildResult(unittest.TestCase):
    def test_child_writes_totals_and_deferred_tasks(self) -> None:
        with TemporaryDirectory() as tmp, patch.object(
            ida_analyze_bin, "_DEFERRED_INPUT_SKILLS", [("engine", "linux", "find-X", ("a.yaml",))]
        ):
            path = os.path.join(tmp, "r.json")
            ida_analyze_bin._write_child_result(path, [3, 0, 1], False, {"obj"})
            payload = json.loads(Path(path).read_text())
        self.assertEqual([3, 0, 1], payload["totals"])
        self.assertEqual([["engine", "linux", "find-X", ["a.yaml"]]], payload["deferred"])
        self.assertEqual(["obj"], payload["found_vcall_objects"])


class TestReadyDeferred(unittest.TestCase):
    def test_a_task_waiting_on_another_deferred_task_runs_after_it(self) -> None:
        with TemporaryDirectory() as tmp:
            first_in = os.path.join(tmp, "server", "A.linux.yaml")
            first_out = os.path.join(tmp, "engine", "B.linux.yaml")
            os.makedirs(os.path.dirname(first_in))
            os.makedirs(os.path.dirname(first_out))
            Path(first_in).write_text("x")
            deferred = [
                ("client", "linux", "find-C", (first_out,)),
                ("engine", "linux", "find-B", (first_in,)),
            ]
            ran = []

            def fake_retry(args, modules, reporting, found):
                batch = list(ida_analyze_bin._DEFERRED_INPUT_SKILLS)
                ida_analyze_bin._DEFERRED_INPUT_SKILLS.clear()
                for entry in batch:
                    ran.append(entry[2])
                    if entry[2] == "find-B":
                        Path(first_out).write_text("x")
                return [len(batch), 0, 0]

            with (
                patch.object(ida_analyze_bin, "_DEFERRED_INPUT_SKILLS", list(deferred)),
                patch.object(ida_analyze_bin, "_retry_deferred_skills", side_effect=fake_retry),
            ):
                counts = ida_analyze_bin._run_ready_deferred(None, [], None, set())
        self.assertEqual(["find-B", "find-C"], ran)
        self.assertEqual([2, 0, 0], counts)


@unittest.skipIf(agent_runner.fcntl is None, "flock only")
class TestAgentSlot(unittest.TestCase):
    def test_no_cap_without_configuration(self) -> None:
        with patch.dict(os.environ, {"CS2VIBE_AGENT_JOBS": "", "CS2VIBE_AGENT_SLOT_DIR": ""}):
            with agent_runner.agent_slot():
                pass

    def test_the_cap_holds_across_processes(self) -> None:
        with TemporaryDirectory() as tmp:
            env = {"CS2VIBE_AGENT_JOBS": "1", "CS2VIBE_AGENT_SLOT_DIR": tmp}
            holder = subprocess.Popen(
                [sys.executable, "-c", "import fcntl,sys,time;h=open(sys.argv[1],'w');"
                 "fcntl.flock(h,fcntl.LOCK_EX);print('held',flush=True);time.sleep(30)",
                 os.path.join(tmp, "slot0.lock")],
                stdout=subprocess.PIPE, text=True,
            )
            try:
                self.assertEqual("held", holder.stdout.readline().strip())
                sleeps = []

                def fake_sleep(seconds):
                    sleeps.append(seconds)
                    holder.kill()
                    holder.wait()

                with (
                    patch.dict(os.environ, env),
                    patch("agent_runner.time.sleep", side_effect=fake_sleep),
                    patch("sys.stdout"),
                ):
                    with agent_runner.agent_slot():
                        pass
                self.assertEqual([agent_runner.AGENT_SLOT_POLL_SECONDS], sleeps)
            finally:
                holder.kill()
                holder.wait()
                holder.stdout.close()


if __name__ == "__main__":
    unittest.main()
