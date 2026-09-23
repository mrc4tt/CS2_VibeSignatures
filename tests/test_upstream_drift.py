import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import check_upstream_drift


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestUpstreamDrift(unittest.TestCase):
    """The three states are read off a real repository, not a mocked git."""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.repo = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

        _git(self.repo, "init", "--quiet", "-b", "main")
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "test")

        # The upstream state: two skills and two artifacts.
        _write(self.repo / ".claude/skills/find-kept/SKILL.md", "name: find-kept\n")
        _write(self.repo / ".claude/skills/find-dropped/SKILL.md", "name: find-dropped\n")
        _write(self.repo / "bin_artifacts/1/server/Kept.linux.yaml", "func_name: Kept\n")
        _write(self.repo / "bin_artifacts/1/server/Gone.linux.yaml", "func_name: Gone\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "--quiet", "-m", "upstream")
        _git(self.repo, "branch", "upstream-main")

    def _report(self):
        return check_upstream_drift.build_report("upstream-main", repo_root=str(self.repo))

    def test_unchanged_tree_reports_nothing(self) -> None:
        report = self._report()

        self.assertEqual(0, report["missing_total"])
        for section in report["sections"].values():
            self.assertEqual([], section["missing"])
            self.assertEqual([], section["modified"])
            self.assertEqual([], section["fork_only"])

    def test_file_removed_here_is_reported_as_missing(self) -> None:
        (self.repo / ".claude/skills/find-dropped/SKILL.md").unlink()
        (self.repo / "bin_artifacts/1/server/Gone.linux.yaml").unlink()

        report = self._report()

        self.assertEqual(
            [".claude/skills/find-dropped/SKILL.md"],
            report["sections"]["skills"]["missing"],
        )
        self.assertEqual(
            ["bin_artifacts/1/server/Gone.linux.yaml"],
            report["sections"]["yaml"]["missing"],
        )
        self.assertEqual(2, report["missing_total"])

    def test_edited_and_added_files_are_separated(self) -> None:
        _write(self.repo / "bin_artifacts/1/server/Kept.linux.yaml", "func_name: Kept\nfunc_va: '0x1'\n")
        _write(self.repo / "bin_artifacts/1/server/ForkOwned.linux.yaml", "func_name: ForkOwned\n")
        _write(
            self.repo / ".claude/skills/find-generated/SKILL.md",
            "Agent fallback for find-generated (auto-generated, category: func).\n",
        )
        _write(self.repo / ".claude/skills/find-by-hand/SKILL.md", "name: find-by-hand\n")
        _git(self.repo, "add", "-A")

        report = self._report()
        skills = report["sections"]["skills"]
        yamls = report["sections"]["yaml"]

        self.assertEqual(0, report["missing_total"])
        self.assertEqual(["bin_artifacts/1/server/Kept.linux.yaml"], yamls["modified"])
        self.assertEqual(["bin_artifacts/1/server/ForkOwned.linux.yaml"], yamls["fork_only"])
        self.assertEqual([".claude/skills/find-generated/SKILL.md"], skills["generated"])
        self.assertEqual([".claude/skills/find-by-hand/SKILL.md"], skills["handwritten"])

    def test_untracked_yaml_is_listed_separately(self) -> None:
        """A new gamever's artifacts are untracked, and git diff cannot see them."""
        _write(self.repo / "bin_artifacts/2/server/New.linux.yaml", "func_name: New\n")

        yamls = self._report()["sections"]["yaml"]

        self.assertEqual([], yamls["fork_only"])
        self.assertEqual(["bin_artifacts/2/server/New.linux.yaml"], yamls["untracked"])

    def test_sections_can_be_requested_individually(self) -> None:
        report = check_upstream_drift.build_report(
            "upstream-main", repo_root=str(self.repo), want_yaml=False
        )

        self.assertEqual(["skills"], list(report["sections"]))

    def test_unknown_ref_raises(self) -> None:
        with self.assertRaises(check_upstream_drift.GitError):
            check_upstream_drift.build_report("no-such-ref", repo_root=str(self.repo))


class TestGroupByDirectory(unittest.TestCase):
    def test_counts_by_first_two_components_most_populated_first(self) -> None:
        grouped = check_upstream_drift.group_by_directory(
            [
                "bin_artifacts/14181/server/A.linux.yaml",
                "bin_artifacts/14181/engine/B.linux.yaml",
                "configs/14181.yaml",
                "download.yaml",
            ]
        )

        self.assertEqual(
            [("bin_artifacts/14181", 2), ("configs/14181.yaml", 1), ("download.yaml", 1)],
            grouped,
        )


if __name__ == "__main__":
    unittest.main()
