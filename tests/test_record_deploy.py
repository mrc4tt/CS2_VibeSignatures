"""record_deploy.py tells a consumer which commit carries a build's deployed gamedata.

The fshost panel installs whatever commit the record names on live servers, so the
record must only say "deployed" when every target is committed and pushed, and must
name the newest commit on the path even when this build changed nothing there.
"""

import datetime
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import check_deploy_drift
import record_deploy


def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True)


def _out(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True).stdout.strip()


class WebUrl(unittest.TestCase):
    def test_normalises_every_remote_spelling(self):
        for remote in (
            "git@github.com:mrc4tt/CounterStrikeSharp.git",
            "ssh://git@github.com/mrc4tt/CounterStrikeSharp.git",
            "https://github.com/mrc4tt/CounterStrikeSharp.git",
            "https://github.com/mrc4tt/CounterStrikeSharp",
            "https://token@github.com/mrc4tt/CounterStrikeSharp/",
        ):
            self.assertEqual(record_deploy.web_url(remote), "https://github.com/mrc4tt/CounterStrikeSharp", remote)

    def test_keeps_a_self_hosted_forge(self):
        self.assertEqual(
            record_deploy.web_url("git@git.miksen.me:mikkel/weaponpaints.git"),
            "https://git.miksen.me/mikkel/weaponpaints",
        )


class DescribeTarget(unittest.TestCase):
    """Against a real clone with a real upstream, because "pushed" is a git question."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.remote = os.path.join(root, "remote.git")
        self.clone = os.path.join(root, "plugins", "plugin")
        _git(root, "init", "-q", "--bare", self.remote)
        _git(root, "clone", "-q", self.remote, self.clone)
        _git(self.clone, "config", "user.email", "test@example.com")
        _git(self.clone, "config", "user.name", "test")
        os.makedirs(os.path.join(self.clone, "gamedata"))
        self.file = os.path.join(self.clone, "gamedata", "plugin.json")
        self._commit("{}", "gamedata")
        _git(self.clone, "push", "-q", "origin", "HEAD")
        _git(self.clone, "branch", "-q", "--set-upstream-to", f"origin/{_out(self.clone, 'branch', '--show-current')}")
        self.target = {
            "plugin": "plugin",
            "root_env": "RECORD_DEPLOY_TEST_ROOT",
            "root_default": os.path.join(root, "plugins"),
            "install": "plugin/gamedata/plugin.json",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, content, message):
        with open(self.file, "w", encoding="utf-8") as handle:
            handle.write(content)
        _git(self.clone, "add", "-A")
        _git(self.clone, "commit", "-q", "-m", message)

    def test_names_the_pushed_commit_on_the_path(self):
        entry = record_deploy.describe_target(self.target)

        self.assertEqual(entry["commit"], _out(self.clone, "rev-parse", "HEAD"))
        self.assertEqual(entry["path"], "gamedata/plugin.json")
        self.assertTrue(entry["pushed"])

    def test_names_the_gamedata_commit_not_a_later_unrelated_one(self):
        gamedata_commit = _out(self.clone, "rev-parse", "HEAD")
        with open(os.path.join(self.clone, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("unrelated")
        _git(self.clone, "add", "README.md")
        _git(self.clone, "commit", "-q", "-m", "docs")
        _git(self.clone, "push", "-q")

        self.assertEqual(record_deploy.describe_target(self.target)["commit"], gamedata_commit)

    def test_flags_a_commit_that_is_not_pushed(self):
        self._commit('{"a": 1}', "gamedata: unpushed")

        self.assertFalse(record_deploy.describe_target(self.target)["pushed"])

    def test_refuses_uncommitted_gamedata(self):
        with open(self.file, "w", encoding="utf-8") as handle:
            handle.write('{"dirty": true}')

        self.assertIn("uncommitted", record_deploy.describe_target(self.target)["error"])

    def test_reports_a_target_missing_on_this_machine(self):
        self.target["install"] = "absent/gamedata/plugin.json"

        self.assertIn("not deployed", record_deploy.describe_target(self.target)["error"])


class BuildRecord(unittest.TestCase):
    NOW = datetime.datetime(2026, 10, 8, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def test_deployed_only_when_every_target_is_pushed(self):
        good = {"repo": "https://github.com/o/r", "path": "p", "commit": "a" * 40, "pushed": True}

        record = record_deploy.build_record("14189", describe=lambda target: dict(good), now=self.NOW)

        self.assertEqual(record["status"], "deployed")
        self.assertEqual(record["gameVersion"], "14189")
        self.assertEqual(record["recordedAt"], "2026-10-08T12:00:00Z")
        self.assertEqual(set(record["targets"]), {t["plugin"] for t in check_deploy_drift.DEPLOY_TARGETS})

    def test_partial_when_one_target_is_missing_or_unpushed(self):
        for broken in ({"error": "not deployed on this machine: x"}, {"commit": "b" * 40, "pushed": False}):
            def describe(target, broken=broken):
                if target["plugin"] == "matchzy":
                    return dict(broken)
                return {"commit": "a" * 40, "pushed": True}

            self.assertEqual(record_deploy.build_record("14189", describe=describe, now=self.NOW)["status"], "partial")

    def test_writes_stable_json_atomically(self):
        record = record_deploy.build_record("14189", describe=lambda target: {"commit": "a" * 40, "pushed": True}, now=self.NOW)
        with tempfile.TemporaryDirectory() as directory:
            path = record_deploy.write_record(record, directory)

            self.assertEqual(os.listdir(directory), ["14189.json"])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), record)


class Main(unittest.TestCase):
    def test_exit_code_follows_the_status(self):
        for status, code in (("deployed", 0), ("partial", 1)):
            record = {"gameVersion": "14189", "status": status, "targets": {}}
            with mock.patch.object(record_deploy, "build_record", return_value=record), \
                    mock.patch.object(record_deploy, "write_record", return_value="deployments/14189.json"), \
                    mock.patch("sys.argv", ["record_deploy.py", "-gamever", "14189"]), \
                    mock.patch("builtins.print"):
                self.assertEqual(record_deploy.main(), code)


if __name__ == "__main__":
    unittest.main()
