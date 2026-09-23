"""review_issue.py: the list -> issue body, and review comments -> checked artifacts."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import review_issue as R

TODO = (
    "# header\n"
    "CCSCustomHudLayout_SetHasClassForPlayer   find-CCSCustomHudLayout_SetHasClassForPlayer   "
    "agent failed | func | best 0x1808d2750 (0.58) | weak evidence only via neighbour score 0.58\n"
    "CBaseFilter_InputTestActivator   find-CBaseFilter_InputTestActivator   func | no candidate\n"
)


class ListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name) / "manual_todo" / "14182"
        folder.mkdir(parents=True)
        (folder / "server.windows.txt").write_text(TODO)
        (folder / "server.linux.txt").write_text(
            "CBaseFilter_InputTestActivator   find-CBaseFilter_InputTestActivator   func | no candidate\n")
        self.rows = R.read_todo("14182", root=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows_carry_candidate_and_reason(self):
        row = next(r for r in self.rows if r["symbol"].startswith("CCSCustomHud"))
        self.assertEqual((row["module"], row["platform"], row["category"]), ("server", "windows", "func"))
        self.assertEqual((row["candidate"], row["score"]), ("0x1808d2750", "0.58"))
        self.assertEqual(row["flags"], ["agent failed"])

    def test_one_issue_per_platform(self):
        windows = R.read_todo("14182", root=self.tmp.name, platform="windows")
        linux = R.read_todo("14182", root=self.tmp.name, platform="linux")
        self.assertEqual((len(windows), len(linux)), (2, 1))
        body = R.render_body("14182", "windows", windows)
        self.assertIn("**windows** run (server.dll", body)
        self.assertIn("### server - 2", body)
        self.assertIn("`0x1808d2750` (0.58)", body)
        self.assertIn("/confirm <Symbol> 0x<address>", body)
        self.assertNotEqual(R.title_for("14182", "linux"), R.title_for("14182", "windows"))

    def test_empty_list_says_so(self):
        self.assertIn("Nothing left", R.render_body("14182", "linux", []))

    def test_a_symbol_open_on_both_platforms_needs_the_platform(self):
        row, problem = R.target_row(self.rows, "CBaseFilter_InputTestActivator", None)
        self.assertIsNone(row)
        self.assertIn("add the platform", problem)
        row, problem = R.target_row(self.rows, "CBaseFilter_InputTestActivator", "linux")
        self.assertEqual(row["platform"], "linux")


class CommandTests(unittest.TestCase):
    def test_parse_commands(self):
        body = ("Looked at it.\n/confirm A_b windows 0x1808d2750\n"
                "/confirm C_d vfunc CBaseTrigger 151\n/reject E_f linux inlined into G\n")
        self.assertEqual(R.parse_commands(body), [
            ("confirm", "A_b", "windows", ["0x1808d2750"]),
            ("confirm", "C_d", None, ["vfunc", "CBaseTrigger", "151"]),
            ("reject", "E_f", "linux", ["inlined", "into", "G"]),
        ])

    def test_rule_args(self):
        self.assertEqual(R.rule_args(["0x10"])[0], ["-kind", "func", "-ea", "0x10"])
        self.assertEqual(R.rule_args(["vfunc", "C", "3"])[0], ["-kind", "vfunc", "-class", "C", "-index", "3"])
        self.assertEqual(R.rule_args(["gv", "0x20"])[0], ["-kind", "gv", "-ea", "0x20"])
        self.assertIsNone(R.rule_args(["somewhere"])[0])


class BuildTests(unittest.TestCase):
    """A confirm goes through emit_artifact + its validation, then one-address-one-name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "bin_artifacts" / "14182" / "server").mkdir(parents=True)
        self.row = {"symbol": "X_y", "module": "server", "platform": "windows", "candidate": "0x100"}
        self.patch = mock.patch.object(R, "REPO", self.repo)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _runner(self, returncode=0, va="0x100"):
        def run(command, **_kwargs):
            outdir = Path(command[command.index("-outdir") + 1])
            if returncode == 0:
                (outdir / "X_y.windows.yaml").write_text(f"func_name: X_y\nfunc_va: '{va}'\nfunc_sig: 48 89\n")
            return subprocess.CompletedProcess(command, returncode, stdout="[emit] done\n", stderr="")
        return run

    def test_validated_artifact_is_copied_in(self):
        path, message = R.build_artifact("14182", self.row, ["-kind", "func", "-ea", "0x100"], runner=self._runner())
        self.assertTrue(path.is_file())
        self.assertIn("matches the run's best candidate", message)

    def test_refused_by_the_checks(self):
        path, message = R.build_artifact("14182", self.row, ["-kind", "func", "-ea", "0x100"], runner=self._runner(2))
        self.assertIsNone(path)
        self.assertIn("refused", message)

    def test_address_already_owned_by_another_symbol(self):
        (self.repo / "bin_artifacts" / "14182" / "server" / "Other_z.windows.yaml").write_text("func_va: '0x100'\n")
        path, message = R.build_artifact("14182", self.row, ["-kind", "func", "-ea", "0x100"], runner=self._runner())
        self.assertIsNone(path)
        self.assertIn("already `Other_z`", message)
        self.assertFalse((self.repo / "bin_artifacts" / "14182" / "server" / "X_y.windows.yaml").exists())


if __name__ == "__main__":
    unittest.main()


