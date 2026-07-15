import unittest
from pathlib import Path


class TestBuildSelfRunnerWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = Path(".github/workflows/build-on-self-runner.yml").read_text(encoding="utf-8")

    def test_workspace_bin_is_real_and_not_linked_to_persisted_bin(self) -> None:
        self.assertNotIn('mklink /d "%WORKSPACE%\\bin"', self.workflow)
        self.assertIn("Workspace bin must be a real directory", self.workflow)
        self.assertIn("Copied persisted bin/$env:GAMEVER into build workspace", self.workflow)

    def test_major_update_explicitly_disables_old_signature_reuse(self) -> None:
        self.assertIn("$analyzeArgs += @('-oldgamever', 'none')", self.workflow)
        self.assertNotIn("$analyzeArgs += @('-oldgamever', '0')", self.workflow)

    def test_candidate_is_built_before_validation_and_published_before_persist(self) -> None:
        analyze = self.workflow.index("uv run ida_analyze_bin.py")
        candidate = self.workflow.index("gamesymbol_candidate.py build")
        gamedata = self.workflow.index("uv run update_gamedata.py")
        cpp_tests = self.workflow.index("uv run run_cpp_tests.py")
        publish = self.workflow.index("gamesymbol_candidate.py publish")
        persist = self.workflow.index("Persist validated bin cache")

        self.assertLess(analyze, candidate)
        self.assertLess(candidate, gamedata)
        self.assertLess(gamedata, cpp_tests)
        self.assertLess(cpp_tests, publish)
        self.assertLess(publish, persist)
        self.assertNotIn("gamesymbol_snapshot.py pack", self.workflow)

    def test_both_consumers_use_the_same_candidate_without_bindir_fallback(self) -> None:
        self.assertIn('-snapshot "$env:ACTUAL_CANDIDATE_SNAPSHOT"', self.workflow)
        self.assertIn("'-snapshot', $env:ACTUAL_CANDIDATE_SNAPSHOT", self.workflow)
        self.assertNotIn('update_gamedata.py -gamever "$env:GAMEVER" -bindir', self.workflow)
        self.assertNotIn("run_cpp_tests.py @args -bindir", self.workflow)

    def test_build_creates_follow_up_snapshot_pr_and_archives_snapshot(self) -> None:
        self.assertIn("pull-requests: write", self.workflow)
        self.assertIn("gamesymbols/$env:GAMEVER.yaml", self.workflow)
        self.assertIn("gamesymbols/$env:GAMEVER", self.workflow)
        self.assertIn("gh pr create", self.workflow)


if __name__ == "__main__":
    unittest.main()
