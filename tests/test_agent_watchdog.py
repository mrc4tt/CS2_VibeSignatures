"""An agent is stopped as soon as its expected outputs appear from elsewhere."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import agent_runner


class WatchdogTests(unittest.TestCase):
    def test_stops_a_running_process_when_outputs_arrive(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "X.windows.yaml")
            threading.Timer(0.5, lambda: open(target, "w").write("func_name: X\n")).start()
            started = time.time()
            with mock.patch.object(agent_runner, "WATCH_INTERVAL", 0.2):
                with self.assertRaises(agent_runner.StoppedForOutputs):
                    agent_runner._run_process_with_stream_capture(
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        timeout=20,
                        stop_when=lambda: os.path.exists(target),
                    )
            self.assertLess(time.time() - started, 5)

    def test_without_stop_when_the_process_runs_to_completion(self):
        result = agent_runner._run_process_with_stream_capture([sys.executable, "-c", "print('ok')"], timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ok", result.stdout)

    def test_timeout_still_raises(self):
        with mock.patch.object(agent_runner, "WATCH_INTERVAL", 0.2):
            with self.assertRaises(subprocess.TimeoutExpired):
                agent_runner._run_process_with_stream_capture(
                    [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1, stop_when=lambda: False
                )

    def test_remote_fetch_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {"CS2VIBE_WATCH_REMOTE": "0"}):
            self.assertEqual(agent_runner._materialize_remote_outputs(["/nonexistent/X.linux.yaml"]), [])


if __name__ == "__main__":
    unittest.main()
