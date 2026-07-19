import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(".claude/skills/abandon-staged-release/scripts/abandon_staged_release.py")
SPEC = importlib.util.spec_from_file_location("abandon_staged_release", SCRIPT)
abandon = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(abandon)


def completed(command, *, stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def pull_request_payload(**overrides) -> dict:
    payload = {
        "number": 582,
        "state": "closed",
        "merged_at": "2026-07-19T12:48:13Z",
        "html_url": "https://github.com/HLND2T/CS2_VibeSignatures/pull/582",
        "user": {"login": "github-actions[bot]"},
        "head": {
            "ref": "gamesymbols/build/14168/29686825445-1",
            "sha": "6a44f19be35e6fc876d9e74b46f494f214b383d1",
            "repo": {"full_name": "HLND2T/CS2_VibeSignatures"},
        },
        "base": {"ref": "main"},
    }
    payload.update(overrides)
    return payload


class TestAbandonStagedRelease(unittest.TestCase):
    def test_script_resolves_its_own_repository_root(self) -> None:
        expected = SCRIPT.resolve().parents[4]
        with patch.object(abandon, "run_command", return_value=completed([], stdout=f"{expected}\n")):
            self.assertEqual(expected, abandon.repository_root())

    def test_skill_is_explicit_and_uses_only_the_bundled_dispatch_script(self) -> None:
        skill = Path(".claude/skills/abandon-staged-release/SKILL.md").read_text(encoding="utf-8")
        agent = Path(".claude/skills/abandon-staged-release/agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("Use only when the user explicitly asks", skill)
        self.assertIn("allow_implicit_invocation: false", agent)
        self.assertIn("bundled script as the only remote-operation entry point", skill)
        self.assertIn("Do not run `cleanup-unmerged`", skill)
        self.assertIn("never automatically reruns a release build", skill)

    def test_pr_identity_is_derived_from_the_trusted_merged_output_pr(self) -> None:
        with patch.object(
            abandon,
            "run_command",
            return_value=completed([], stdout=json.dumps(pull_request_payload())),
        ):
            identity = abandon.load_pr_identity(
                Path("."),
                "HLND2T/CS2_VibeSignatures",
                582,
                "ABANDON 14168/29686825445-1",
                "Promotion failed before promote-bin",
            )
        self.assertEqual("14168", identity["gamever"])
        self.assertEqual("29686825445-1", identity["build_id"])
        self.assertEqual("6a44f19be35e6fc876d9e74b46f494f214b383d1", identity["head_sha"])

    def test_pr_identity_rejects_untrusted_or_unmerged_requests(self) -> None:
        cases = (
            ({"merged_at": None}, "must be merged"),
            ({"user": {"login": "someone"}}, "github-actions"),
            (
                {
                    "head": {
                        "ref": "gamesymbols/build/14168/29686825445-1",
                        "sha": "6a44f19be35e6fc876d9e74b46f494f214b383d1",
                        "repo": {"full_name": "other/repository"},
                    }
                },
                "trusted same-repository",
            ),
        )
        for overrides, message in cases:
            with (
                self.subTest(message=message),
                patch.object(
                    abandon,
                    "run_command",
                    return_value=completed([], stdout=json.dumps(pull_request_payload(**overrides))),
                ),
            ):
                with self.assertRaisesRegex(abandon.AbandonError, message):
                    abandon.load_pr_identity(
                        Path("."),
                        "HLND2T/CS2_VibeSignatures",
                        582,
                        "ABANDON 14168/29686825445-1",
                        "Promotion failed before promote-bin",
                    )

    def test_confirmation_and_reason_are_strict(self) -> None:
        with patch.object(
            abandon,
            "run_command",
            return_value=completed([], stdout=json.dumps(pull_request_payload())),
        ):
            with self.assertRaisesRegex(abandon.AbandonError, "confirmation"):
                abandon.load_pr_identity(
                    Path("."),
                    "HLND2T/CS2_VibeSignatures",
                    582,
                    "ABANDON 14168/wrong",
                    "Promotion failed before promote-bin",
                )
            with self.assertRaisesRegex(abandon.AbandonError, "one non-empty line"):
                abandon.load_pr_identity(
                    Path("."),
                    "HLND2T/CS2_VibeSignatures",
                    582,
                    "ABANDON 14168/29686825445-1",
                    "bad\nreason",
                )

    def test_duplicate_active_workflow_is_rejected(self) -> None:
        runs = [
            {
                "databaseId": 123,
                "displayTitle": "Abandon staged release PR #582",
                "status": "in_progress",
                "url": "https://github.com/example/run",
            }
        ]
        with patch.object(abandon, "list_runs", return_value=runs):
            with self.assertRaisesRegex(abandon.AbandonError, "already active"):
                abandon.require_no_duplicate(Path("."), 582)

    def test_dispatch_uses_only_derived_identity_and_audit_inputs(self) -> None:
        identity = {
            "pr_number": 582,
            "confirmation": "ABANDON 14168/29686825445-1",
            "reason": "Promotion failed before promote-bin",
        }
        with patch.object(abandon, "run_command", return_value=completed([])) as run:
            abandon.dispatch(Path("."), identity)
        command = run.call_args.args[0]
        self.assertIn("abandon-staged-release.yml", command)
        self.assertIn("pr_number=582", command)
        self.assertIn("confirmation=ABANDON 14168/29686825445-1", command)
        self.assertIn("reason=Promotion failed before promote-bin", command)
        self.assertNotIn("staging_root", " ".join(command))

    def test_execute_reports_the_dispatched_recovery_run(self) -> None:
        identity = {
            "pr_number": 582,
            "pr_url": "https://github.com/HLND2T/CS2_VibeSignatures/pull/582",
            "gamever": "14168",
            "build_id": "29686825445-1",
            "head_sha": "6" * 40,
            "confirmation": "ABANDON 14168/29686825445-1",
            "reason": "Promotion failed before promote-bin",
        }
        with (
            patch.object(abandon, "repository_root", return_value=Path(".")),
            patch.object(abandon, "require_repository", return_value="HLND2T/CS2_VibeSignatures"),
            patch.object(abandon, "require_github_access"),
            patch.object(abandon, "resolve_main", return_value="a" * 40),
            patch.object(abandon, "load_pr_identity", return_value=identity.copy()),
            patch.object(abandon, "require_no_duplicate", return_value={1}),
            patch.object(abandon, "require_main_unchanged"),
            patch.object(abandon, "dispatch") as dispatch,
            patch.object(abandon, "discover_run", return_value="https://github.com/example/run"),
        ):
            result = abandon.execute(
                582,
                "ABANDON 14168/29686825445-1",
                "Promotion failed before promote-bin",
            )
        dispatch.assert_called_once()
        self.assertEqual("https://github.com/example/run", result["run_url"])
        self.assertEqual("a" * 40, result["source_sha"])

    def test_recovery_workflow_derives_identity_and_uses_promotion_concurrency(self) -> None:
        workflow = Path(".github/workflows/abandon-staged-release.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("gamever:\n        description:", workflow)
        self.assertNotIn("build_id:\n        description:", workflow)
        self.assertIn('gh api "repos/${{ github.repository }}/pulls/$env:PR_NUMBER"', workflow)
        self.assertIn("release-promotion-${{ github.repository }}-${{ needs.resolve.outputs.gamever }}", workflow)
        self.assertIn("runs-on: [self-hosted, windows, x64]", workflow)
        self.assertIn("environment: win64", workflow)
        self.assertIn("release_workflow.py abandon-pending", workflow)
        self.assertIn("secrets.PERSISTED_WORKSPACE", workflow)
        self.assertIn('--pr-number "$env:PR_NUMBER"', workflow)
        self.assertNotIn('--pr-number "${{ inputs.pr_number }}"', workflow)
        self.assertNotIn("cleanup-unmerged", workflow)


if __name__ == "__main__":
    unittest.main()
