import json
import os
import tempfile
import unittest
from unittest.mock import patch

import publish_site_data as P

FILE = "CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json"


class RemovedKeyTests(unittest.TestCase):
    """A key that leaves a file must say so: points record only changes, so a removed
    key used to keep its last value for ever on the site."""

    def _history(self, per_build):
        with tempfile.TemporaryDirectory() as root:
            for build, content in per_build.items():
                path = os.path.join(root, build, FILE)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(content, handle)
            with patch.object(P, "GAMEDATA_ROOT", root), \
                    patch.object(P, "builds", return_value=list(per_build)), \
                    patch.object(P, "generated_files", return_value=[FILE]), \
                    patch.object(P, "symbol_index", return_value={}), \
                    patch.object(P, "_committed_dates", return_value={}):
                return P.build_history(list(per_build)[-1])["files"][FILE]

    def test_a_removed_key_records_when_it_went(self):
        entry = self._history({
            "1": {"SelectItem": {"offsets": {"linux": 31, "windows": 30}}, "Keep": {"offsets": {"linux": 1, "windows": 2}}},
            "2": {"Keep": {"offsets": {"linux": 1, "windows": 2}}},
            "3": {"Keep": {"offsets": {"linux": 1, "windows": 2}}},
        })
        self.assertEqual(["2"], entry["SelectItem"]["gone"])
        self.assertNotIn("gone", entry["Keep"])

    def test_a_key_that_comes_back_gets_a_new_point(self):
        entry = self._history({
            "1": {"K": {"offsets": {"linux": 5, "windows": 6}}},
            "2": {"Other": {"offsets": {"linux": 1, "windows": 2}}},
            "3": {"K": {"offsets": {"linux": 5, "windows": 6}}},
        })
        self.assertEqual(["2"], entry["K"]["gone"])
        self.assertEqual(["1", "3"], [point[0] for point in entry["K"]["points"]])
        self.assertEqual([], entry["K"]["changes"])


if __name__ == "__main__":
    unittest.main()


class VtableKeyTests(unittest.TestCase):
    """A CounterStrikeSharp "vtable" block is published as "<entry>.vtable", so the site can
    show when a slot moved and patch a stale index, and it maps to the entry's symbol."""

    def test_vtable_block_is_its_own_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "gamedata.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"CBaseTrigger_EndTouch": {
                    "signatures": {"library": "server", "linux": "55 48", "windows": "40 53"},
                    "vtable": {"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152}}}, handle)
            values = P.read_values(path)
        self.assertEqual(values, {"CBaseTrigger_EndTouch": ["55 48", "40 53"],
                                  "CBaseTrigger_EndTouch.vtable": [151, 152]})

    def test_vtable_key_maps_to_the_entry_symbol(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "1", FILE)
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"K": {"signatures": {"linux": "55", "windows": "40"},
                                 "vtable": {"class": "C", "linux_index": 3, "windows_index": 4}}}, handle)
            with patch.object(P, "GAMEDATA_ROOT", root), \
                    patch.object(P, "builds", return_value=["1"]), \
                    patch.object(P, "generated_files", return_value=[FILE]), \
                    patch.object(P, "symbol_index", return_value={P.fold("K"): "server/K"}), \
                    patch.object(P, "_committed_dates", return_value={}):
                history = P.build_history("1")
        self.assertEqual(history["keyToSymbol"][f"{FILE}|K.vtable"], "server/K")
        self.assertEqual(history["files"][FILE]["K.vtable"]["points"], [["1", 3, 4]])
