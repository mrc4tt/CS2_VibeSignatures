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

    def test_skips_automated_gamesymbol_output_pull_requests(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")
        output_filter = (
            "!(github.event.pull_request.user.login == 'github-actions[bot]' &&\n"
            "        startsWith(github.event.pull_request.head.ref, 'gamesymbols/') &&\n"
            "        startsWith(github.event.pull_request.title, 'chore(gamesymbols): publish '))"
        )

        self.assertEqual(2, workflow.count(output_filter))

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

    def test_closed_event_deletes_workspace_without_persisting_pr_yaml(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertNotIn("- name: Clean PR bin copy", workflow)
        self.assertIn("finalize-pr-workspace:", workflow)
        self.assertIn("- name: Finalize PR workspace", workflow)
        self.assertIn('$prWasMerged = "${{ github.event.pull_request.merged }}"', workflow)
        self.assertIn("candidate validation never writes persisted YAML", workflow)
        self.assertNotIn("Copied PR bin/$gamever YAML files into persisted workspace", workflow)
        self.assertIn("Remove-Item -LiteralPath $prWorkspace -Recurse -Force", workflow)
        self.assertIn('Write-Host "Removed PR workspace: $prWorkspace"', workflow)

    def test_closed_event_leaves_pr_workspace_before_deleting_it(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn(
            "Set-Location $workspaceRoot\n\n          Remove-Item -LiteralPath $prWorkspace -Recurse -Force",
            workflow,
        )

    def test_uses_selected_base_gamever_for_entire_validation(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        extract = workflow.index("- name: Extract deterministic base snapshot")
        copy_bin = workflow.index("- name: Prepare persisted depot link and PR bin copy")
        restore = workflow.index("gamesymbol_snapshot.py restore")
        invalidate = workflow.index("gamesymbol_pr_validation.py invalidate")
        analyze = workflow.index("uv run ida_analyze_bin.py")
        candidate = workflow.index("gamesymbol_candidate.py build")
        compare = workflow.index("gamesymbol_candidate.py compare")
        gamedata = workflow.index("uv run update_gamedata.py")
        cpp_tests = workflow.index("uv run run_cpp_tests.py")

        self.assertIn('$baseRef = "${{ github.event.pull_request.base.sha }}".Trim()', workflow)
        self.assertIn('$versionedBaseConfig = "configs/$baseGamever.yaml"', workflow)
        self.assertIn('Export-GitBlob $baseSnapshotCommit "config.yaml"', workflow)
        self.assertIn('"PR_GAMEVER=$gamever"', workflow)
        self.assertIn('$sameVersionSnapshot = "gamesymbols/$env:PR_GAMEVER.yaml"', workflow)
        self.assertIn("$validationGamever = $baseGamever", workflow)
        self.assertIn('"GAMEVER=$validationGamever"', workflow)
        self.assertIn('Export-GitBlob "HEAD" $headSnapshotRepoPath $headSnapshot', workflow)
        self.assertIn('"HEAD_SNAPSHOT=$headSnapshot"', workflow)
        self.assertIn('"HEAD_CONFIG=$headConfig"', workflow)
        self.assertIn('-headconfigyaml "$env:HEAD_CONFIG"', workflow)
        self.assertIn("bootstrap PR validation will rebuild $validationGamever", workflow)
        self.assertIn('-baseref "$env:BASE_REF"', workflow)
        self.assertIn('-headsnapshot "$env:HEAD_SNAPSHOT"', workflow)
        self.assertLess(extract, copy_bin)
        self.assertLess(restore, invalidate)
        self.assertLess(invalidate, analyze)
        self.assertLess(analyze, candidate)
        self.assertLess(candidate, compare)
        self.assertLess(compare, gamedata)
        self.assertLess(gamedata, cpp_tests)
        self.assertNotIn("SAME_VERSION_BASE", workflow)
        self.assertNotIn("$env:PR_GAMEVER", workflow[copy_bin:])
        self.assertNotIn("gamesymbol_snapshot.py verify", workflow)
        self.assertNotIn("prune_pr_expected_output_bin.py", workflow)

    def test_base_ref_snapshot_selection_does_not_sort_by_filename(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn("$trackedSnapshots = @(\n", workflow)
        self.assertIn("git ls-tree -r --name-only $baseRef -- gamesymbols", workflow)
        self.assertIn("$trackedSnapshots -contains $sameVersionSnapshot", workflow)
        self.assertIn("$baseSnapshotRepoPath = $trackedSnapshots[0]", workflow)
        self.assertIn("git log -1 --format=%H --name-only $baseRef -- gamesymbols", workflow)
        self.assertIn("$baseSnapshotRepoPath = $latestSnapshotPaths[0]", workflow)
        self.assertNotIn("$trackedSnapshots[-1]", workflow)
        self.assertNotIn("Sort-Object", workflow)

    def test_actual_candidate_is_the_only_downstream_symbol_source(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        self.assertIn("ACTUAL_CANDIDATE_SNAPSHOT=$candidate", workflow)
        self.assertIn('-expected "$env:HEAD_SNAPSHOT"', workflow)
        self.assertIn('-snapshot "$env:ACTUAL_CANDIDATE_SNAPSHOT"', workflow)
        self.assertNotIn("gamesymbol_candidate.py publish", workflow)
        self.assertNotIn('update_gamedata.py -gamever "$env:GAMEVER" -bindir', workflow)
        self.assertNotIn('run_cpp_tests.py -gamever "$env:GAMEVER" -bindir', workflow)

    def test_baseline_probe_controls_incremental_or_shared_bootstrap_paths(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")
        step_start = workflow.index("- name: Restore deterministic base and invalidate affected outputs")
        tests_start = workflow.index("- name: Run Python unit tests")
        step = workflow[step_start:tests_start]

        probe = step.index("gamesymbol_snapshot.py check-contract")
        restore = step.index("gamesymbol_snapshot.py restore")
        invalidate = step.index("gamesymbol_pr_validation.py invalidate")
        self.assertLess(probe, restore)
        self.assertLess(restore, invalidate)
        self.assertIn("if ($probeExitCode -eq 0)", step)
        self.assertIn("elseif ($probeExitCode -eq 3)", step)
        self.assertIn('throw "Baseline contract probe failed with exit code $probeExitCode', step)
        self.assertIn('$baselineMode = "trusted-incremental"', step)
        self.assertIn('$baselineMode = "untrusted-bootstrap"', step)
        self.assertIn('$baselineMode = "absent-bootstrap"', step)
        self.assertEqual(3, step.count("Clear-BootstrapYaml"))
        self.assertIn('"HAS_BASE_SNAPSHOT=false"', step)
        self.assertIn('if ($baselineMode -eq "trusted-incremental")', step)
        self.assertIn('elseif ($baselineMode -eq "absent-bootstrap")', step)

    def test_untrusted_baseline_fallback_is_observable_and_yaml_only(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")
        step_start = workflow.index("- name: Restore deterministic base and invalidate affected outputs")
        tests_start = workflow.index("- name: Run Python unit tests")
        step = workflow[step_start:tests_start]

        self.assertIn("::warning title=Baseline snapshot rejected::reason=$baselineReason", step)
        self.assertIn('"BASELINE_MODE=$baselineMode"', step)
        self.assertIn('"Baseline mode: $baselineMode"', step)
        self.assertIn('"Reason: $baselineReason"', step)
        self.assertIn('"Incremental invalidation:', step)
        self.assertIn('Get-ChildItem -LiteralPath $gameRoot -Recurse -File -Filter "*.yaml"', step)
        self.assertIn("Bootstrap cleanup path must not traverse a reparse point", step)
        self.assertNotIn("Remove-Item -LiteralPath $gameRoot -Recurse", step)

    def test_pr_validation_marks_success_only_after_cpp_tests(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")

        cpp_tests = workflow.index("uv run run_cpp_tests.py")
        marker = workflow.index(".snapshot-validation-success")

        self.assertLess(cpp_tests, marker)

    def test_cpp_validation_selects_sdk_for_effective_gamever_only(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")
        submodule = workflow.index("git submodule update --init --recursive")
        gamedata = workflow.index("uv run update_gamedata.py")
        selector_start = workflow.index("- name: Select versioned SDK for C++ ABI validation")
        cpp_tests = workflow.index("uv run run_cpp_tests.py")
        selector = workflow[selector_start:cpp_tests]

        self.assertLess(submodule, selector_start)
        self.assertLess(gamedata, selector_start)
        self.assertIn('$sdkRef = "cs2-$env:GAMEVER"', selector)
        self.assertNotIn("$env:PR_GAMEVER", selector)
        self.assertIn('$sdkRemote = "https://github.com/HLND2T/hl2sdk.git"', selector)
        self.assertIn('ls-remote --heads $sdkRemote "refs/heads/$sdkRef"', selector)
        self.assertIn("SDK_ABI_REF=pinned-submodule", selector)
        self.assertIn("SDK_ABI_SHA=$pinnedSha", selector)
        self.assertIn("No versioned SDK branch exists for $sdkRef", selector)
        self.assertIn('fetch --no-tags $sdkRemote "refs/heads/$sdkRef"', selector)
        self.assertIn("checkout --detach $remoteSha", selector)
        self.assertIn("selected SHA=$selectedSha; pinned SHA=$pinnedSha", selector)

    def test_cpp_validation_restores_pinned_sdk_even_after_failure(self) -> None:
        workflow = Path(".github/workflows/pr-self-runner.yml").read_text(encoding="utf-8")
        cpp_tests = workflow.index("uv run run_cpp_tests.py")
        restore_start = workflow.index("- name: Restore pinned SDK revision")
        success = workflow.index("- name: Mark snapshot validation success")
        restore = workflow[restore_start:success]

        self.assertLess(cpp_tests, restore_start)
        self.assertIn("if: always()", restore)
        self.assertIn('if ($env:SDK_ABI_SWITCHED -ne "true")', restore)
        self.assertIn('checkout --detach "$env:SDK_PINNED_SHA"', restore)
        self.assertIn("restored pinned SHA=$restoredSha", restore)


if __name__ == "__main__":
    unittest.main()
