import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gamesymbol_snapshot_lib.codec import build_snapshot_document, canonical_snapshot_bytes
from gamesymbol_snapshot_lib.config import load_contract
from release_workflow_lib.cli import _parser
from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.promotion import verify_output_pr, verify_promotion
from release_workflow_lib.staging import abandon_pending, cleanup_incomplete, cleanup_unmerged
from release_workflow_lib.validation import invalidate_republish, validate_build_input
from tests.test_release_workflow import ReleaseFixture
from tests.release_branch_protocol import LEGACY_OUTPUT_BRANCH
from release_workflow_lib.manifests import format_output_branch


class LegacyBootstrapFixture:
    gamever = "14170"

    def __init__(self, root: Path) -> None:
        self.repo = root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "tests@example.com")
        self.git("config", "user.name", "Tests")
        self.config = self.repo / "configs" / f"{self.gamever}.yaml"
        self.snapshot = self.repo / "gamesymbols" / f"{self.gamever}.yaml"
        changed_skill = self.repo / ".claude" / "skills" / "find-Changed" / "SKILL.md"
        stable_skill = self.repo / ".claude" / "skills" / "find-Stable" / "SKILL.md"
        self.config.parent.mkdir(parents=True)
        self.snapshot.parent.mkdir(parents=True)
        changed_skill.parent.mkdir(parents=True)
        stable_skill.parent.mkdir(parents=True)
        self.config.write_text(
            "modules:\n"
            "  - name: server\n"
            "    path_windows: game/bin/win64/server.dll\n"
            "    skills:\n"
            "      - name: find-Changed\n"
            "        platform: windows\n"
            "        expected_output:\n"
            "          - Changed.{platform}.yaml\n"
            "      - name: find-Stable\n"
            "        platform: windows\n"
            "        expected_output:\n"
            "          - Stable.{platform}.yaml\n",
            encoding="utf-8",
        )
        changed_skill.write_text("changed v1\n", encoding="utf-8")
        stable_skill.write_text("stable v1\n", encoding="utf-8")
        contract = load_contract(self.config, self.gamever, self.repo / "bin")
        document = build_snapshot_document(
            self.gamever,
            contract.config_sha256,
            {
                "server/Changed.windows.yaml": {"func_name": "Changed", "func_rva": "0x10"},
                "server/Stable.windows.yaml": {"func_name": "Stable", "func_rva": "0x20"},
            },
        )
        self.snapshot.write_bytes(canonical_snapshot_bytes(document))
        self.git("add", ".")
        self.git("commit", "-m", "legacy snapshot")
        self.base_sha = self.git("rev-parse", "HEAD")
        changed_skill.write_text("changed v2\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "change one producer")
        self.source_sha = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


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

    def test_legacy_bootstrap_requires_explicit_cli_flag(self) -> None:
        parser = _parser()
        common = [
            "invalidate-republish",
            "--gamever",
            "14170",
            "--source-sha",
            "1" * 40,
        ]

        self.assertFalse(parser.parse_args(common).allow_legacy_bootstrap)
        self.assertTrue(parser.parse_args([*common, "--allow-legacy-bootstrap"]).allow_legacy_bootstrap)

    def test_explicit_legacy_bootstrap_restores_snapshot_and_invalidates_changed_producer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = LegacyBootstrapFixture(Path(tmp))

            deleted = invalidate_republish(
                repo_root=fixture.repo,
                gamever=fixture.gamever,
                source_sha=fixture.source_sha,
                bindir=fixture.repo / "bin",
                allow_legacy_bootstrap=True,
            )

            game_root = fixture.repo / "bin" / fixture.gamever / "server"
            self.assertEqual(1, deleted)
            self.assertFalse((game_root / "Changed.windows.yaml").exists())
            self.assertTrue((game_root / "Stable.windows.yaml").is_file())

    def test_explicit_legacy_bootstrap_rejects_missing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with self.assertRaisesRegex(ReleaseWorkflowError, "legacy bootstrap snapshot"):
                invalidate_republish(
                    repo_root=repo,
                    gamever="14170",
                    source_sha="1" * 40,
                    bindir=repo / "bin",
                    allow_legacy_bootstrap=True,
                )

    def test_explicit_legacy_bootstrap_rejects_snapshot_contract_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = LegacyBootstrapFixture(Path(tmp))
            invalid_document = build_snapshot_document(
                fixture.gamever,
                "sha256:" + "0" * 64,
                {"server/Stable.windows.yaml": {"func_name": "Stable", "func_rva": "0x20"}},
            )
            fixture.snapshot.write_bytes(canonical_snapshot_bytes(invalid_document))
            fixture.git("add", ".")
            fixture.git("commit", "-m", "tamper snapshot contract")

            with self.assertRaisesRegex(ReleaseWorkflowError, "trusted legacy bootstrap snapshot was rejected"):
                invalidate_republish(
                    repo_root=fixture.repo,
                    gamever=fixture.gamever,
                    source_sha=fixture.git("rev-parse", "HEAD"),
                    bindir=fixture.repo / "bin",
                    allow_legacy_bootstrap=True,
                )

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
                        branch=f"gamesymbols/build/{fixture.gamever}/{fixture.build_id}",
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
                        branch=f"gamesymbols/build/{fixture.gamever}/{fixture.build_id}",
                        base_branch="main",
                        default_branch="main",
                        pr_number=42,
                        event_head_sha=fixture.head_sha,
                        merge_sha="4" * 40,
                    )

    def test_stage_build_rejects_the_legacy_output_branch_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            with self.assertRaisesRegex(ReleaseWorkflowError, "invalid generated-output branch"):
                fixture.stage(output_branch=LEGACY_OUTPUT_BRANCH)

    def test_stage_build_rejects_output_branch_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            with self.assertRaisesRegex(ReleaseWorkflowError, "does not match GAMEVER and BUILD_ID"):
                fixture.stage(output_branch=format_output_branch("14171", fixture.build_id))

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

    def test_explicit_abandon_removes_only_matching_unpromoted_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            stage_dir = fixture.finalize_and_index()
            accepted = fixture.root / "persisted" / "bin" / fixture.gamever
            accepted.mkdir(parents=True)
            marker = accepted / "accepted.dll"
            marker.write_bytes(b"accepted")

            result = abandon_pending(
                staging_root=fixture.staging,
                persisted_root=fixture.root / "persisted",
                gamever=fixture.gamever,
                build_id=fixture.build_id,
                pr_number=42,
                event_head_sha=fixture.head_sha,
                confirmation=f"ABANDON {fixture.gamever}/{fixture.build_id}",
                reason="Promotion failed before promote-bin",
            )

            self.assertEqual(fixture.build_id, result["build_id"])
            self.assertFalse(stage_dir.exists())
            self.assertFalse((fixture.staging / "pr-index" / "42.json").exists())
            self.assertEqual(b"accepted", marker.read_bytes())

    def test_explicit_abandon_requires_exact_confirmation_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            stage_dir = fixture.finalize_and_index()
            kwargs = {
                "staging_root": fixture.staging,
                "persisted_root": fixture.root / "persisted",
                "gamever": fixture.gamever,
                "build_id": fixture.build_id,
                "pr_number": 42,
                "event_head_sha": fixture.head_sha,
                "reason": "Promotion failed before promote-bin",
            }

            with self.assertRaisesRegex(ReleaseWorkflowError, "confirmation"):
                abandon_pending(confirmation="ABANDON wrong/build", **kwargs)
            with self.assertRaisesRegex(ReleaseWorkflowError, "build identity"):
                abandon_pending(
                    confirmation=f"ABANDON {fixture.gamever}/999-1",
                    **{**kwargs, "build_id": "999-1"},
                )
            self.assertTrue(stage_dir.exists())

    def test_explicit_abandon_refuses_any_started_promotion_state(self) -> None:
        for marker_name in ("PROMOTION_STARTED", "PROMOTED.json", "PROMOTION_COMPLETE"):
            with self.subTest(marker=marker_name), tempfile.TemporaryDirectory() as tmp:
                fixture = ReleaseFixture(Path(tmp))
                fixture.stage()
                stage_dir = fixture.finalize_and_index()
                (stage_dir / marker_name).write_text("{}\n", encoding="utf-8")

                with self.assertRaisesRegex(ReleaseWorkflowError, "resume instead of abandon"):
                    abandon_pending(
                        staging_root=fixture.staging,
                        persisted_root=fixture.root / "persisted",
                        gamever=fixture.gamever,
                        build_id=fixture.build_id,
                        pr_number=42,
                        event_head_sha=fixture.head_sha,
                        confirmation=f"ABANDON {fixture.gamever}/{fixture.build_id}",
                        reason="Promotion failed before promote-bin",
                    )

    def test_explicit_abandon_refuses_transaction_recovery_paths(self) -> None:
        for suffix in ("incoming", "backup"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                fixture = ReleaseFixture(Path(tmp))
                fixture.stage()
                stage_dir = fixture.finalize_and_index()
                recovery = fixture.root / "persisted" / "bin" / f".{fixture.gamever}.{fixture.build_id}.{suffix}"
                recovery.mkdir(parents=True)

                with self.assertRaisesRegex(ReleaseWorkflowError, "recovery path exists"):
                    abandon_pending(
                        staging_root=fixture.staging,
                        persisted_root=fixture.root / "persisted",
                        gamever=fixture.gamever,
                        build_id=fixture.build_id,
                        pr_number=42,
                        event_head_sha=fixture.head_sha,
                        confirmation=f"ABANDON {fixture.gamever}/{fixture.build_id}",
                        reason="Promotion failed before promote-bin",
                    )
                self.assertTrue(stage_dir.exists())

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
