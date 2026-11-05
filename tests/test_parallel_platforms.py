"""Linux and windows are analysed side by side (autopilot AUTOPILOT_PARALLEL_PLATFORMS).

What keeps that safe is pinned here: the run scripts' phases, each script publishing
and cleaning only its own platform, and windows' sister facts waiting for linux.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import ida_analyze_bin  # noqa: E402


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as handle:
        return handle.read()


class RunScripts(unittest.TestCase):
    def test_each_script_has_the_three_phases_and_stays_on_its_platform(self):
        for platform in ("linux", "windows"):
            text = _read(f"run_{platform}.sh")
            for phase in ("prepare", "analyse", "publish"):
                self.assertIn(f"if phase {phase}; then", text, platform)
            self.assertIn(f'"$module_dir"*.{platform}.yaml', text, "publishes only its own artifacts")
            self.assertNotIn('"$module_dir"*.yaml', text)
            self.assertIn(f'.published-{platform}"', text)
            self.assertIn(f'[ "{platform}" = {platform} ] || continue', text, "cleans only its own databases")
            subprocess.run(["bash", "-n", os.path.join(REPO, f"run_{platform}.sh")], check=True)

    def test_autopilot_prepares_once_and_publishes_windows_after_linux(self):
        text = _read("autopilot.sh")
        prepare = text.index('CS2VIBE_RUN_PHASES=prepare ./run_linux.sh')
        start = text.index("        start_windows_analysis")
        linux = text.index('CS2VIBE_RUN_PHASES="analyse publish" ./run_linux.sh')
        release = text.index("( linux_release )")
        publish = text.index('CS2VIBE_RUN_PHASES=publish ./run_windows.sh')
        self.assertLess(prepare, start)
        self.assertLess(start, linux)
        self.assertLess(linux, release)
        self.assertLess(release, publish)
        self.assertIn("CS2VIBE_RUN_PHASES=analyse ./run_windows.sh", text)
        # the linux release must not pack or commit a windows run still in progress
        release_body = text[text.index("linux_release() {"):text.index("linux_finish() {")]
        self.assertIn("-name '*.linux.yaml'", release_body)
        self.assertIn('-platform linux -artifactdir "$view"', release_body)
        self.assertIn('":(glob)bin_artifacts/$TAG/**/*.linux.yaml"', release_body)
        self.assertNotIn('"bin_artifacts/$TAG" ', release_body)
        subprocess.run(["bash", "-n", os.path.join(REPO, "autopilot.sh")], check=True)


class SisterFactsWait(unittest.TestCase):
    def test_goes_ahead_when_no_sister_run_is_alive(self):
        with tempfile.TemporaryDirectory() as repo, \
                mock.patch.object(ida_analyze_bin, "_sister_analysis_running", return_value=False):
            self.assertTrue(ida_analyze_bin._wait_for_sister_publish(repo, "14196", "linux", poll=0))

    def test_goes_ahead_once_the_marker_exists(self):
        with tempfile.TemporaryDirectory() as repo, \
                mock.patch.object(ida_analyze_bin, "_sister_analysis_running", return_value=True):
            os.makedirs(os.path.join(repo, "bin", "14196"))
            open(os.path.join(repo, "bin", "14196", ".published-linux"), "w").close()
            self.assertTrue(ida_analyze_bin._wait_for_sister_publish(repo, "14196", "linux", poll=0))

    def test_gives_up_after_the_deadline_while_linux_still_runs(self):
        with tempfile.TemporaryDirectory() as repo, \
                mock.patch.object(ida_analyze_bin, "_sister_analysis_running", return_value=True), \
                mock.patch.dict(os.environ, {ida_analyze_bin.SISTER_WAIT_ENV: "0"}), \
                mock.patch("builtins.print"):
            self.assertFalse(ida_analyze_bin._wait_for_sister_publish(repo, "14196", "linux", poll=0))

    def test_finds_a_live_run_by_its_arguments(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                  "ida_analyze_bin.py", "-gamever", "99999", "-platform", "linux"])
        try:
            import time
            for _ in range(50):
                if ida_analyze_bin._sister_analysis_running("99999", "linux"):
                    break
                time.sleep(0.02)
            self.assertTrue(ida_analyze_bin._sister_analysis_running("99999", "linux"))
            self.assertFalse(ida_analyze_bin._sister_analysis_running("99999", "windows"))
            self.assertFalse(ida_analyze_bin._sister_analysis_running("99998", "linux"))
        finally:
            child.kill()
            child.wait()


if __name__ == "__main__":
    unittest.main()
