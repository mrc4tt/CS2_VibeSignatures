"""POST /api/report: a server's gamedata files are answered known / plugin / unknown, only
unknown ones are stored, and nothing identifying (file text, the install id) is kept."""
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plugin_reports as PR  # noqa: E402
import verify_service as S  # noqa: E402

MATCHZY_OLD = json.dumps({"A": {"signatures": {"linux": "55"}}, "B": {"signatures": {"linux": "48"}}, "C": {}}, indent=4)
MATCHZY_NEW = json.dumps({"A": {"signatures": {"linux": "56"}}, "B": {"signatures": {"linux": "49"}}, "C": {}, "D": {}}, indent=4)
INSTALL = "0123456789abcdef0123456789abcdef"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        self.store = os.path.join(self.tmp.name, "store")
        for build, text in (("14195", MATCHZY_OLD), ("14196", MATCHZY_NEW)):
            folder = os.path.join(self.repo, "gamedata", build, "matchzy", "gamedata")
            os.makedirs(folder)
            with open(os.path.join(folder, "matchzy.json"), "w", encoding="utf-8") as handle:
                handle.write(text)
            with open(os.path.join(folder, "matchzy.metadata.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")
        self.published = PR.Published(root=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, files, install=INSTALL, build="14196"):
        return {"build": build, "platform": "linux", "install": install, "files": files}

    def test_published_copy_of_any_build_is_known(self):
        answer = PR.handle_report(self.report([{"name": "matchzy.json", "sha256": sha(MATCHZY_OLD), "keys": ["A", "B", "C"]}]),
                                  self.published.get(), root=self.store)
        self.assertEqual(answer["files"][0]["status"], "known")
        self.assertEqual(answer["files"][0]["feed"], "matchzy/matchzy.json")
        self.assertEqual(PR.load_records(self.store), [])

    def test_another_release_is_matched_by_keys(self):
        edited = MATCHZY_NEW + "\n"
        answer = PR.handle_report(self.report([{"name": "MatchZy.json", "sha256": sha(edited), "keys": ["A", "B", "Mine"]}]),
                                  self.published.get(), root=self.store)
        self.assertEqual(answer["files"][0]["status"], "plugin")
        self.assertEqual(answer["files"][0]["feed"], "matchzy/matchzy.json")

    def test_too_few_shared_keys_is_unknown_and_recorded(self):
        files = [{"name": "secret.json", "sha256": sha("x"), "keys": ["A", "X", "Y", "Z"], "broken": ["X"]}]
        answer = PR.handle_report(self.report(files), self.published.get(), root=self.store, now=100)
        self.assertEqual(answer["files"][0]["status"], "unknown")
        # a second server, and the first again on a newer build
        PR.handle_report(self.report(files, install="f" * 32), self.published.get(), root=self.store, now=200)
        files[0]["broken"] = ["Y"]
        PR.handle_report(self.report(files, build="14197"), self.published.get(), root=self.store, now=300)

        records = PR.load_records(self.store)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(len(record["installs"]), 2)
        self.assertEqual(record["broken"], {"14196": ["X"], "14197": ["Y"]})
        self.assertEqual((record["first_seen"], record["last_seen"]), (100, 300))
        # the install id itself is stored nowhere
        for folder, _dirs, names in os.walk(self.store):
            for name in names:
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    self.assertNotIn(INSTALL, handle.read())

    def test_validation(self):
        good = {"name": "a.json", "sha256": sha("a"), "keys": []}
        for bad in (
            {"build": "../x", "platform": "linux", "install": INSTALL, "files": []},
            {"build": "14196", "platform": "mac", "install": INSTALL, "files": []},
            {"build": "14196", "platform": "linux", "install": "nothex", "files": []},
            self.report([{**good, "sha256": "A" * 64}]),
            self.report([{**good, "keys": ["x" * 300]}]),
            self.report([good] * (PR.MAX_FILES_PER_REPORT + 1)),
            [],
        ):
            with self.assertRaises(PR.BadReport):
                PR.parse_report(bad)
        parsed = PR.parse_report(self.report([{**good, "name": "../../etc/passwd"}]))
        self.assertEqual(parsed["files"][0]["name"], "passwd")

    def test_route(self):
        service = S.Service(None, files_root=self.store)
        service.published = self.published
        status, payload = service.handle("POST", "/api/report",
                                         json.dumps(self.report([{"name": "matchzy.json", "sha256": sha(MATCHZY_NEW)}])).encode())
        self.assertEqual(status, 200)
        self.assertEqual(payload["files"][0]["status"], "known")
        self.assertEqual(service.handle("GET", "/api/report", None)[0], 404)
        self.assertEqual(service.handle("POST", "/api/report", b"not json")[0], 400)
        self.assertEqual(service.handle("POST", "/api/report", b"{}")[0], 400)

    def test_list_command_survives_an_empty_store(self):
        self.assertEqual(PR.load_records(os.path.join(self.tmp.name, "nothing")), [])


if __name__ == "__main__":
    unittest.main()
