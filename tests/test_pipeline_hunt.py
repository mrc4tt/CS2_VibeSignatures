"""The pipeline's own hunter pass and the manual list it leaves (ida_analyze_bin).

The hunt itself runs inside IDA; these tests cover the host side: when it runs, how an
unavailable hunter is remembered, and how the manual list merges and cleans itself.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ida_analyze_bin as I


class AgentDisabledTests(unittest.TestCase):
    def test_none_and_aliases(self):
        for name in ("none", "NONE", " manual ", "off"):
            self.assertTrue(I.agent_disabled(name), name)

    def test_real_agents_and_chains(self):
        for name in ("claude", "opencode,claude", "", None):
            self.assertFalse(I.agent_disabled(name), name)


class DescribeUnresolvedTests(unittest.TestCase):
    def test_best_candidate_first(self):
        row = {"category": "func", "why": "weak evidence only via neighbour score 0.58",
               "candidates": [{"va": "0x1808d1cf0", "score": 0.58}, {"va": "0x1", "score": 0.1}]}
        self.assertEqual(I.describe_unresolved(row),
                         "func | best 0x1808d1cf0 (0.58) | weak evidence only via neighbour score 0.58")

    def test_no_candidate(self):
        self.assertEqual(I.describe_unresolved({"category": "gv", "why": "owner not found"}),
                         "gv | owner not found")


class ManualTodoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = os.path.join(self.tmp.name, "bin_artifacts", "14182", "server")
        os.makedirs(self.artifacts)
        self.path = I.manual_todo_path("14182", "server", "windows", repo_root=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self):
        with open(self.path, encoding="utf-8") as handle:
            return {line.split()[0]: line for line in handle if line.strip() and not line.startswith("#")}

    def test_merge_keeps_earlier_entries_and_replaces_same_symbol(self):
        I.update_manual_todo(self.path, self.artifacts, "windows", {"A_x": ("find-A", "func | first")})
        left = I.update_manual_todo(self.path, self.artifacts, "windows",
                                    {"B_y": ("find-B", "func | b"), "A_x": ("find-A", "agent failed | func | first")})
        rows = self._rows()
        self.assertEqual(left, 2)
        self.assertIn("agent failed", rows["A_x"])
        self.assertIn("find-B", rows["B_y"])

    def test_entry_drops_out_once_its_artifact_exists(self):
        I.update_manual_todo(self.path, self.artifacts, "windows", {"A_x": ("find-A", "d"), "B_y": ("find-B", "d")})
        open(os.path.join(self.artifacts, "A_x.windows.yaml"), "w").close()
        self.assertEqual(I.update_manual_todo(self.path, self.artifacts, "windows", {}), 1)
        self.assertEqual(set(self._rows()), {"B_y"})


class RunPipelineHuntTests(unittest.TestCase):
    KW = dict(host="127.0.0.1", port=1, symbols=["A_x"], artifact_dir="/nonexistent",
              old_artifact_dir="bin_artifacts/14181/server", module_name="server", platform="windows")

    def setUp(self):
        I._pipeline_hunt_unavailable.clear()

    def test_env_switch_turns_it_off(self):
        with mock.patch.dict(os.environ, {I.PIPELINE_HUNT_ENV: "0"}), \
                mock.patch.object(I, "_pipeline_hunt_via_mcp") as call:
            self.assertIsNone(I.run_pipeline_hunt(binary_path="b1", **self.KW))
            call.assert_not_called()

    def test_result_is_returned(self):
        result = {"solved": [{"symbol": "A_x"}], "unresolved": [], "log": ["  OK   func A_x"]}

        async def fake(*_args):
            return result

        with mock.patch.object(I, "_pipeline_hunt_via_mcp", side_effect=fake):
            self.assertEqual(I.run_pipeline_hunt(binary_path="b2", **self.KW), result)

    def test_unavailable_hunter_is_asked_once_per_binary(self):
        calls = []

        async def fake(*_args):
            calls.append(1)
            return {"error": "the open binary is not under bin/<gamever>/<module>/"}

        with mock.patch.object(I, "_pipeline_hunt_via_mcp", side_effect=fake):
            self.assertIsNone(I.run_pipeline_hunt(binary_path="b3", **self.KW))
            self.assertIsNone(I.run_pipeline_hunt(binary_path="b3", **self.KW))
        self.assertEqual(len(calls), 1)

    def test_missing_facts_are_built_then_asked_again(self):
        answers = [{"error": "no baseline facts for server.windows before 14182"},
                   {"solved": [], "unresolved": [], "log": []}]

        async def fake(*_args):
            return answers.pop(0)

        with mock.patch.object(I, "_pipeline_hunt_via_mcp", side_effect=fake), \
                mock.patch.object(I, "_generate_baseline_facts", return_value=True) as build:
            self.assertEqual(I.run_pipeline_hunt(binary_path="b4", **self.KW)["solved"], [])
        build.assert_called_once_with("bin_artifacts/14181/server", "server", "windows")


if __name__ == "__main__":
    unittest.main()


class DeferredInputRetryTests(unittest.TestCase):
    """A task whose input another module produces is retried once every module ran."""

    def setUp(self):
        I._DEFERRED_INPUT_SKILLS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.ready = os.path.join(self.tmp.name, "server", "IVEngineServer2_ServerCommand.windows.yaml")
        os.makedirs(os.path.dirname(self.ready))
        open(self.ready, "w").close()
        self.missing = os.path.join(self.tmp.name, "server", "IVEngineServer2_Nope.windows.yaml")
        self.modules = [{"name": "engine", "skills": [{"name": "find-A"}, {"name": "find-B"}, {"name": "find-C"}]}]

    def tearDown(self):
        self.tmp.cleanup()
        I._DEFERRED_INPUT_SKILLS.clear()

    def test_ready_tasks_rerun_and_missing_ones_fail(self):
        I._DEFERRED_INPUT_SKILLS.extend([
            ("engine", "windows", "find-A", (self.ready,)),
            ("engine", "windows", "find-B", (self.missing,)),
        ])
        seen = {}

        def fake(args, module, platform, vcall_targets, reporting, found):
            seen["skills"] = [s["name"] for s in module["skills"]]
            seen["platform"] = platform
            return 1, 0, 0

        args = mock.Mock(vcall_finder_filter=None)
        with mock.patch.object(I, "_process_platform", side_effect=fake):
            counts = I._retry_deferred_skills(args, self.modules, None, set())
        self.assertEqual(seen, {"skills": ["find-A"], "platform": "windows"})
        # A: success (its first-pass skip taken back); B: a real failure now
        self.assertEqual(counts, [1, 1, -1])
        self.assertEqual(I._DEFERRED_INPUT_SKILLS, [])


class PackPlatformTests(unittest.TestCase):
    """pack -platform: each platform's run packs without waiting for the other."""

    def test_other_platform_missing_is_tolerated_own_is_not(self):
        from gamesymbol_snapshot_lib import operations as O

        contract = mock.Mock(required_paths={"server/A.linux.yaml", "server/B.windows.yaml"})
        with mock.patch.object(O, "_waived", return_value=False):
            self.assertEqual(O._missing_required(contract, lambda p: False),
                             ["server/A.linux.yaml", "server/B.windows.yaml"])
            O._TOLERATED_PLATFORMS.add("windows")
            try:
                self.assertEqual(O._missing_required(contract, lambda p: False), ["server/A.linux.yaml"])
            finally:
                O._TOLERATED_PLATFORMS.clear()

    def test_pack_platform_restores_the_full_requirement_afterwards(self):
        from gamesymbol_snapshot_lib import operations as O

        seen = []

        def fake_load_contract(*_args, **_kwargs):
            seen.append(set(O._TOLERATED_PLATFORMS))
            raise RuntimeError("stop")

        with mock.patch.object(O, "resolve_analysis_config", return_value="c.yaml"), \
                mock.patch.object(O, "load_contract", side_effect=fake_load_contract), \
                mock.patch.object(O, "_explicit_snapshot_path", side_effect=lambda p: p):
            with self.assertRaises(RuntimeError):
                O.pack_snapshot("14182", snapshot_path="x.yaml", platform="linux")
        self.assertEqual(seen, [{"windows"}])
        self.assertEqual(O._TOLERATED_PLATFORMS, set())


class SinglePlatformGenerationTests(unittest.TestCase):
    """update_gamedata -platform linux keeps the windows values already in the output."""

    def test_existing_output_is_kept_only_for_single_platform_runs(self):
        import update_gamedata as U

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "template.json"), "w") as handle:
                handle.write("template")
            contract = mock.Mock(static_sources=[("template.json", "gamedata/p.json")], directory="p", source_dir=Path(src))
            out = os.path.join(tmp, "out")
            target = os.path.join(out, "p", "gamedata", "p.json")
            os.makedirs(os.path.dirname(target))
            with open(target, "w") as handle:
                handle.write("generated earlier")
            U._seed_output_root([contract], out, keep_existing=True)
            self.assertEqual(open(target).read(), "generated earlier")
            U._seed_output_root([contract], out, keep_existing=False)
            self.assertEqual(open(target).read(), "template")
