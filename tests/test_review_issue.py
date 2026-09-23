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
    """One bot comment per issue, always the last: posted anew, old copy deleted."""

    def test_repost_at_the_bottom_then_delete_the_old_copy(self):
        calls = []

        def fake_api(method, path, payload=None):
            calls.append((method, path, payload and payload["body"]))
            return {"id": 8} if method == "POST" else None

        with mock.patch.object(R, "gh_api", side_effect=fake_api):
            new_id = R.write_bot_log("2", 7, ["re @a:\n\n- first\n", "re @b:\n\n- second\n"])
        self.assertEqual(new_id, 8)
        self.assertEqual([c[:2] for c in calls], [("POST", "repos/{repo}/issues/2/comments"),
                                                  ("DELETE", "repos/{repo}/issues/comments/7")])
        body = calls[0][2]
        self.assertTrue(body.startswith(R.BOT_MARK))
        self.assertLess(body.index("- first"), body.index("- second"))   # newest at the bottom
        log_id, sections = R.bot_log("2", [{"id": 8, "body": body}])
        self.assertEqual((log_id, len(sections)), (8, 2))

    def test_oldest_results_are_dropped_when_too_long(self):
        posted = []
        with mock.patch.object(R, "gh_api", side_effect=lambda m, p, payload=None: posted.append(payload and payload["body"]) or {"id": 1}), \
                mock.patch.object(R, "MAX_BODY", 200):
            R.write_bot_log("2", None, ["old " * 40, "new " * 10])
        self.assertIn("new", posted[0])
        self.assertNotIn("old", posted[0])

class EditTests(unittest.TestCase):
    def test_markers_round_trip(self):
        key = R.line_key("confirm", "A_b", None, ["0x10"])
        self.assertEqual(key, R.line_key("confirm", "A_b", None, ["0x10"]))
        self.assertNotEqual(key, R.line_key("confirm", "A_b", None, ["0x20"]))
        sections = [f"re @x:\n\n- ok\n<!-- done:42:{key},abc123 -->\n"]
        self.assertEqual(R.done_lines(sections), {42: {key, "abc123"}})

    def test_edited_comment_acts_on_changed_lines_only(self):
        old = R.line_key("confirm", "A_b", None, ["0x10"])
        reject = R.line_key("reject", "C_d", None, ["inlined"])
        log = {"id": 9, "body": R.BOT_HEADER + f"\nre @x:\n\n- A_b refused\n<!-- done:5:{old},{reject} -->\n"}
        edited = {"id": 5, "author_association": "OWNER", "login": "x", "url": "u",
                  "body": "/confirm A_b 0x20\n/reject C_d inlined"}
        built = []

        def fake_build(gamever, row, args, runner=None):
            built.append(args)
            return R.REPO / "A_b.windows.yaml", "written and validated."

        rows = [{"symbol": "A_b", "platform": "windows", "module": "server", "candidate": None, "path": "p"},
                {"symbol": "C_d", "platform": "windows", "module": "server", "candidate": None, "path": "p"}]
        posted, reactions = [], []
        with mock.patch.object(R, "find_issue", return_value={"number": 2}), \
                mock.patch.object(R, "issue_comments", return_value=[edited, log]), \
                mock.patch.object(R, "read_todo", return_value=rows), \
                mock.patch.object(R, "build_artifact", side_effect=fake_build), \
                mock.patch.object(R, "write_bot_log", side_effect=lambda n, i, s: posted.append(s) or 10), \
                mock.patch.object(R, "replace_reaction", side_effect=lambda c, r, m: reactions.append((c, r))), \
                mock.patch.object(R, "react") as plain_react:
            R._apply_issue("14182", "windows", "me", False, [])
        self.assertEqual(built, [["-kind", "func", "-ea", "0x20"]])      # only the changed line
        self.assertEqual(reactions, [(5, "+1")])                         # verdict replaced
        plain_react.assert_not_called()
        self.assertIn("edited: 1 new or changed line(s)", posted[-1][-1])


class NewRoundTests(unittest.TestCase):
    def test_closed_issue_is_not_reopened_a_new_one_links_it(self):
        calls = []

        def fake_api(method, path, payload=None):
            calls.append((method, path, payload))
            if method == "GET" and "state=open" in path:
                return []
            if method == "GET" and "state=closed" in path:
                return [{"number": 2, "title": R.title_for("14182", "windows"), "state": "closed"}]
            if method == "POST" and path.endswith("/issues"):
                return {"html_url": "https://github.com/x/y/issues/3", "number": 3}
            return None

        rows = [{"module": "server", "platform": "windows", "symbol": "A_b", "flags": [], "category": "func",
                 "candidate": None, "score": None, "why": "no candidate"}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(R, "REPO", Path(tmp)), \
                mock.patch.object(R, "gh_api", side_effect=fake_api):
            R.publish("14182", "windows", rows=rows)
            self.assertEqual(R._remembered_path("14182", "windows").read_text().strip(), "3")
        created = [c for c in calls if c[0] == "POST" and c[1].endswith("/issues")]
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0][2]["body"].startswith("Previous round: #2"))
        self.assertFalse([c for c in calls if c[0] == "PATCH"])   # #2 stays closed

    def test_a_stale_list_entry_is_checked_directly(self):
        # the list still says open; the issue itself says closed
        def fake_api(method, path, payload=None):
            if "state=open" in path:
                return [{"number": 2, "title": R.title_for("14182", "windows"), "state": "open"}]
            if path.endswith("/issues/2"):
                return {"state": "closed"}
            return None

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(R, "REPO", Path(tmp)), \
                mock.patch.object(R, "gh_api", side_effect=fake_api):
            self.assertIsNone(R.find_issue("14182", "windows"))

    def test_remembered_issue_is_found_even_when_the_list_misses_it(self):
        def fake_api(method, path, payload=None):
            if "state=open" in path:
                return []                                  # the list has not caught up yet
            if path.endswith("/issues/3"):
                return {"state": "open", "title": R.title_for("14182", "windows")}
            return None

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(R, "REPO", Path(tmp)), \
                mock.patch.object(R, "gh_api", side_effect=fake_api):
            R.remember_issue("14182", "windows", 3)
            self.assertEqual(R.find_issue("14182", "windows")["number"], 3)

    def _unused(self):
        calls = []

        def fake_api(method, path, payload=None):
            calls.append((method, path, payload))
            return None

        rows = [{"module": "server", "platform": "windows", "symbol": "A_b", "flags": [], "category": "func",
                 "candidate": None, "score": None, "why": "no candidate"}]
        with mock.patch.object(R, "gh_api", side_effect=fake_api):
            R.publish("14182", "windows", rows=rows)
        created = [c for c in calls if c[0] == "POST" and c[1].endswith("/issues")]
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0][2]["body"].startswith("Previous round: #2"))
        self.assertFalse([c for c in calls if c[0] == "PATCH"])   # #2 stays closed
