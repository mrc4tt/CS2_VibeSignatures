"""ghidra_verify: Ghidra's hunt answer against IDA's manual_todo candidate."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ghidra_verify as GV  # noqa: E402

REPORT = {
    "solved": [{"symbol": "A", "va": "0x1000", "how": "strings 1.00"},
               {"symbol": "B", "va": "0x2000", "how": "calls"},
               {"symbol": "C", "va": "0x3000", "how": "vtable"}],
    "unresolved": [{"symbol": "D", "why": "weak", "candidates": [{"va": "0x4000", "score": 0.6}]},
                   {"symbol": "E", "why": "weak", "candidates": [{"va": "0x5000", "score": 0.6}]}],
}


def row(symbol, candidate):
    return {"symbol": symbol, "candidate": candidate}


class CompareTests(unittest.TestCase):
    def verdict(self, symbol, candidate):
        return GV.compare(row(symbol, candidate), REPORT)["verdict"]

    def test_verdicts(self):
        self.assertEqual(self.verdict("A", "0x1000"), "agree")
        self.assertEqual(self.verdict("B", "0x2001"), "disagree")
        self.assertEqual(self.verdict("C", None), "ghidra-only")
        self.assertEqual(self.verdict("D", "0x4000"), "same-guess")
        self.assertEqual(self.verdict("E", "0x9999"), "open")
        self.assertEqual(self.verdict("F", "0x1000"), "open")

    def test_addresses_compare_as_numbers(self):
        self.assertEqual(self.verdict("A", "0x00001000"), "agree")

    def test_load_results_skips_the_raw_hunt_report(self):
        with tempfile.TemporaryDirectory() as root:
            out = GV.result_path("1", "server", "linux", root)
            out.parent.mkdir(parents=True)
            out.write_text(json.dumps({"module": "server", "platform": "linux",
                                       "results": [GV.compare(row("A", "0x1000"), REPORT)]}))
            out.with_suffix(".hunt.json").write_text(json.dumps(REPORT))
            found = GV.load_results("1", root)
        self.assertEqual(list(found), [("server", "linux", "A")])


if __name__ == "__main__":
    unittest.main()
