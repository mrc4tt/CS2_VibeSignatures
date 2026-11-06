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

    def test_broken_keys_are_tallied_per_feed_file_and_server(self):
        known = {"name": "matchzy.json", "sha256": sha(MATCHZY_NEW), "keys": ["A", "B", "C", "D"], "broken": ["A"]}
        other = {"name": "secret.json", "sha256": sha("x"), "keys": ["X", "Y"], "broken": ["X", "Y"]}
        get = self.published.get()
        self.assertTrue(PR.handle_report(self.report([known, other]), get, root=self.store, now=10) is not None)
        PR.handle_report(self.report([{**known, "broken": ["A", "B"]}], install="a" * 32), get, root=self.store, now=20)
        PR.handle_report(self.report([{**known, "broken": ["A", "B"]}], install="a" * 32), get, root=self.store, now=30)

        tally = PR.load_tally("14196", self.store)
        matchzy = tally["files"]["matchzy/matchzy.json"]
        self.assertEqual(matchzy["status"], "known")
        self.assertEqual(len(matchzy["installs"]), 2)
        self.assertEqual({k: len(v) for k, v in matchzy["broken"].items()}, {"A": 2, "B": 1})
        self.assertIn(f"sha256:{sha('x')}", tally["files"])

        # a server's newer report replaces its older one: B fixed there, gone from the tally
        PR.handle_report(self.report([{**known, "broken": []}], install="a" * 32), get, root=self.store, now=40)
        matchzy = PR.load_tally("14196", self.store)["files"]["matchzy/matchzy.json"]
        self.assertEqual({k: len(v) for k, v in matchzy["broken"].items()}, {"A": 1})

        summary = PR.summarize(PR.load_tally("14196", self.store))
        self.assertEqual(summary["servers"], 2)
        self.assertEqual(summary["files"][0]["file"], "secret.json (" + sha("x")[:12] + ")")
        self.assertEqual(summary["files"][0]["broken"][0], {"key": "X", "servers": 1, "linux": 1, "windows": 0})
        self.assertNotIn(PR.install_hash(INSTALL), json.dumps(summary))
        for folder, _dirs, names in os.walk(self.store):
            for name in names:
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    self.assertNotIn(INSTALL, handle.read())

    def test_tally_keeps_the_newest_builds_and_refuses_far_ahead_ones(self):
        get = self.published.get()
        entry = {"name": "matchzy.json", "sha256": sha(MATCHZY_NEW), "keys": ["A"], "broken": ["A"]}
        self.assertFalse(PR.record_tally(PR.parse_report(self.report([entry], build="14299")),
                                         [PR.classify(entry, get)], get, root=self.store))
        self.assertEqual(PR.tally_builds(self.store), [])
        for build in range(14190, 14200):
            PR.handle_report(self.report([entry], build=str(build)), get, root=self.store)
        self.assertEqual(PR.tally_builds(self.store), [str(b) for b in range(14199, 14199 - PR.TALLY_BUILDS, -1)])
        # an old build no longer kept does not come back
        PR.handle_report(self.report([entry], build="14180"), get, root=self.store)
        self.assertNotIn("14180", PR.tally_builds(self.store))

    def test_tally_size_caps(self):
        get = self.published.get()
        many = {"name": "secret.json", "sha256": sha("x"), "keys": [],
                "broken": [f"K{i}" for i in range(PR.TALLY_MAX_KEYS + 50)]}
        PR.handle_report(self.report([many]), get, root=self.store)
        item = PR.load_tally("14196", self.store)["files"][f"sha256:{sha('x')}"]
        self.assertEqual(len(item["broken"]), PR.TALLY_MAX_KEYS)
        files = [{"name": f"f{i}.json", "sha256": sha(str(i)), "keys": []} for i in range(PR.MAX_FILES_PER_REPORT)]
        PR.handle_report(self.report(files), get, root=self.store)
        PR.handle_report(self.report([{**f, "sha256": sha("b" + f["name"])} for f in files]), get, root=self.store)
        self.assertEqual(len(PR.load_tally("14196", self.store)["files"]), PR.TALLY_MAX_FILES)

    def test_digest_only_when_it_matters_and_debounced(self):
        sent, clock = [], [1000.0]
        digest = PR.Digest("http://bot", "s", root=self.store, debounce=1800, settle=60,
                           send=sent.append, clock=lambda: clock[0])
        pokes = []
        digest.poke = lambda build, _poke=digest.poke: (pokes.append(build), _poke(build))
        get = self.published.get()
        entry = {"name": "matchzy.json", "sha256": sha(MATCHZY_NEW), "keys": ["A"], "broken": ["A"]}

        PR.handle_report(self.report([entry]), get, root=self.store, digest=digest)
        self.assertEqual(pokes, ["14196"])
        self.assertEqual(digest.due["14196"], 1060.0)  # settles before the first send
        # nothing new until it was sent: still one pending digest
        PR.handle_report(self.report([entry], install="b" * 32), get, root=self.store, digest=digest)
        self.assertEqual(len(digest.due), 1)

        # the worker's send: what the bot gets carries counts, never install hashes
        del digest.due["14196"]
        digest.sent["14196"] = clock[0]
        self.assertTrue(digest.flush("14196"))
        payload = sent[-1]
        self.assertEqual((payload["outcome"], payload["gamever"]), ("server-reports", "14196"))
        self.assertEqual(payload["reports"]["files"][0]["broken"][0]["servers"], 2)
        self.assertNotIn(PR.install_hash(INSTALL), json.dumps(payload))

        # same key, 3rd and 4th server: below the next level (5), no digest
        pokes.clear()
        for who in "cd":
            PR.handle_report(self.report([entry], install=who * 32), get, root=self.store, digest=digest)
        self.assertEqual(pokes, [])
        # the 5th crosses a level; the next send waits for the debounce
        PR.handle_report(self.report([entry], install="e" * 32), get, root=self.store, digest=digest)
        self.assertEqual(pokes, ["14196"])
        self.assertEqual(digest.due["14196"], 1000.0 + 1800)
        # a key broken for the first time is news too
        digest.due.clear()
        pokes.clear()
        PR.handle_report(self.report([{**entry, "broken": ["A", "B"]}]), get, root=self.store, digest=digest)
        self.assertEqual(pokes, ["14196"])
        # an older build's tally never sends
        pokes.clear()
        PR.handle_report(self.report([{**entry, "broken": ["Z"]}], build="14195"), get, root=self.store, digest=digest)
        self.assertEqual(pokes, [])

    def test_digest_worker_sends_and_survives_a_dead_bot(self):
        import threading
        done = threading.Event()
        calls = []

        def send(payload):
            calls.append(payload)
            done.set()
            raise OSError("bot down")

        digest = PR.Digest("http://bot", "s", root=self.store, settle=0, send=send)
        entry = {"name": "matchzy.json", "sha256": sha(MATCHZY_NEW), "keys": ["A"], "broken": ["A"]}
        PR.handle_report(self.report([entry]), self.published.get(), root=self.store, digest=digest)
        self.assertTrue(done.wait(5))
        self.assertEqual(calls[0]["gamever"], "14196")
        # not accepted, so nothing counts as notified: the next report that matters retries
        self.assertEqual(PR.load_tally("14196", self.store)["notified"], {})
        self.assertIsNone(PR.Digest.from_env(environ={}))
        self.assertIsNotNone(PR.Digest.from_env(environ={"AUTOPILOT_BOT_URL": "u", "AUTOPILOT_BOT_SECRET": "s"}))

    def test_list_command_survives_an_empty_store(self):
        self.assertEqual(PR.load_records(os.path.join(self.tmp.name, "nothing")), [])


if __name__ == "__main__":
    unittest.main()
