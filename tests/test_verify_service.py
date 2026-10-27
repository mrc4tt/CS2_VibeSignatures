"""verify_service answers an uploaded file with the pipeline's own verdicts, and only
ever proposes a replacement value this build already knows to be right."""
import concurrent.futures as cf
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify_plugin_gamedata as VPG  # noqa: E402
import verify_service as S  # noqa: E402

BUILD = "14192"
MATCHZY = os.path.join(S.REPO_ROOT, "gamedata", BUILD, "matchzy", "gamedata", "matchzy.json")
HAVE_BUILD = os.path.isfile(MATCHZY) and os.path.isfile(os.path.join(S.REPO_ROOT, "gamesymbols", f"{BUILD}.yaml"))


def _shipped(build):
    out = []
    for plugin, path in S.shipped_files(build):
        with open(path, "r", encoding="utf-8-sig") as handle:
            entries, note = VPG.load_gamedata_text(handle.read())
        if not note:
            out.append((plugin, path, entries))
    return out


class ValidationTests(unittest.TestCase):
    def test_build_must_be_scannable(self):
        with self.assertRaises(S.BadRequest):
            S.parse_verify({"gamedata": "{}", "build": "../14192"}, [BUILD])
        with self.assertRaises(S.BadRequest):
            S.parse_verify({"gamedata": "{}", "build": "14100"}, [BUILD])
        with self.assertRaises(S.BadRequest):
            S.parse_verify({"gamedata": "{}"}, [])
        self.assertEqual(S.parse_verify({"gamedata": "{}"}, [BUILD, "14191"])[0], BUILD)

    def test_platform_and_filename(self):
        with self.assertRaises(S.BadRequest):
            S.parse_verify({"gamedata": "{}", "platform": "mac"}, [BUILD])
        build, _, filename, platforms = S.parse_verify(
            {"gamedata": "{}", "platform": "linux", "filename": "../../etc/matchzy.json"}, [BUILD])
        self.assertEqual((filename, platforms), ("matchzy.json", ("linux",)))

    def test_check_limits(self):
        with self.assertRaises(S.BadRequest):
            S.parse_check({"signature": "55 " * 300, "platform": "linux"}, [BUILD])
        with self.assertRaises(S.BadRequest):
            S.parse_check({"signature": "55 48", "platform": "linux", "module": "../x"}, [BUILD])
        self.assertEqual(S.parse_check({"signature": "`55 48 89 E5`", "platform": "linux"}, [BUILD]),
                         (BUILD, "server", "linux", "55 48 89 E5"))


class FixTests(unittest.TestCase):
    ENTRIES = {"Sig": {"kind": "signature", "values": {"linux": "55 48", "windows": "48 89"}},
               "Off": {"kind": "offset", "values": {"linux": 31, "windows": 30}}}

    def test_only_bad_values_are_replaced_with_known_ones(self):
        results = [
            {"name": "Sig", "kind": "signature", "platforms": {
                "linux": {"status": "broken"}, "windows": {"status": "ok", "verification": "verified"}}},
            {"name": "Off", "kind": "offset", "platforms": {
                "linux": {"status": "mismatch", "reference": 32}, "windows": {"status": "match"}}},
        ]
        shipped = {"Sig": {"values": {"linux": "55 48 89", "windows": "48 8B"}}}
        fixes = S.suggest_fixes(results, self.ENTRIES, shipped)
        self.assertEqual(fixes, [
            {"key": "Sig", "platform": "linux", "from": "55 48", "to": "55 48 89", "source": "shipped"},
            {"key": "Off", "platform": "linux", "from": 31, "to": 32, "source": "record"},
        ])

    def test_no_known_value_means_no_fix(self):
        results = [{"name": "Sig", "kind": "signature", "platforms": {"linux": {"status": "ambiguous"}}}]
        self.assertEqual(S.suggest_fixes(results, self.ENTRIES, {}), [])

    def test_a_bad_vtable_slot_takes_the_shipped_index(self):
        results = [{"name": "Sig", "kind": "signature",
                    "platforms": {"linux": {"status": "ok", "vtable": "mismatch"}}}]
        fixes = S.suggest_fixes(results, self.ENTRIES, {}, {"Sig": {"linux_index": 150}},
                                {"Sig": {"linux_index": 151}})
        self.assertEqual(fixes, [{"key": "Sig.vtable", "platform": "linux", "from": 150, "to": 151,
                                  "source": "shipped"}])


