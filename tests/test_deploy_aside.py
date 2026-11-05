"""deploy_local_plugins.sh commits onto origin's HEAD branch even when a plugin
clone is checked out on a work branch, and leaves that checkout alone.

14196: ~/CounterStrikeSharp was on test/frame-probe (no upstream). The gamedata
commit landed on the work branch, "nothing to push" was printed, and record_deploy
failed the build on every tick.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_FILE = "configs/addons/counterstrikesharp/gamedata/gamedata.json"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git") and os.path.isdir(os.path.join(REPO, "gamedata")), "needs git and gamedata/")
class DeployAside(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.remote = os.path.join(self.home, "css.git")
        self.clone = os.path.join(self.home, "CounterStrikeSharp")
        _git(self.home, "init", "-q", "--bare", "-b", "main", self.remote)
        _git(self.home, "clone", "-q", self.remote, self.clone)
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            _git(self.clone, "config", key, value)
        self.file = os.path.join(self.clone, CSS_FILE)
        os.makedirs(os.path.dirname(self.file))
        self._write('{"old": 1}\n')
        with open(os.path.join(self.clone, "configs", "core.json"), "w") as handle:
            handle.write("main\n")
        _git(self.clone, "add", "-A")
        _git(self.clone, "commit", "-q", "-m", "init")
        _git(self.clone, "push", "-q", "origin", "main")
        _git(self.clone, "remote", "set-head", "origin", "main")
        _git(self.clone, "switch", "-q", "-c", "test/work")
        with open(os.path.join(self.clone, "configs", "core.json"), "w") as handle:
            handle.write("work branch only\n")
        _git(self.clone, "commit", "-q", "-am", "work")
        self.work_head = _git(self.clone, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, content):
        with open(self.file, "w") as handle:
            handle.write(content)

    def _deploy(self):
        gamever = sorted(d for d in os.listdir(os.path.join(REPO, "gamedata")) if d[:1].isdigit())[-1]
        env = dict(os.environ, HOME=self.home)
        return subprocess.run([os.path.join(REPO, "deploy_local_plugins.sh"), gamever],
                              cwd=REPO, env=env, capture_output=True, text=True)

    def test_commits_onto_main_and_leaves_the_work_branch(self):
        self._write('{"new": 2}\n')

        result = self._deploy()

        self.assertIn("pushed onto main", result.stdout, result.stdout + result.stderr)
        self.assertEqual(_git(self.remote, "show", f"main:{CSS_FILE}"), '{"new": 2}')
        self.assertEqual(_git(self.remote, "show", "main:configs/core.json"), "main",
                         "nothing but the gamedata file may reach main")
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), self.work_head)
        self.assertEqual(_git(self.clone, "branch", "--show-current"), "test/work")

        again = self._deploy()
        self.assertIn("nothing to push", again.stdout)
        self.assertEqual(_git(self.remote, "rev-list", "--count", "main"), "2")


if __name__ == "__main__":
    unittest.main()
