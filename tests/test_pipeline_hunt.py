"""The pipeline's own hunter pass and the manual list it leaves (ida_analyze_bin).

The hunt itself runs inside IDA; these tests cover the host side: when it runs, how an
unavailable hunter is remembered, and how the manual list merges and cleans itself.
"""
import os
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
