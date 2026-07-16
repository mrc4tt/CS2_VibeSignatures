import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.promotion import verify_output_pr, verify_promotion
from release_workflow_lib.staging import cleanup_incomplete, cleanup_unmerged
from release_workflow_lib.validation import invalidate_republish, validate_build_input
from tests.test_release_workflow import ReleaseFixture


class TestReleaseWorkflowGuards(unittest.TestCase):
    def test_new_and_republish_tag_presence_guards(self) -> None:
        source_sha = "1" * 40
        download = b'downloads:\n  - tag: "14170"\n'
        merge_ok = subprocess.CompletedProcess([], 0)
        tag_missing = subprocess.CompletedProcess([], 1)
        tag_present = subprocess.CompletedProcess([], 0)
        with (
            patch("release_workflow_lib.validation.git_output", side_effect=["", download, b"modules: []\n"]),
            patch("release_workflow_lib.validation.subprocess.run", side_effect=[merge_ok, tag_present]),
        ):
            with self.assertRaisesRegex(ReleaseWorkflowError, "mode=new requires tag"):
                validate_build_input(
                    repository="HLND2T/CS2_VibeSignatures",
                    gamever="14170",
                    source_sha=source_sha,
                    mode="new",
                    default_ref="origin/main",
                )
        with (
            patch("release_workflow_lib.validation.git_output", side_effect=["", download, b"modules: []\n"]),
            patch("release_workflow_lib.validation.subprocess.run", side_effect=[merge_ok, tag_missing]),
        ):
            with self.assertRaisesRegex(ReleaseWorkflowError, "mode=republish requires tag"):
                validate_build_input(
                    repository="HLND2T/CS2_VibeSignatures",
                    gamever="14170",
                    source_sha=source_sha,
                    mode="republish",
                    default_ref="origin/main",
                )

    def test_first_republish_without_manifest_uses_conservative_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            game_root = repo / "bin" / "14170"
            game_root.mkdir(parents=True)
            (game_root / "client.yaml").write_text("value: 1\n", encoding="utf-8")
            (game_root / "client.dll").write_bytes(b"dll")

            deleted = invalidate_republish(
                repo_root=repo,
                gamever="14170",
                source_sha="1" * 40,
                bindir=repo / "bin",
            )

            self.assertEqual(1, deleted)
            self.assertFalse((game_root / "client.yaml").exists())
            self.assertTrue((game_root / "client.dll").exists())

    def test_lightweight_output_pr_check_rejects_stale_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            with patch(
                "release_workflow_lib.promotion._git_output",
                return_value="gamesymbols/14170.yaml\nrelease-manifests/14170.json",
            ):
                with self.assertRaisesRegex(ReleaseWorkflowError, "stale"):
                    verify_output_pr(
                        repo_root=fixture.repo,
                        repository="HLND2T/CS2_VibeSignatures",
                        head_repository="HLND2T/CS2_VibeSignatures",
                        author="github-actions[bot]",
                        branch=f"gamesymbols/{fixture.gamever}/build-{fixture.build_id}",
                        base_sha="9" * 40,
                        head_sha=fixture.head_sha,
                    )

    def test_promotion_rejects_merge_whose_base_parent_is_not_source_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            fixture.finalize_and_index()
            with patch(
                "release_workflow_lib.promotion._git_output",
                return_value=f"{'4' * 40} {'9' * 40} {fixture.head_sha}",
            ):
                with self.assertRaisesRegex(ReleaseWorkflowError, "merge parents"):
                    verify_promotion(
                        repo_root=fixture.repo,
                        staging_root=fixture.staging,
                        repository="HLND2T/CS2_VibeSignatures",
                        head_repository="HLND2T/CS2_VibeSignatures",
                        author="github-actions[bot]",
                        branch=f"gamesymbols/{fixture.gamever}/build-{fixture.build_id}",
                        base_branch="main",
                        default_branch="main",
                        pr_number=42,
                        event_head_sha=fixture.head_sha,
                        merge_sha="4" * 40,
                    )

    def test_unmerged_cleanup_cannot_touch_accepted_bin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            stage_dir = fixture.finalize_and_index()
            accepted = fixture.root / "persisted" / "bin" / fixture.gamever
            accepted.mkdir(parents=True)
            marker = accepted / "accepted.dll"
            marker.write_bytes(b"accepted")

            cleanup_unmerged(fixture.staging, 42, fixture.head_sha)

            self.assertFalse(stage_dir.exists())
            self.assertEqual(b"accepted", marker.read_bytes())

    def test_incomplete_cleanup_removes_only_state_without_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "release-staging"
            incomplete = root / "14170" / "1-1"
            ready = root / "14170" / "2-1"
            incomplete.mkdir(parents=True)
            ready.mkdir(parents=True)
            (incomplete / "manifest.json").write_text("{}\n", encoding="utf-8")
            (ready / "READY").write_text("hash\n", encoding="ascii")

            self.assertTrue(cleanup_incomplete(root, "14170", "1-1"))
            self.assertFalse(cleanup_incomplete(root, "14170", "2-1"))
            self.assertFalse(incomplete.exists())
            self.assertTrue(ready.exists())


if __name__ == "__main__":
    unittest.main()