class RecordSignatureTests(unittest.TestCase):
    ENTRIES = {"Sig": {"kind": "signature", "values": {"linux": "55 48 8B", "windows": "40 53"}}}
    RECORD = {"func_sig": "55 48 89 E5 41 57", "func_va": "0x1000", "_module": "server"}

    def fixes(self, info, record=RECORD, hit=None, existing=()):
        results = [{"name": "Sig", "kind": "signature", "module": "server", "platforms": {"linux": info}}]
        hit = hit or {"status": "ok", "at": "0x1000"}
        return S.record_signature_fixes(results, self.ENTRIES, list(existing),
                                        lambda name, platform: record, lambda module, platform, pattern, rec: hit)

    def test_a_broken_signature_takes_the_record_signature_that_lands_on_its_function(self):
        self.assertEqual(self.fixes({"status": "broken"}), [
            {"key": "Sig", "platform": "linux", "from": "55 48 8B", "to": "55 48 89 E5 41 57", "source": "record"}])
        self.assertEqual(len(self.fixes({"status": "ok", "func": "mismatch"})), 1)

    def test_nothing_unconfirmed_is_offered(self):
        self.assertEqual(self.fixes({"status": "ok", "func": "ok"}), [])
        self.assertEqual(self.fixes({"status": "broken"}, hit={"status": "ok", "at": "0x2000"}), [])
        self.assertEqual(self.fixes({"status": "broken"}, hit={"status": "ambiguous", "count": 2}), [])
        self.assertEqual(self.fixes({"status": "broken"}, hit={"status": "ok-midfunction", "at": "0x1000"}), [])
        self.assertEqual(self.fixes({"status": "broken"}, record=None), [])
        self.assertEqual(self.fixes({"status": "broken"}, record={**self.RECORD, "func_sig": None}), [])
        self.assertEqual(self.fixes({"status": "broken"}, record={**self.RECORD, "_module": "engine"}), [])

    def test_a_global_or_patch_record_offers_its_own_pattern(self):
        gv = {"gv_sig": "48 8B 05 ? ? ? ? 48 85 C0", "gv_sig_va": "0x2000", "gv_va": "0x9000", "_module": "server"}
        hit = {"status": "ok-globalref", "at": "0x2000", "gv": "ok"}
        self.assertEqual(self.fixes({"status": "broken"}, record=gv, hit=hit)[0]["to"], gv["gv_sig"])
        # the reference no longer addresses the global
        self.assertEqual(self.fixes({"status": "broken"}, record=gv, hit={**hit, "gv": "mismatch"}), [])
        patch = {"patch_sig": "74 0E 48 8B 07", "patch_va": "0x3004", "_module": "server"}
        hit = {"status": "ok-midfunction", "at": "0x3004"}
        self.assertEqual(self.fixes({"status": "broken"}, record=patch, hit=hit)[0]["to"], patch["patch_sig"])
        self.assertEqual(self.fixes({"status": "broken"}, record=patch, hit={**hit, "at": "0x3008"}), [])

    def test_a_shipped_fix_wins(self):
        shipped = [{"key": "Sig", "platform": "linux", "from": "55 48 8B", "to": "55", "source": "shipped"}]
        self.assertEqual(self.fixes({"status": "broken"}, existing=shipped), [])


