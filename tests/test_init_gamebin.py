import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SCRIPT = Path(".claude/skills/init-gamebin/scripts/init_gamebin.py")
SPEC = importlib.util.spec_from_file_location("init_gamebin", SCRIPT)
init_gamebin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(init_gamebin)


def completed(command, *, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def response(*, status=200, chunks=(), reason="OK"):
    result = MagicMock()
    result.status_code = status
    result.reason = reason
    result.iter_content.return_value = iter(chunks)
    result.__enter__.return_value = result
    result.__exit__.return_value = False
    return result


class TestInitGamebin(unittest.TestCase):
    def test_script_resolves_its_own_repository_root(self) -> None:
        expected = SCRIPT.resolve().parents[4]
        with patch.object(init_gamebin, "run_command", return_value=completed([], stdout=f"{expected}\n")):
            self.assertEqual(expected, init_gamebin.repository_root())

    def test_skill_metadata_and_operator_contract(self) -> None:
        skill = Path(".claude/skills/init-gamebin/SKILL.md").read_text(encoding="utf-8")
        agent = Path(".claude/skills/init-gamebin/agents/openai.yaml").read_text(encoding="utf-8")
        self.assertNotIn("disable-model-invocation", skill)
        self.assertIn("allow_implicit_invocation: false", agent)
        self.assertIn("需要将已知函数名同步/重命名到idb里?", skill)
        self.assertIn("bin/<GAMEVER>/*/*.id0", skill)
        self.assertIn(
            "uv run ida_analyze_bin.py -gamever <GAMEVER> -debug -rename >> /tmp/bump_idb_output.log 2>&1",
            skill,
        )

    def test_load_versions_preserves_order_and_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "download.yaml"
            path.write_text('downloads:\n  - tag: "14168"\n  - tag: "14169"\n', encoding="utf-8")
            self.assertEqual(["14168", "14169"], init_gamebin.load_versions(path))
            path.write_text('downloads:\n  - tag: "14168"\n  - tag: "14168"\n', encoding="utf-8")
            with self.assertRaisesRegex(init_gamebin.InitGamebinError, "duplicate"):
                init_gamebin.load_versions(path)

    def test_latest_and_exact_versions_must_come_from_download_yaml(self) -> None:
        versions = ["14168", "14168b", "14169"]
        self.assertEqual("14169", init_gamebin.select_version("latest", versions))
        self.assertEqual("14168b", init_gamebin.select_version("14168b", versions))
        with self.assertRaisesRegex(init_gamebin.InitGamebinError, "absent"):
            init_gamebin.select_version("14170", versions)

    def test_download_200_streams_and_404_is_the_only_missing_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "gamebin.7z"
            with patch.object(init_gamebin.requests, "get", return_value=response(chunks=[b"abc", b"def"])):
                self.assertTrue(init_gamebin.download_release_asset("https://example/archive", archive))
            self.assertEqual(b"abcdef", archive.read_bytes())
            archive.unlink()
            with patch.object(init_gamebin.requests, "get", return_value=response(status=404, reason="Not Found")):
                self.assertFalse(init_gamebin.download_release_asset("https://example/missing", archive))
            self.assertFalse(archive.exists())

    def test_download_non_404_http_failure_does_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "gamebin.7z"
            with patch.object(init_gamebin.requests, "get", return_value=response(status=503, reason="Unavailable")):
                with self.assertRaisesRegex(init_gamebin.InitGamebinError, "HTTP 503"):
                    init_gamebin.download_release_asset("https://example/archive", archive)

    def test_merge_archive_bin_copies_missing_and_preserves_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "extract" / "bin" / "14168" / "server"
            source.mkdir(parents=True)
            (source / "server.dll").write_bytes(b"new")
            (source / "server.so").write_bytes(b"linux")
            target = root / "local-bin" / "14168" / "server"
            target.mkdir(parents=True)
            (target / "server.dll").write_bytes(b"existing")

            copied, skipped = init_gamebin.merge_archive_bin(root / "extract", root / "local-bin", "14168")

            self.assertEqual((1, 1), (copied, skipped))
            self.assertEqual(b"existing", (target / "server.dll").read_bytes())
            self.assertEqual(b"linux", (target / "server.so").read_bytes())

    def test_depot_credentials_must_be_paired_and_are_added_together(self) -> None:
        with patch.dict(os.environ, {"STEAM_USERNAME": "user"}, clear=True):
            with self.assertRaisesRegex(init_gamebin.InitGamebinError, "configured together"):
                init_gamebin.depot_download_command("14168")
        with patch.dict(os.environ, {"STEAM_USERNAME": "user", "STEAM_PASSWORD": "secret"}, clear=True):
            command = init_gamebin.depot_download_command("14168")
        self.assertEqual(
            ["-username", "user", "-password", "secret", "-remember-password"],
            command[-5:],
        )

    def test_depot_fallback_uses_workflow_commands_in_order(self) -> None:
        root = Path("repo")
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(init_gamebin, "run_command", return_value=completed([])) as run,
        ):
            init_gamebin.run_depot_fallback(root, "14168")
        self.assertEqual("download_depot.py", run.call_args_list[0].kwargs["label"])
        self.assertEqual("copy_depot_bin.py", run.call_args_list[1].kwargs["label"])
        self.assertIn("-tag", run.call_args_list[0].args[0])
        self.assertIn("all-platform", run.call_args_list[1].args[0])

    def test_checkonly_configuration_error_stops_preparation(self) -> None:
        with patch.object(init_gamebin, "run_command", return_value=completed([], returncode=2)):
            with self.assertRaisesRegex(init_gamebin.InitGamebinError, "configuration or argument"):
                init_gamebin.check_binaries(Path("repo"), "14168")

    def test_prepare_skips_network_when_binaries_are_ready(self) -> None:
        root = Path("repo")
        snapshot = root / "gamesymbols" / "14168.yaml"
        with (
            patch.object(init_gamebin, "load_versions", return_value=["14168"]),
            patch.object(init_gamebin, "require_snapshot", return_value=snapshot),
            patch.object(init_gamebin, "check_binaries", side_effect=[True, True]),
            patch.object(init_gamebin, "download_release_asset") as download,
            patch.object(init_gamebin, "restore_snapshot") as restore,
        ):
            result = init_gamebin.prepare(root, "14168")
        self.assertEqual("existing local binaries", result["source"])
        download.assert_not_called()
        restore.assert_called_once_with(root, "14168", snapshot)

    def test_prepare_404_uses_depot_then_restores_snapshot(self) -> None:
        root = Path("repo")
        snapshot = root / "gamesymbols" / "14168.yaml"
        with (
            patch.object(init_gamebin, "load_versions", return_value=["14168"]),
            patch.object(init_gamebin, "require_snapshot", return_value=snapshot),
            patch.object(init_gamebin, "check_binaries", side_effect=[False, True]),
            patch.object(init_gamebin, "download_release_asset", return_value=False),
            patch.object(init_gamebin, "run_depot_fallback") as fallback,
            patch.object(init_gamebin, "restore_snapshot") as restore,
        ):
            result = init_gamebin.prepare(root, "14168")
        self.assertEqual("Steam depot fallback", result["source"])
        fallback.assert_called_once_with(root, "14168")
        restore.assert_called_once_with(root, "14168", snapshot)

    def test_prepare_stops_before_network_when_snapshot_is_missing(self) -> None:
        root = Path("repo")
        with (
            patch.object(init_gamebin, "load_versions", return_value=["14169"]),
            patch.object(init_gamebin, "require_snapshot", side_effect=init_gamebin.InitGamebinError("missing")),
            patch.object(init_gamebin, "check_binaries") as check,
            patch.object(init_gamebin, "download_release_asset") as download,
        ):
            with self.assertRaisesRegex(init_gamebin.InitGamebinError, "missing"):
                init_gamebin.prepare(root, "14169")
        check.assert_not_called()
        download.assert_not_called()

    def test_restore_runs_without_replace_then_verifies(self) -> None:
        root = Path("repo")
        snapshot = root / "gamesymbols" / "14168.yaml"
        with patch.object(init_gamebin, "run_command", return_value=completed([])) as run:
            init_gamebin.restore_snapshot(root, "14168", snapshot)
        restore_command = run.call_args_list[0].args[0]
        verify_command = run.call_args_list[1].args[0]
        self.assertIn("restore", restore_command)
        self.assertNotIn("-replace", restore_command)
        self.assertIn("verify", verify_command)


if __name__ == "__main__":
    unittest.main()
