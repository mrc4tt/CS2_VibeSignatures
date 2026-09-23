"""CounterStrikeSharp's generator writes a global's gv_sig, not only func_sig.

IGameSystem_InitAllSystems_pFirst kept its template value from 14180 to 14182 because only
func_sig was read, and that value matched twice on linux 14182.
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


class GvSignatureTests(unittest.TestCase):
    def _run(self, record):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "config", "addons", "counterstrikesharp", "gamedata")
            os.makedirs(path)
            with open(os.path.join(path, "gamedata.json"), "w") as handle:
                json.dump({"IGameSystem_InitAllSystems_pFirst": {"signatures": {
                    "library": "server", "linux": "OLD", "windows": "OLDW"}}}, handle)
            yaml_data = {"IGameSystem_InitAllSystems_pFirst": {"library": "server", "category": "gv", "linux": record}}
            GEN.update(yaml_data, {}, ["linux"], out, {}, debug=False)
            with open(os.path.join(path, "gamedata.json")) as handle:
                return json.load(handle)["IGameSystem_InitAllSystems_pFirst"]["signatures"]

    def test_gv_sig_at_the_instruction_is_written(self):
        got = self._run({"gv_sig": "4C 8B 35 ?? ?? ?? ?? 4D 85 F6 75 ?? E9", "gv_inst_offset": 0})
        self.assertEqual(got["linux"], "4C 8B 35 ? ? ? ? 4D 85 F6 75 ? E9")
        self.assertEqual(got["windows"], "OLDW")

    def test_gv_sig_starting_before_the_instruction_is_not(self):
        got = self._run({"gv_sig": "48 89 5C 24 ?? 4C 8B 35", "gv_inst_offset": 5})
        self.assertEqual(got["linux"], "OLD")
