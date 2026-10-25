import json
import os
import tempfile
import unittest
from unittest.mock import patch

import publish_site_data as P

FILE = "matchzy/gamedata/matchzy.json"


def sig(linux, windows):
    return {"signatures": {"library": "server", "linux": linux, "windows": windows}}


class BuildKeyChangesTests(unittest.TestCase):
    """What autopilot's notification and the Discord bot call "changed in this build":
    against the builds before it, by the same rule as the site's keyChanges."""

    def _run(self, per_build, build):
        with tempfile.TemporaryDirectory() as root:
            for tag, content in per_build.items():
                if content is None:
                    continue
                path = os.path.join(root, tag, FILE)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(content, handle)
                # The generator's companion: its "before" is the template, never the
                # previous build, so it must not decide anything here.
                with open(path + ".metadata.json", "w", encoding="utf-8") as handle:
                    json.dump({"entries": [{"name": "A", "changes": [{"path": ["A", "signatures", "linux"],
                                                                      "before": "TEMPLATE", "after": "x"}]}]}, handle)
            with patch.object(P, "GAMEDATA_ROOT", root), \
                    patch.object(P, "builds", return_value=list(per_build)), \
                    patch.object(P, "generated_files", return_value=[FILE]), \
                    patch.object(P, "symbol_index", return_value={}), \
                    patch.object(P, "_committed_dates", return_value={}):
                changes = P.build_key_changes(build)
                history = P.build_history(list(per_build)[-1])
                counted = {b["gameVersion"]: b["keyChanges"] for b in history["builds"]}
                return changes, counted

    def test_an_identical_file_changed_nothing_whatever_its_metadata_says(self):
        changes, counted = self._run({"1": {"A": sig("aa", "bb")}, "2": {"A": sig("aa", "bb")}}, "2")
        self.assertEqual({}, changes)
        self.assertEqual(0, counted["2"])

    def test_a_moved_value_is_reported_on_either_platform(self):
        changes, counted = self._run({"1": {"A": sig("aa", "bb"), "B": sig("1", "2")},
                                      "2": {"A": sig("aa", "cc"), "B": sig("1", "2")}}, "2")
        self.assertEqual({FILE: ["A"]}, changes)
        self.assertEqual(1, counted["2"])

    def test_a_build_without_the_file_is_skipped_not_compared(self):
        changes, _ = self._run({"1": {"A": sig("aa", "bb")}, "2": None, "3": {"A": sig("aa", "bb")}}, "3")
        self.assertEqual({}, changes)

    def test_a_key_back_after_a_gap_compares_with_its_last_value(self):
        per_build = {"1": {"A": sig("aa", "bb")}, "2": {"B": sig("1", "2")}, "3": {"A": sig("zz", "bb"), "B": sig("1", "2")}}
        changes, counted = self._run(per_build, "3")
        self.assertEqual({FILE: ["A"]}, changes)
        self.assertEqual(1, counted["3"])

    def test_a_first_appearance_is_not_a_change(self):
        changes, counted = self._run({"1": {"A": sig("aa", "bb")}, "2": {"A": sig("aa", "bb"), "N": sig("n", "n")}}, "2")
        self.assertEqual({}, changes)
        self.assertEqual(0, counted["2"])


if __name__ == "__main__":
    unittest.main()
