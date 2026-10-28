"""cpp_tests/fork_tests.yaml is the one list of cpp tests.

sdk_abi_check.sh runs it; ensure_local_gamedata_symbols.py copies it into every
config's cpp_tests: block, and the payer rule reads it directly, so a config that
has not been re-asserted yet still credits the classes the check compares.
"""
import os
import tempfile
import unittest

import yaml

import ensure_local_gamedata_symbols as E
import ida_analyze_bin as I

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK_TESTS = os.path.join(REPO, "cpp_tests", "fork_tests.yaml")

FORK = """# header comment
cpp_tests:
  - name: A_MSVC
    symbol: A
"""


class EnforceForkCppTestsTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(handle, "w") as f:
            f.write(FORK)

    def tearDown(self):
        os.unlink(self.path)

    def test_replaces_a_stale_block(self):
        text = "modules:\n  - name: m\ncpp_tests:\n  - name: Old_MSVC\n    symbol: Old\n"
        patched, changed = E.enforce_fork_cpp_tests(text, self.path)
        self.assertEqual(changed, 1)
        self.assertEqual(patched, "modules:\n  - name: m\ncpp_tests:\n  - name: A_MSVC\n    symbol: A\n")

    def test_is_idempotent(self):
        once, _ = E.enforce_fork_cpp_tests("modules: []\ncpp_tests: []\n", self.path)
        twice, changed = E.enforce_fork_cpp_tests(once, self.path)
        self.assertEqual((twice, changed), (once, 0))

    def test_keeps_a_following_top_level_key(self):
        patched, _ = E.enforce_fork_cpp_tests("cpp_tests: []\nother: 1\n", self.path)
        self.assertTrue(patched.endswith("    symbol: A\nother: 1\n"))

    def test_adds_a_missing_block(self):
        patched, changed = E.enforce_fork_cpp_tests("modules: []\n", self.path)
        self.assertEqual(changed, 1)
        self.assertEqual(yaml.safe_load(patched)["cpp_tests"], [{"name": "A_MSVC", "symbol": "A"}])

    def test_no_fork_list_changes_nothing(self):
        self.assertEqual(E.enforce_fork_cpp_tests("x: 1\n", self.path + ".missing"), ("x: 1\n", 0))


@unittest.skipUnless(os.path.isfile(FORK_TESTS), "needs cpp_tests/fork_tests.yaml")
class PayerReadsForkTestsTests(unittest.TestCase):
    def test_fork_test_classes_are_credited_without_a_config_block(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("modules: []\n")
        try:
            prefixes = I.cpp_test_class_prefixes(f.name)
        finally:
            os.unlink(f.name)
        for prefix in ("CNetChan_", "CServerSideClientBase_", "CCvar_", "CNetworkSystem_"):
            self.assertIn(prefix, prefixes)


if __name__ == "__main__":
    unittest.main()