@unittest.skipUnless(HAVE_BUILD, "needs gamedata/14192 and its snapshot")
class MatchTests(unittest.TestCase):
    def test_a_stale_copy_finds_its_plugin(self):
        with open(MATCHZY, "r", encoding="utf-8") as handle:
            entries, _ = VPG.load_gamedata_text(handle.read())
        entries.pop("CDecoyProjectile_Create")
        plugin, path, _ = S.match_shipped(entries, "matchzy.json", _shipped(BUILD))
        self.assertIn(plugin, ("matchzy", "matchzy-original"))
        self.assertEqual(os.path.basename(path), "matchzy.json")

    def test_stock_css_is_not_taken_for_the_fork(self):
        # The fork ships every stock key plus its own, so both cover a stock file.
        stock = [(p, path, e) for p, path, e in _shipped(BUILD) if p == "CounterStrikeSharp-roflmuffin"]
        if not stock:
            self.skipTest("no stock CounterStrikeSharp file shipped for this build")
        plugin, _, _ = S.match_shipped(dict(stock[0][2]), "gamedata.json", _shipped(BUILD))
        self.assertEqual(plugin, "CounterStrikeSharp-roflmuffin")

    def test_unrelated_keys_match_nothing(self):
        entries = {"NotARealKey": {"values": {"linux": 1}}, "AlsoNot": {"values": {"linux": 2}}}
        self.assertIsNone(S.match_shipped(entries, "x.json", _shipped(BUILD)))


class FakeService(S.Service):
    """The real front end over threads instead of processes, against the one local build."""

    def builds(self):
        return [BUILD]


@unittest.skipUnless(HAVE_BUILD, "needs gamedata/14192 and its snapshot")
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = cf.ThreadPoolExecutor(max_workers=1)
        cls.service = FakeService(cls.executor, bindir="bin-absent-in-tests", workers=1, queue=0, timeout=120)
        cls.server = S.ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(cls.service, max_body=64 * 1024))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.executor.shutdown()

    def post(self, path, payload, raw=None):
        data = raw if raw is not None else json.dumps(payload).encode()
        request = urllib.request.Request(self.url + path, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_a_wrong_offset_is_reported_and_fixed(self):
        with open(MATCHZY, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["CCSPlayer_WeaponServices_SelectItem"]["offsets"]["linux"] = 99
        status, body = self.post("/api/verify", {"gamedata": json.dumps(data), "filename": "matchzy.json"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["matched"]["plugin"], "matchzy")
        row = next(r for r in body["results"] if r["name"] == "CCSPlayer_WeaponServices_SelectItem")
        self.assertEqual(row["platforms"]["linux"]["status"], "mismatch")
        self.assertEqual(row["platforms"]["windows"]["status"], "match")
        self.assertIn({"key": "CCSPlayer_WeaponServices_SelectItem", "platform": "linux", "from": 99, "to": 31,
                       "source": "shipped"}, body["fixes"])
        self.assertGreaterEqual(body["unhealthy"], 1)
        # the same upload again comes from the cache
        self.assertEqual(self.post("/api/verify", {"gamedata": json.dumps(data), "filename": "matchzy.json"}),
                         (status, {**body, "cached": True}))

    def test_rejections(self):
        self.assertEqual(self.post("/api/verify", None, raw=b"not json")[0], 400)
        self.assertEqual(self.post("/api/verify", None, raw=b"x" * (65 * 1024))[0], 413)
        self.assertEqual(self.post("/api/nope", {})[0], 404)
        self.assertEqual(self.post("/api/verify", {"gamedata": "{}", "build": "14100"})[0], 400)
        status, body = self.post("/api/verify", {"gamedata": "just some text"})
        self.assertEqual(status, 200)
        self.assertIn("unrecognised", body["note"])

    def test_check_without_binaries_says_so(self):
        status, body = self.post("/api/check", {"signature": "55 48 89 E5", "platform": "linux"})
        self.assertEqual((status, body["status"]), (200, "no-binary"))


if __name__ == "__main__":
    unittest.main()
