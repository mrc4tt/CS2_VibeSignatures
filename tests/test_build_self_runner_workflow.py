import unittest
from pathlib import Path


class TestBuildSelfRunnerWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = Path(".github/workflows/build-on-self-runner.yml").read_text(encoding="utf-8")
        self.promotion = Path(".github/workflows/promote-release-after-output-merge.yml").read_text(encoding="utf-8")

    def test_build_is_dispatch_only_with_machine_inputs(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("repository_dispatch:", self.workflow)
        self.assertIn("source_sha:", self.workflow)
        self.assertIn("options: [new, republish]", self.workflow)
        self.assertNotIn("push:\n    tags:", self.workflow)

    def test_preflight_validates_before_self_hosted_build(self) -> None:
        preflight = self.workflow.index("preflight:")
        self_hosted = self.workflow.index("runs-on: [self-hosted, windows, x64]")
        validation = self.workflow.index("release_workflow.py validate-build")
        self.assertLess(preflight, validation)
        self.assertLess(validation, self_hosted)
        self.assertIn("SOURCE_SHA is not reachable", Path("release_workflow_lib/validation.py").read_text())
        self.assertIn('gh release view "$gamever"', self.workflow)

    def test_checkout_uses_exact_source_sha_not_tag(self) -> None:
        self.assertIn("ref: ${{ needs.preflight.outputs.source_sha }}", self.workflow)
        self.assertNotIn("ref: ${{ github.ref }}", self.workflow)
        self.assertNotIn("github.ref_name", self.workflow)

    def test_workspace_bin_is_real_and_republish_uses_affected_invalidation(self) -> None:
        self.assertIn("Workspace bin must be a real directory", self.workflow)
        self.assertIn("Copied persisted bin/$env:GAMEVER into build workspace", self.workflow)
        self.assertIn("release_workflow.py invalidate-republish", self.workflow)
        self.assertIn("if: env.MODE == 'republish'", self.workflow)
        self.assertNotIn("force every preprocessor", self.workflow.lower())

    def test_major_update_is_the_only_workflow_reason_for_oldgamever_none(self) -> None:
        self.assertIn("if ($major -eq 'true') { $args += @('-oldgamever', 'none') }", self.workflow)
        self.assertEqual(1, self.workflow.count("'-oldgamever', 'none'"))

    def test_candidate_validation_precedes_staging_and_output_pr(self) -> None:
        analyze = self.workflow.index("uv run ida_analyze_bin.py")
        candidate = self.workflow.index("gamesymbol_candidate.py build")
        gamedata = self.workflow.index("uv run update_gamedata.py")
        cpp_tests = self.workflow.index("uv run run_cpp_tests.py")
        publish = self.workflow.index("gamesymbol_candidate.py publish")
        stage = self.workflow.index("release_workflow.py stage-build")
        output_pr = self.workflow.index("gh pr create")
        self.assertLess(analyze, candidate)
        self.assertLess(candidate, gamedata)
        self.assertLess(gamedata, cpp_tests)
        self.assertLess(cpp_tests, publish)
        self.assertLess(publish, stage)
        self.assertLess(stage, output_pr)

    def test_build_passes_one_immutable_analysis_config_through_every_stage(self) -> None:
        self.assertIn("ANALYSIS_CONFIG=", self.workflow)
        self.assertIn("ANALYSIS_CONFIG_SHA256=", self.workflow)
        self.assertIn('-config "$env:ANALYSIS_CONFIG"', self.workflow)
        self.assertIn('-configyaml "$env:ANALYSIS_CONFIG"', self.workflow)
        self.assertIn('--analysis-config "$env:ANALYSIS_CONFIG"', self.workflow)

    def test_build_stops_after_pending_pr_without_publication(self) -> None:
        self.assertIn("release-manifests/$env:GAMEVER.json", self.workflow)
        self.assertIn("gamesymbols/$env:GAMEVER/build-$env:BUILD_ID", self.workflow)
        self.assertIn("release_workflow.py write-pr-index", self.workflow)
        self.assertNotIn("Archive release payload", self.workflow)
        self.assertNotIn("Promote verified bin transactionally", self.workflow)
        self.assertNotIn("action-gh-release", self.workflow)
        self.assertNotIn("gh release upload", self.workflow)
        self.assertNotIn("git tag ", self.workflow)

    def test_output_branch_is_immutable_after_review_starts(self) -> None:
        self.assertIn('git checkout -b "$env:OUTPUT_BRANCH"', self.workflow)
        self.assertIn('git push origin "HEAD:refs/heads/$env:OUTPUT_BRANCH"', self.workflow)
        self.assertNotIn("--force-with-lease", self.workflow)

    def test_full_repository_checks_run_before_analysis(self) -> None:
        unit_tests = self.workflow.index("python -m unittest discover -s tests -b")
        analysis = self.workflow.index("uv run ida_analyze_bin.py")
        self.assertIn("format_repo_files.py --check", self.workflow)
        self.assertLess(unit_tests, analysis)

    def test_promotion_orders_verification_before_publication(self) -> None:
        verify = self.promotion.index("release_workflow.py verify-promotion")
        archive = self.promotion.index("Create release archives")
        promote = self.promotion.index("release_workflow.py promote-bin")
        tag = self.promotion.index("Apply immutable tag rules")
        release = self.promotion.index("gh release upload")
        complete = self.promotion.index("release_workflow.py finalize-promotion")
        self.assertLess(verify, archive)
        self.assertLess(archive, promote)
        self.assertLess(promote, tag)
        self.assertLess(tag, release)
        self.assertLess(release, complete)
        self.assertIn("--clobber", self.promotion)
        self.assertIn("Uploaded asset hash mismatch", self.promotion)
        self.assertIn("Checkout trusted promotion tooling from merge base", self.promotion)
        self.assertIn(".release-tools/release_workflow.py verify-promotion", self.promotion)
        self.assertIn('"configs\\$gamever.yaml"', self.promotion)
        self.assertIn("analysis_config_sha256", self.promotion)
        self.assertIn('git", "show", f"{sys.argv[1]}:configs/{sys.argv[3]}.yaml"', self.promotion)

    def test_bump_merge_dispatches_without_creating_tag(self) -> None:
        workflow = Path(".github/workflows/tag-bump-after-merge.yml").read_text(encoding="utf-8")
        self.assertIn("gamever = $gamever", workflow)
        self.assertIn("source_sha = $sourceSha", workflow)
        self.assertIn('mode = "new"', workflow)
        self.assertIn("source_pull_request", workflow)
        self.assertIn("contents/configs/$gamever.yaml?ref=$sourceSha", workflow)
        self.assertNotIn("git tag", workflow)
        self.assertNotIn("git push origin", workflow)

    def test_existing_config_missing_tag_dispatches_instead_of_repairing_tag(self) -> None:
        workflow = Path(".github/workflows/bump-download.yml").read_text(encoding="utf-8")
        self.assertIn("dispatch_build == 'true'", workflow)
        self.assertIn('mode = "new"', workflow)
        self.assertIn("source_sha = $headSha.Trim()", workflow)
        self.assertNotIn("Failed to push repaired tag", workflow)
        self.assertNotIn('git push origin "refs/tags/', workflow)
        self.assertIn("configs/$tag.yaml", workflow)

    def test_bump_workflow_carries_version_config_in_preview_and_pr_contract(self) -> None:
        workflow = Path(".github/workflows/bump-download.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count("-configs-dir configs"), 2)
        self.assertIn("analysis_config_source_gamever", workflow)
        self.assertIn("analysis_config_path", workflow)
        self.assertIn("exact initial copy", workflow)

    def test_generated_output_pr_has_a_lightweight_required_check(self) -> None:
        workflow = Path(".github/workflows/validate-generated-output-pr.yml").read_text(encoding="utf-8")
        self.assertIn("release_workflow.py verify-output-pr", workflow)
        self.assertIn("Checkout trusted validation tooling from PR base", workflow)
        self.assertIn(".release-tools/release_workflow.py verify-output-pr", workflow)
        self.assertIn("github.event.pull_request.base.sha", workflow)
        self.assertIn("github.event.pull_request.head.sha", workflow)
        self.assertNotIn("ida_analyze_bin.py", workflow)


if __name__ == "__main__":
    unittest.main()
