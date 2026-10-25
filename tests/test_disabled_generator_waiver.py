"""A disabled plugin stops paying for symbols: the waiver in ida_analyze_bin and pack.

Uses the repository's own generators and 14182 config, so it tracks the real switch
(CS2Fixes MODULE_ENABLED = False) rather than a fixture that could drift from it.
"""
import os
import unittest
import unittest.mock

import ida_analyze_bin as I

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, "configs", "14182.yaml")


def _artifact(module, symbol, platform="linux"):
    return os.path.join(REPO, "bin_artifacts", "14181", module, f"{symbol}.{platform}.yaml")


@unittest.skipUnless(os.path.isfile(CONFIG), "needs configs/14182.yaml")
class DisabledGeneratorWaiverTests(unittest.TestCase):
    def test_cs2fixes_is_disabled(self):
        names = {os.path.basename(d) for d in I.disabled_generator_dirs(os.path.join(REPO, "gamedata-generators"))}
        self.assertIn("CS2Fixes", names)
        self.assertNotIn("CounterStrikeSharp", names)

    def test_symbol_only_cs2fixes_reads_is_waived(self):
        path = _artifact("server", "CBaseFilter_InputTestActivator", "windows")
        self.assertFalse(I.artifact_has_consumer(path, "windows", CONFIG))
        self.assertTrue(I.artifact_only_disabled_consumers(path, "windows", CONFIG))

    def test_symbol_an_enabled_plugin_reads_is_not_waived(self):
        path = _artifact("server", "CCSPlayer_ItemServices_GiveNamedItem")
        self.assertTrue(I.artifact_has_consumer(path, "linux", CONFIG))
        self.assertFalse(I.artifact_only_disabled_consumers(path, "linux", CONFIG))

    def test_symbol_no_plugin_ever_read_is_not_a_disabled_plugin_waiver(self):
        # never consumed by any generator, enabled or not: artifact_unpaid decides those
        path = _artifact("server", "CEntityInstance_OnSetDormant")
        self.assertFalse(I.artifact_only_disabled_consumers(path, "linux", CONFIG))

    def test_no_config_never_waives(self):
        self.assertFalse(I.artifact_only_disabled_consumers(_artifact("server", "X"), "linux", None))


CONFIG_14192 = os.path.join(REPO, "configs", "14192.yaml")


@unittest.skipUnless(os.path.isfile(CONFIG_14192), "needs configs/14192.yaml")
class UnreadOutputWaiverTests(unittest.TestCase):
    """A required output nothing reads is not hunted by an agent and not insisted on by pack."""

    def _path(self, symbol):
        return os.path.join(REPO, "bin_artifacts", "14192", "server", f"{symbol}.linux.yaml")

    def test_output_nothing_reads_is_unpaid(self):
        self.assertTrue(I.artifact_unpaid(self._path("CBaseEntity_GetChangeAccessorPathInfo_1"), "linux", CONFIG_14192))

    def test_cpp_test_class_records_are_read(self):
        # IGameSystem_MSVC compares the SDK header against every IGameSystem_* record
        path = self._path("IGameSystem_OnRestoreGame")
        self.assertTrue(I.artifact_has_consumer(path, "linux", CONFIG_14192))
        self.assertFalse(I.artifact_unpaid(path, "linux", CONFIG_14192))

    def test_plugin_key_is_read(self):
        self.assertFalse(I.artifact_unpaid(self._path("CCSPlayer_ItemServices_GiveNamedItem"), "linux", CONFIG_14192))

    def test_switch_restores_the_disabled_plugins_only_rule(self):
        path = self._path("CBaseEntity_GetChangeAccessorPathInfo_1")
        with unittest.mock.patch.dict(os.environ, {I.HUNT_UNREAD_ENV: "1"}):
            self.assertFalse(I.artifact_unpaid(path, "linux", CONFIG_14192))

    def test_no_config_never_waives(self):
        self.assertFalse(I.artifact_unpaid(self._path("X"), "linux", None))


if __name__ == "__main__":
    unittest.main()
