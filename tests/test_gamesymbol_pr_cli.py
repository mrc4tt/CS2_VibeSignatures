import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gamesymbol_snapshot_lib.pr_cli import _parse_changed_paths, _revision_sources


class TestGitChangeCollection(unittest.TestCase):
    def test_parse_name_status_preserves_status_rename_sides_and_spaces(self) -> None:
        raw = (
            b"A\0new file.py\0"
            b"M\0modified.py\0"
            b"D\0deleted.py\0"
            b"R087\0old name.yaml\0new name.yaml\0"
            b"C100\0source.py\0copied file.py\0"
        )

        changes = _parse_changed_paths(raw)

        self.assertEqual(
            [
                ("A", None, "new file.py"),
                ("M", "modified.py", "modified.py"),
                ("D", "deleted.py", None),
                ("R", "old name.yaml", "new name.yaml"),
                ("C", "source.py", "copied file.py"),
            ],
            [(change.status, change.old_path, change.new_path) for change in changes],
        )

    def test_revision_sources_reads_base_and_head_without_checkout_mutation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            script = root / "ida_preprocessor_scripts" / "find-target.py"
            script.parent.mkdir()
            script.write_bytes(b"VALUE = 1\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            script.write_bytes(b"VALUE = 2\n")
            subprocess.run(["git", "commit", "-qam", "head"], cwd=root, check=True)
            head_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()

            base_sources = _revision_sources(base_ref, root)
            head_sources = _revision_sources(head_ref, root)
            current_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()

        path = "ida_preprocessor_scripts/find-target.py"
        self.assertEqual("VALUE = 1\n", base_sources[path])
        self.assertEqual("VALUE = 2\n", head_sources[path])
        self.assertEqual(head_ref, current_ref)


if __name__ == "__main__":
    unittest.main()
