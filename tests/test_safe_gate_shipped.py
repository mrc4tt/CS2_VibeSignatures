"""autopilot_safe_gate holds a build for a lost platform only when an enabled plugin ships the symbol."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autopilot_safe_gate as G  # noqa: E402


class LostPlatformTests(unittest.TestCase):
    def _decide(self, shipped, platforms=("linux", "windows")):
        old = {"server/IsCommandWhitelisted": {"linux", "windows"}, "server/ClientPrint": {"linux", "windows"}}
        new = {"server/ClientPrint": {"linux"}}
        with mock.patch.object(G, "generated_files", return_value=["a.json"]), \
                mock.patch.object(G, "read_keys", return_value={}), \
                mock.patch.object(G, "coverage", return_value=(1, 1)), \
                mock.patch.object(G, "snapshot_platforms", side_effect=[new, old]), \
                mock.patch.object(G, "shipped_symbols", return_value=shipped):
            return G.decide("2", "1", platforms)

    def test_unshipped_symbol_is_a_note_not_a_hold(self):
        result = self._decide({"server/ClientPrint"})
        self.assertEqual([h["symbol"] for h in result["holds"]], ["server/ClientPrint"])
        self.assertTrue(any("IsCommandWhitelisted" in n for n in result["notes"]))

    def test_without_the_dataset_every_symbol_still_counts(self):
        result = self._decide(None)
        self.assertEqual(sorted(h["symbol"] for h in result["holds"]),
                         ["server/ClientPrint", "server/IsCommandWhitelisted"])

    def test_linux_release_judges_linux_alone(self):
        # The linux-first release has no windows artifacts yet: ClientPrint keeping
        # linux is not a lost platform there, IsCommandWhitelisted losing it still is.
        result = self._decide(None, ("linux",))
        self.assertEqual([h["symbol"] for h in result["holds"]], ["server/IsCommandWhitelisted"])


if __name__ == "__main__":
    unittest.main()
