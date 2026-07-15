import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_workflow_lib.errors import ReleaseWorkflowError
from release_workflow_lib.hashing import (
    canonical_json_bytes,
    file_inventory,
    inventory_sha256,
    reject_reparse_points,
    validate_output_paths,
)
from release_workflow_lib.manifests import load_tracked_manifest
from release_workflow_lib.promotion import finalize_promotion, promote_bin
from release_workflow_lib.staging import (
    finalize_stage,
    load_indexed_pending,
    stage_build,
    write_pr_index,
)


class ReleaseFixture:
    gamever = "14170"
    build_id = "123456789-1"
    source_sha = "1" * 40
    head_sha = "2" * 40

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.staging = root / "persisted" / "release-staging"
        self.bin_source = self.repo / "bin" / self.gamever
        self.candidate = root / "candidate.yaml"
        (self.repo / "gamesymbols").mkdir(parents=True)
        (self.repo / "dist" / "nested").mkdir(parents=True)
        self.bin_source.mkdir(parents=True)
        snapshot = b"schema_version: 1\ngame_version: '14170'\nfiles: {}\n"
        (self.repo / "gamesymbols" / f"{self.gamever}.yaml").write_bytes(snapshot)
        self.candidate.write_bytes(snapshot)
        (self.repo / "dist" / "nested" / "gamedata.txt").write_text("gamedata\n", encoding="utf-8")
        (self.bin_source / "client.dll").write_bytes(b"dll")
        (self.bin_source / "client.yaml").write_text("value: 1\n", encoding="utf-8")

    def stage(self) -> dict:
        return stage_build(
            repo_root=self.repo,
            staging_root=self.staging,
            bin_source=self.bin_source,
            candidate=self.candidate,
            repository="HLND2T/CS2_VibeSignatures",
            output_branch=f"gamesymbols/{self.gamever}/build-{self.build_id}",
            gamever=self.gamever,
            mode="new",
            build_id=self.build_id,
            source_sha=self.source_sha,
            workflow_run_url="https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/123456789",
        )

    def finalize_and_index(self, pr_number: int = 42) -> Path:
        finalize_stage(
            repo_root=self.repo,
            staging_root=self.staging,
            gamever=self.gamever,
            build_id=self.build_id,
            pr_head_sha=self.head_sha,
        )
        write_pr_index(
            staging_root=self.staging,
            pr_number=pr_number,
            gamever=self.gamever,
            build_id=self.build_id,
            pr_head_sha=self.head_sha,
        )
        return self.staging / self.gamever / self.build_id


class TestReleaseWorkflow(unittest.TestCase):
    def test_stage_writes_canonical_tracked_and_private_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            pending = fixture.stage()
            tracked_path = fixture.repo / "release-manifests" / f"{fixture.gamever}.json"
            tracked = load_tracked_manifest(tracked_path)

            self.assertEqual(fixture.source_sha, tracked["source_sha"])
            self.assertEqual(inventory_sha256(pending["bin_files"]), tracked["bin_manifest_sha256"])
            self.assertEqual(canonical_json_bytes(tracked), tracked_path.read_bytes())
            self.assertNotIn("timestamp", tracked)
            self.assertNotIn(str(fixture.root), tracked_path.read_text(encoding="utf-8"))

    def test_finalize_binds_ready_state_and_pr_index_to_head_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            stage_dir = fixture.finalize_and_index()

            index, pending, loaded_dir = load_indexed_pending(fixture.staging, 42, fixture.head_sha)

            self.assertEqual(stage_dir, loaded_dir)
            self.assertEqual(fixture.head_sha, pending["pr_head_sha"])
            self.assertEqual(fixture.build_id, index["build_id"])
            self.assertTrue((stage_dir / "READY").is_file())

    def test_event_head_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            fixture.finalize_and_index()

            with self.assertRaisesRegex(ReleaseWorkflowError, "event identity"):
                load_indexed_pending(fixture.staging, 42, "3" * 40)

    def test_tampered_tracked_output_is_rejected_when_finalizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            (fixture.repo / "dist" / "nested" / "gamedata.txt").write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(ReleaseWorkflowError, "tracked output manifest hash mismatch"):
                finalize_stage(
                    repo_root=fixture.repo,
                    staging_root=fixture.staging,
                    gamever=fixture.gamever,
                    build_id=fixture.build_id,
                    pr_head_sha=fixture.head_sha,
                )

    def test_disallowed_generated_output_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReleaseWorkflowError, "disallowed paths"):
            validate_output_paths(
                ["gamesymbols/14170.yaml", "release-manifests/14170.json", "config.yaml"],
                "14170",
            )

    def test_reparse_point_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("data", encoding="utf-8")
            with patch("release_workflow_lib.hashing._is_reparse_point", return_value=True):
                with self.assertRaisesRegex(ReleaseWorkflowError, "reparse points"):
                    reject_reparse_points(root)

    def test_promote_bin_swaps_verified_directory_and_finalizes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            stage_dir = fixture.finalize_and_index()
            accepted = fixture.root / "persisted" / "bin" / fixture.gamever
            accepted.mkdir(parents=True)
            (accepted / "old.dll").write_bytes(b"old")

            state = promote_bin(
                persisted_root=fixture.root / "persisted",
                stage_dir=stage_dir,
                gamever=fixture.gamever,
                build_id=fixture.build_id,
            )

            self.assertEqual(file_inventory(stage_dir / "bin" / fixture.gamever), file_inventory(accepted))
            self.assertTrue(Path(state["backup"]).is_dir())
            finalize_promotion(
                staging_root=fixture.staging,
                pr_number=42,
                event_head_sha=fixture.head_sha,
                output_merge_sha="4" * 40,
            )
            self.assertFalse(Path(state["backup"]).exists())
            self.assertTrue((stage_dir / "PROMOTION_COMPLETE").is_file())
            self.assertFalse((fixture.staging / "pr-index" / "42.json").exists())

    def test_promote_bin_is_idempotent_after_successful_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReleaseFixture(Path(tmp))
            fixture.stage()
            stage_dir = fixture.finalize_and_index()

            kwargs = {
                "persisted_root": fixture.root / "persisted",
                "stage_dir": stage_dir,
                "gamever": fixture.gamever,
                "build_id": fixture.build_id,
            }
            first = promote_bin(**kwargs)
            second = promote_bin(**kwargs)

            self.assertEqual(first["accepted"], second["accepted"])
            self.assertEqual(first["backup"], second["backup"])

if __name__ == "__main__":
    unittest.main()
