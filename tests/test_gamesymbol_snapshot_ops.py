import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from gamesymbol_snapshot_lib.errors import SnapshotMismatchError, SnapshotSchemaError
from gamesymbol_snapshot_lib.operations import pack_snapshot, restore_snapshot, verify_snapshot
from gamesymbol_snapshot_lib.snapshot_cli import main as snapshot_main
from tests.gamesymbol_snapshot_test_support import module, skill, write_config, write_yaml


class SnapshotWorkspace:
    def __init__(self, root: Path):
        self.root = root
        self.bindir = root / "bin"
        self.config = root / "config.yaml"
        self.snapshot = root / "gamesymbols" / "1.yaml"
        write_config(
            self.config,
            [
                module(
                    "server",
                    [skill("find-a", ["A.{platform}.yaml"], optional_output=["Optional.{platform}.yaml"])],
                )
            ],
        )

    def write_required(self) -> None:
        write_yaml(self.bindir / "1/server/A.windows.yaml", {"z": 2, "a": {"y": 1, "x": 0}})
        write_yaml(self.bindir / "1/server/A.linux.yaml", {"func_name": "A", "func_size": 1})

    def pack(self):
        return pack_snapshot("1", self.bindir, self.config, self.snapshot)


class TestPack(unittest.TestCase):
    def test_pack_is_deterministic_and_uses_full_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            first = workspace.pack()
            second = workspace.pack()
            data = yaml.safe_load(first)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertNotIn(b"\r\n", first)
        self.assertEqual("1", data["game_version"])
        self.assertEqual(2, data["file_count"])
        self.assertEqual(
            ["server/A.linux.yaml", "server/A.windows.yaml"],
            list(data["files"]),
        )
        self.assertEqual(["a", "z"], list(data["files"]["server/A.windows.yaml"]))

    def test_existing_optional_output_is_included(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            write_yaml(workspace.bindir / "1/server/Optional.windows.yaml", {"optional": True})

            data = yaml.safe_load(workspace.pack())

        self.assertIn("server/Optional.windows.yaml", data["files"])

    def test_pack_rejects_missing_required_and_undeclared_without_overwriting(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.snapshot.parent.mkdir(parents=True)
            workspace.snapshot.write_bytes(b"existing\n")
            with self.assertRaises(SnapshotMismatchError):
                workspace.pack()
            self.assertEqual(b"existing\n", workspace.snapshot.read_bytes())

            workspace.write_required()
            write_yaml(workspace.bindir / "1/server/Stale.windows.yaml", {"stale": True})
            with self.assertRaises(SnapshotMismatchError):
                workspace.pack()
            self.assertEqual(b"existing\n", workspace.snapshot.read_bytes())

    def test_pack_rejects_top_level_non_mapping_yaml(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            (workspace.bindir / "1/server/A.windows.yaml").write_text("- invalid\n", encoding="utf-8")

            with self.assertRaisesRegex(SnapshotMismatchError, "top level must be a mapping"):
                workspace.pack()


class TestRestoreAndVerify(unittest.TestCase):
    def test_replace_restores_round_trip_and_preserves_non_yaml_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = SnapshotWorkspace(root)
            workspace.write_required()
            expected = workspace.pack()
            game_root = workspace.bindir / "1"
            (game_root / "server/server.dll").write_bytes(b"dll")
            (game_root / "server/server.i64").write_bytes(b"ida")
            write_yaml(game_root / "server/Stale.yaml", {"stale": True})

            restore_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot, replace=True)
            verified = verify_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot)

            self.assertEqual(expected, verified)
            self.assertFalse((game_root / "server/Stale.yaml").exists())
            self.assertEqual(b"dll", (game_root / "server/server.dll").read_bytes())
            self.assertEqual(b"ida", (game_root / "server/server.i64").read_bytes())

    def test_default_restore_rejects_semantically_different_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            workspace.pack()
            write_yaml(workspace.bindir / "1/server/A.windows.yaml", {"different": True})

            with self.assertRaises(SnapshotMismatchError):
                restore_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot)

    def test_verify_reports_modified_payload_and_noncanonical_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            canonical = workspace.pack()
            write_yaml(workspace.bindir / "1/server/A.windows.yaml", {"func_name": "changed"})
            with self.assertRaisesRegex(SnapshotMismatchError, "Modified"):
                verify_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot)

            workspace.snapshot.write_bytes(b"\n" + canonical)
            with self.assertRaisesRegex(SnapshotMismatchError, "canonical"):
                verify_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot)

    def test_restore_rejects_snapshot_path_traversal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            workspace.pack()
            data = yaml.safe_load(workspace.snapshot.read_text(encoding="utf-8"))
            data["files"]["../outside.yaml"] = data["files"].pop("server/A.windows.yaml")
            data["file_count"] = len(data["files"])
            workspace.snapshot.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

            with self.assertRaises(SnapshotSchemaError):
                restore_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot, replace=True)
            self.assertFalse((workspace.root / "outside.yaml").exists())

    def test_verify_rejects_config_digest_mismatch_and_empty_path_component(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            workspace.write_required()
            workspace.pack()
            changed_config = workspace.root / "changed.yaml"
            write_config(
                changed_config,
                [module("server", [skill("find-b", ["A.{platform}.yaml"])])],
            )
            with self.assertRaisesRegex(SnapshotMismatchError, "config digest mismatch"):
                verify_snapshot("1", workspace.bindir, changed_config, workspace.snapshot)

            data = yaml.safe_load(workspace.snapshot.read_text(encoding="utf-8"))
            data["files"]["server//Bad.yaml"] = {"bad": True}
            data["file_count"] = len(data["files"])
            workspace.snapshot.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            with self.assertRaises(SnapshotSchemaError):
                restore_snapshot("1", workspace.bindir, workspace.config, workspace.snapshot, replace=True)

    def test_cli_returns_mismatch_and_schema_exit_codes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = SnapshotWorkspace(Path(temp_dir))
            snapshot_args = [
                "verify",
                "-gamever",
                "1",
                "-bindir",
                str(workspace.bindir),
                "-configyaml",
                str(workspace.config),
                "-snapshot",
                str(workspace.snapshot),
            ]
            self.assertEqual(1, snapshot_main(snapshot_args))

            workspace.snapshot.parent.mkdir(parents=True)
            workspace.snapshot.write_text("schema_version: 999\n", encoding="utf-8")
            self.assertEqual(2, snapshot_main(snapshot_args))


if __name__ == "__main__":
    unittest.main()
