from pathlib import Path
import unittest


class TestPrSelfRunnerWorkflow(unittest.TestCase):
    def test_listens_for_pull_request_closed_events(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn("types: [opened, synchronize, reopened, ready_for_review, closed]", workflow)

    def test_validation_job_does_not_run_for_closed_events(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn("github.event.action != 'closed' &&", workflow)

    def test_skips_automated_bump_download_pull_requests(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository &&",
            workflow,
        )
        self.assertIn(
            "!(github.event.pull_request.user.login == 'github-actions[bot]' &&",
            workflow,
        )
        self.assertIn(
            "startsWith(github.event.pull_request.head.ref, 'bump-download/')",
            workflow,
        )
        self.assertIn(
            "startsWith(github.event.pull_request.title, 'chore(download): Update manifest for ')",
            workflow,
        )

    def test_cpp_test_steps_fail_on_run_cpp_tests_nonzero_exit(self) -> None:
        for workflow_path in (
            ".github/workflows/pr-self-runner.yml",
            ".github/workflows/build-on-self-runner.yml",
        ):
            with self.subTest(workflow_path=workflow_path):
                workflow = Path(workflow_path).read_text(encoding="utf-8")

                self.assertIn("uv run run_cpp_tests.py", workflow)
                self.assertIn(
                    'throw "run_cpp_tests.py failed with exit code $LASTEXITCODE"',
                    workflow,
                )

    def test_closed_event_finalizes_pr_workspace_instead_of_cleaning_bin_copy(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertNotIn("- name: Clean PR bin copy", workflow)
        self.assertIn("finalize-pr-workspace:", workflow)
        self.assertIn("- name: Finalize PR workspace", workflow)
        self.assertIn('$prWasMerged = "${{ github.event.pull_request.merged }}"', workflow)
        self.assertIn("robocopy @robocopyArgs", workflow)
        self.assertIn('"*.yaml"', workflow)
        self.assertIn(".snapshot-validation-success", workflow)
        self.assertIn("if ($robocopyExitCode -ge 8)", workflow)
        self.assertIn("Remove-Item -LiteralPath $prWorkspace -Recurse -Force", workflow)
        self.assertIn('Write-Host "Removed PR workspace: $prWorkspace"', workflow)

    def test_closed_event_leaves_pr_workspace_before_deleting_it(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn(
            "Set-Location $workspaceRoot\n\n          Remove-Item -LiteralPath $prWorkspace -Recurse -Force",
            workflow,
        )

    def test_uses_base_snapshot_then_invalidates_before_analysis(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        restore = workflow.index("gamesymbol_snapshot.py restore")
        invalidate = workflow.index("gamesymbol_pr_validation.py invalidate")
        analyze = workflow.index("uv run ida_analyze_bin.py")
        verify = workflow.index("gamesymbol_snapshot.py verify")
        gamedata = workflow.index("uv run update_gamedata.py")

        self.assertIn('Export-GitBlob "HEAD^1" "config.yaml"', workflow)
        self.assertIn('Export-GitBlob "HEAD^1" $sameVersionSnapshot', workflow)
        self.assertIn("bootstrap PR validation will rebuild all current YAML", workflow)
        self.assertLess(restore, invalidate)
        self.assertLess(invalidate, analyze)
        self.assertLess(analyze, verify)
        self.assertLess(verify, gamedata)
        self.assertNotIn("prune_pr_expected_output_bin.py", workflow)

    def test_pr_validation_marks_success_only_after_cpp_tests(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        cpp_tests = workflow.index("uv run run_cpp_tests.py")
        marker = workflow.index(".snapshot-validation-success")

        self.assertLess(cpp_tests, marker)


if __name__ == "__main__":
    unittest.main()
