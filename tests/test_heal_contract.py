"""heal_contract re-makes the artifacts audit_artifact_contract rejects, through the tasks
that declare them; fork-owned optional tasks can order themselves after an input."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ensure_local_gamedata_symbols as E  # noqa: E402
import heal_contract as H  # noqa: E402

CONFIG = """modules:
  - name: server
    skills:
      - name: find-X_vtable-server
        optional_output:
          - X_vtable.{platform}.yaml
      - name: find-X_Destroy-linux
        optional_output:
          - X_Destroy.linux.yaml
      - name: find-X_Destroy
        optional_output:
          - X_Destroy.windows.yaml
      - name: find-Y
        expected_output:
          - Y.{platform}.yaml
"""


class HealTests(unittest.TestCase):
    def test_bad_lines_are_parsed(self):
        line = "  BAD  server/X_Destroy.linux.yaml: vtable_name is 'X<Y>', the previous gamever has 'X_Y'"
        m = H.BAD.match(line)
        self.assertEqual((m["module"], m["file"], m["platform"]), ("server", "X_Destroy.linux.yaml", "linux"))

    def test_producing_tasks_follow_the_platform(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(CONFIG)
        self.assertEqual(H.producing_tasks(handle.name, "server", "X_Destroy.linux.yaml", "linux"), ["find-X_Destroy-linux"])
        self.assertEqual(H.producing_tasks(handle.name, "server", "Y.windows.yaml", "windows"), ["find-Y"])


class OptionalInputTests(unittest.TestCase):
    def test_fork_task_gets_its_optional_input_once(self):
        saved = list(E.FORK_OWNED_OPTIONAL_TASKS)
        try:
            E.FORK_OWNED_OPTIONAL_TASKS[:] = [("find-X_Destroy-linux", "server", "X_Destroy.linux.yaml",
                                               ["X_vtable.{platform}.yaml"])]
            text, changed = E.enforce_fork_owned_optional_tasks(CONFIG)
            again, changed_again = E.enforce_fork_owned_optional_tasks(text)
        finally:
            E.FORK_OWNED_OPTIONAL_TASKS[:] = saved
        self.assertEqual(changed, 1)
        self.assertIn("      - name: find-X_Destroy-linux\n        optional_output:\n          - X_Destroy.linux.yaml\n"
                      "        optional_input:\n          - X_vtable.{platform}.yaml", text)
        self.assertEqual((changed_again, again), (0, text))


if __name__ == "__main__":
    unittest.main()