class RepoPinTests(unittest.TestCase):
    """Every gh call targets origin, never gh's default (the upstream remote here)."""

    def test_issue_and_api_calls_are_pinned_to_origin(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch.dict(os.environ, {"CS2VIBE_REVIEW_REPO": "me/fork"}), \
                mock.patch.object(R.subprocess, "run", side_effect=fake_run):
            R.gh("issue", "list", "--label", "x")
            R.gh("api", "repos/{owner}/{repo}/issues/1/comments")
        self.assertEqual(calls[0][:5], ["gh", "issue", "list", "-R", "me/fork"])
        self.assertEqual(calls[1], ["gh", "api", "repos/me/fork/issues/1/comments"])

    def test_origin_url_forms(self):
        for url in ("git@github.com:mrc4tt/CS2_VibeSignatures.git", "https://github.com/mrc4tt/CS2_VibeSignatures"):
            done = subprocess.CompletedProcess([], 0, stdout=url + "\n", stderr="")
            with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(R.subprocess, "run", return_value=done):
                os.environ.pop("CS2VIBE_REVIEW_REPO", None)
                self.assertEqual(R.repo_slug(), "mrc4tt/CS2_VibeSignatures")


class LatestTests(unittest.TestCase):
    def test_latest_is_the_newest_manual_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in ("14181", "14182", "14178b"):
                (Path(tmp) / "manual_todo" / version).mkdir(parents=True)
            with mock.patch.object(R, "REPO", Path(tmp)):
                self.assertEqual(R.resolve_gamever("latest"), "14182")
                self.assertEqual(R.resolve_gamever("14180"), "14180")

    def test_latest_without_lists_is_none(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(R, "REPO", Path(tmp)):
            self.assertIsNone(R.resolve_gamever("latest"))


class ReactionTests(unittest.TestCase):
    def test_reactions(self):
        self.assertEqual(R.reaction_for(1, 0, 0), "+1")
        self.assertEqual(R.reaction_for(0, 1, 0), "-1")
        self.assertEqual(R.reaction_for(0, 1, 1), "eyes")   # live test 3: a reject plus a refusal
        self.assertEqual(R.reaction_for(1, 1, 0), "eyes")
        self.assertEqual(R.reaction_for(0, 0, 1), "eyes")


class CommitDespiteFailureTests(unittest.TestCase):
    def test_written_artifacts_are_committed_when_a_later_step_fails(self):
        def boom(gamever, platform, me, dry_run, written):
            written.append(R.REPO / "bin_artifacts" / "x.yaml")
            raise RuntimeError("HTTP 401")

        with mock.patch.object(R, "my_login", return_value="me"), \
                mock.patch.object(R, "_apply_issue", side_effect=boom), \
                mock.patch.object(R, "find_issue", return_value=None), \
                mock.patch.object(R, "read_todo", return_value=[]), \
                mock.patch.object(R.subprocess, "run") as run, \
                mock.patch.dict("sys.modules", {"ida_analyze_bin": mock.Mock()}):
            with self.assertRaises(RuntimeError):
                R.apply("14182", commit=True, platform="windows")
        commands = [c.args[0][:2] for c in run.call_args_list]
        self.assertIn(["git", "commit"], commands)
        self.assertIn(["git", "push"], commands)


class EnvTests(unittest.TestCase):
    def test_gh_ignores_a_token_loaded_later_from_dotenv(self):
        seen = {}

        def fake_run(command, **kwargs):
            seen["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch.dict(os.environ, {"CS2VIBE_REVIEW_REPO": "me/fork", "GITHUB_TOKEN": "stale"}), \
                mock.patch.object(R, "_GH_ENV", {"PATH": "/usr/bin"}), \
                mock.patch.object(R.subprocess, "run", side_effect=fake_run):
            R.gh("api", "user")
        self.assertNotIn("GITHUB_TOKEN", seen["env"])


class BotLogTests(unittest.TestCase):
    """One bot comment per issue, edited in place, newest result first."""

    def test_log_round_trip_and_newest_first(self):
        posted = []

        def fake_api(method, path, payload=None):
            posted.append((method, path, payload["body"]))

        with mock.patch.object(R, "gh_api", side_effect=fake_api):
            R.write_bot_log("2", None, ["re @a:\n\n- first\n"])
            first = posted[-1][2]
            comment = {"id": 7, "body": first}
            log_id, sections = R.bot_log("2", [{"id": 1, "body": "/confirm X 0x1"}, comment])
            self.assertEqual((log_id, len(sections)), (7, 1))
            R.write_bot_log("2", log_id, ["re @b:\n\n- second\n"] + sections)
        self.assertEqual(posted[0][0], "POST")
        self.assertEqual(posted[1][:2], ("PATCH", "repos/{repo}/issues/comments/7"))
        body = posted[1][2]
        self.assertTrue(body.startswith(R.BOT_MARK))
        self.assertLess(body.index("- second"), body.index("- first"))

    def test_oldest_results_are_dropped_when_too_long(self):
        posted = []
        with mock.patch.object(R, "gh_api", side_effect=lambda m, p, payload=None: posted.append(payload["body"])), \
                mock.patch.object(R, "MAX_BODY", 200):
            R.write_bot_log("2", 7, ["new " * 10, "old " * 40])
        self.assertIn("new", posted[0])
        self.assertNotIn("old", posted[0])
