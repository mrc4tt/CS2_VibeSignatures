import unittest
from pathlib import Path


class TestBuildSelfRunnerWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = Path(".github/workflows/build-on-self-runner.yml").read_text(encoding="utf-8")

    def test_workspace_bin_is_real_and_not_linked_to_persisted_bin(self) -> None:
        self.assertNotIn('mklink /d "%WORKSPACE%\\bin"', self.workflow)
        self.assertIn("Workspace bin must be a real directory", self.workflow)
        self.assertIn("Copied persisted bin/$env:GAMEVER into build workspace", self.workflow)

    def test_snapshot_is_packed_after_full_validation(self) -> None:
        cpp_tests = self.workflow.index("uv run run_cpp_tests.py")
        pack = self.workflow.index("gamesymbol_snapshot.py pack")
        persist = self.workflow.index("Persist validated bin cache")

        self.assertLess(cpp_tests, pack)
        self.assertLess(pack, persist)

    def test_build_creates_follow_up_snapshot_pr_and_archives_snapshot(self) -> None:
        self.assertIn("pull-requests: write", self.workflow)
        self.assertIn("gamesymbols/$env:GAMEVER.yaml", self.workflow)
        self.assertIn("gamesymbols/$env:GAMEVER", self.workflow)
        self.assertIn("gh pr create", self.workflow)


if __name__ == "__main__":
    unittest.main()
