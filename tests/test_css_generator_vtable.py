"""CounterStrikeSharp's generator writes a virtual function's vtable slot next to its signature.

CounterStrikeSharp falls back to the slot when the pattern stops resolving and cross-checks the
two when both resolve. The block must not carry "linux"/"windows" keys: every gamedata walker
here reads an object with platform keys as an entry of its own.
"""
import importlib.util
import json
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location("css_gen", os.path.join(REPO, "gamedata-generators", "CounterStrikeSharp", "gamedata.py"))
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)

KEY = "CBaseTrigger_EndTouch"


def record(sig, cls, index):
    return {"func_sig": sig, "vtable_name": cls, "vfunc_index": index}


class VtableSlotTests(unittest.TestCase):
    def _run(self, yaml_platforms, platforms=("linux", "windows"), existing=None):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "config", "addons", "counterstrikesharp", "gamedata")
            os.makedirs(path)
            entry = {"signatures": {"library": "server", "linux": "OLD", "windows": "OLDW"}}
            if existing is not None:
                entry["vtable"] = existing
            with open(os.path.join(path, "gamedata.json"), "w") as handle:
                json.dump({KEY: entry}, handle)
            yaml_data = {KEY: {"library": "server", **yaml_platforms}}
            GEN.update(yaml_data, {}, list(platforms), out, {}, debug=False)
            with open(os.path.join(path, "gamedata.json")) as handle:
                return json.load(handle)[KEY]

    def test_slot_is_written_for_both_platforms(self):
        got = self._run({"linux": record("55 48", "CBaseTrigger", 151), "windows": record("40 53", "CBaseTrigger", 152)})
        self.assertEqual(got["vtable"], {"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152})
        self.assertEqual(got["signatures"]["linux"], "55 48")

    def test_block_has_no_platform_keys(self):
        got = self._run({"linux": record("55 48", "CBaseTrigger", 151), "windows": record("40 53", "CBaseTrigger", 152)})
        self.assertFalse({"linux", "windows"} & set(got["vtable"]))

    def test_non_virtual_function_gets_no_block(self):
        got = self._run({"linux": {"func_sig": "55 48"}, "windows": {"func_sig": "40 53"}})
        self.assertNotIn("vtable", got)

    def test_stale_block_is_removed_when_the_slot_is_gone(self):
        got = self._run({"linux": {"func_sig": "55 48"}, "windows": {"func_sig": "40 53"}},
                        existing={"class": "CBaseTrigger", "linux_index": 150, "windows_index": 151})
        self.assertNotIn("vtable", got)

    def test_single_platform_run_keeps_the_other_platform(self):
        got = self._run({"linux": record("55 48", "CBaseTrigger", 153)}, platforms=("linux",),
                        existing={"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152})
        self.assertEqual(got["vtable"], {"class": "CBaseTrigger", "linux_index": 153, "windows_index": 152})

    def test_class_change_drops_the_other_platform(self):
        got = self._run({"linux": record("55 48", "CBaseToggle", 90)}, platforms=("linux",),
                        existing={"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152})
        self.assertEqual(got["vtable"], {"class": "CBaseToggle", "linux_index": 90})

    def test_platforms_disagreeing_on_the_class_get_no_block(self):
        got = self._run({"linux": record("55 48", "CBaseTrigger", 151), "windows": record("40 53", "CBaseToggle", 152)})
        self.assertNotIn("vtable", got)


if __name__ == "__main__":
    unittest.main()
