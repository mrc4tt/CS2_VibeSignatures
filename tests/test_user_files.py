"""The user-file store hands out two secrets and keeps neither in a form that grants
anything; the read link serves the current text, the manage token alone changes it."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import concurrent.futures as cf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gamedata_patch as GP  # noqa: E402
import user_files as UF  # noqa: E402
import verify_service as S  # noqa: E402

CSS = json.dumps({"Foo": {"signatures": {"library": "server", "linux": "55 48 89 E5", "windows": "48 89 5C"}},
                  "Bar": {"offsets": {"linux": 31, "windows": 30}}}, indent=2)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_fetch_manage_delete(self):
        file_id, token = UF.create(CSS, "../../etc/gamedata.json", "14196", root=self.root, now=1000)
        self.assertRegex(file_id, UF.ID_RE)
        self.assertRegex(token, UF.TOKEN_RE)
        # the token itself is written nowhere
        for folder, _dirs, names in os.walk(self.root):
            for name in names:
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    self.assertNotIn(token, handle.read() + name)
        self.assertEqual(UF.resolve_token(token, self.root), file_id)
        self.assertEqual(UF.fetch(file_id, self.root, now=2000), ("gamedata.json", CSS))
        self.assertEqual(UF.load_meta(file_id, self.root)["last_fetch"], 2000)
        UF.fetch(file_id, self.root, now=2100)  # throttled: no write within the hour
        self.assertEqual(UF.load_meta(file_id, self.root)["last_fetch"], 2000)
        UF.record_update(file_id, "14197", CSS.replace("55 48 89 E5", "55 48 8B"),
                         [{"key": "Foo", "platform": "linux", "from": "55 48 89 E5", "to": "55 48 8B"}], [],
                         root=self.root)
        self.assertIn("55 48 8B", UF.fetch(file_id, self.root)[1])
        meta = UF.public_meta(file_id, self.root)
        self.assertEqual((meta["baseline_build"], len(meta["history"])), ("14197", 1))
        UF.delete(file_id, token=token, root=self.root)
        with self.assertRaises(UF.StoreError):
            UF.fetch(file_id, self.root)
        with self.assertRaises(UF.StoreError):
            UF.resolve_token(token, self.root)

    def test_rejects_paths_and_bad_webhooks(self):
        for bad in ("../x", "a" * 21, "", None, "a/b" + "c" * 19):
            with self.assertRaises(UF.StoreError):
                UF.fetch(bad, self.root)
        with self.assertRaises(UF.StoreError):
            UF.create(CSS, "x.json", "14196", webhook="https://evil.example/api/webhooks/1/2", root=self.root)
        ok = "https://discord.com/api/webhooks/123456789/" + "a" * 60
        file_id, _ = UF.create(CSS, "x.json", "14196", webhook=ok, root=self.root)
        self.assertTrue(UF.public_meta(file_id, self.root)["webhook"])
        self.assertNotIn(ok, json.dumps(UF.public_meta(file_id, self.root)))

    def test_expiry(self):
        old, _ = UF.create(CSS, "a.json", "14196", root=self.root, now=1000)
        fresh, _ = UF.create(CSS, "b.json", "14196", root=self.root, now=1000 + 100 * 86400)
        self.assertEqual(UF.expire(self.root, now=1000 + 100 * 86400), [old])
        self.assertEqual(UF.list_ids(self.root), [fresh])


class PatchTests(unittest.TestCase):
    def test_json_value_replaced_in_its_own_key_only(self):
        text = CSS
        out, applied, skipped = GP.apply_fixes(text, [
            {"key": "Foo", "platform": "linux", "from": "55 48 89 E5", "to": "55 48 8B ??"},
            {"key": "Bar", "platform": "windows", "from": 30, "to": 32},
            {"key": "Nope", "platform": "linux", "from": 1, "to": 2}])
        self.assertEqual((applied, skipped), (2, [{"key": "Nope", "platform": "linux", "reason": "notFound"}]))
        data = json.loads(out)
        self.assertEqual(data["Foo"]["signatures"]["linux"], "55 48 8B ??")
        self.assertEqual(data["Foo"]["signatures"]["windows"], "48 89 5C")
        self.assertEqual(data["Bar"]["offsets"], {"linux": 31, "windows": 32})

    def test_keyvalues_escapes(self):
        text = '"Games"\n{\n "csgo"\n {\n  "Signatures"\n  {\n   "Foo"\n   {\n    "linux" "\\x55\\x48\\x2A"\n' \
               '    "windows" "\\x48\\x89"\n   }\n  }\n }\n}\n'
        out, applied, _ = GP.apply_fixes(text, [{"key": "Foo", "platform": "linux", "from": "55 48 ??",
                                                 "to": "55 8B ?? E5"}])
        self.assertEqual(applied, 1)
        self.assertIn('"linux" "\\x55\\x8B\\x2A\\xE5"', out)
        self.assertIn('"windows" "\\x48\\x89"', out)

    def test_vtable_index(self):
        text = json.dumps({"K": {"signatures": {"linux": "55"}, "vtable": {"linux_index": 3, "windows_index": 4}}})
        out, applied, _ = GP.apply_fixes(text, [{"key": "K.vtable", "platform": "windows", "from": 4, "to": 5}])
        self.assertEqual((applied, json.loads(out)["K"]["vtable"]), (1, {"linux_index": 3, "windows_index": 5}))


class UpdaterTests(unittest.TestCase):
    def test_class_candidates_longest_first(self):
        import user_gamedata as UG
        self.assertEqual(UG.split_key("CCSPlayer_ItemServices_GiveNamedItem"),
                         [("CCSPlayer_ItemServices", "GiveNamedItem"), ("CCSPlayer", "ItemServices_GiveNamedItem")])
        self.assertEqual(UG.split_key("CBaseEntity::Teleport"), [("CBaseEntity", "Teleport")])
        self.assertEqual(UG.method_of("CBaseEntity_Teleport"), "teleport")

    def test_new_value_keeps_the_file_wildcard_style(self):
        import user_gamedata as UG
        self.assertEqual(UG.in_style_of("55 ? 48", "48 ?? 8B"), "48 ? 8B")
        self.assertEqual(UG.in_style_of("55 ?? 48", "48 ? 8B"), "48 ?? 8B")
        self.assertEqual(UG.in_style_of(31, 32), 32)


class Service(S.Service):
    def builds(self):
        return ["14196", "14195"]


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.executor = cf.ThreadPoolExecutor(max_workers=1)
        cls.service = Service(cls.executor, workers=1, queue=0, files_root=cls.tmp.name)
        cls.server = S.ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(cls.service))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.executor.shutdown()
        cls.tmp.cleanup()

    def call(self, method, path, payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Manage-Token"] = token
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode()
                return response.status, (json.loads(body) if "json" in response.headers["Content-Type"]
                                         and path.startswith("/api/files/manage") or method == "POST"
                                         else body)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_round_trip(self):
        status, made = self.call("POST", "/api/files", {"gamedata": CSS, "filename": "gamedata.json",
                                                        "build": "14195"})
        self.assertEqual(status, 201, made)
        self.assertEqual(made["build"], "14195")
        status, text = self.call("GET", made["url"])
        self.assertEqual((status, text), (200, CSS))
        status, meta = self.call("GET", "/api/files/manage", token=made["manage"])
        self.assertEqual((status, meta["id"], meta["current"]), (200, made["id"], CSS))
        status, meta = self.call("PUT", "/api/files/manage", {"filename": "renamed.json"}, token=made["manage"])
        self.assertEqual((status, meta["filename"]), (200, "renamed.json"))
        self.assertEqual(self.call("DELETE", "/api/files/manage", token=made["manage"])[0], 200)
        self.assertEqual(self.call("GET", made["url"])[0], 404)
        self.assertEqual(self.call("GET", "/api/files/manage", token=made["manage"])[0], 404)

    def test_rejections(self):
        self.assertEqual(self.call("POST", "/api/files", {"gamedata": "hello"})[0], 400)
        self.assertEqual(self.call("POST", "/api/files", {"gamedata": CSS, "build": "14100"})[0], 400)
        self.assertEqual(self.call("GET", "/api/files/manage", token="x" * 43)[0], 404)
        self.assertEqual(self.call("GET", "/api/files/manage")[0], 404)
        self.assertEqual(self.call("GET", "/api/files/../../etc/passwd")[0], 404)


if __name__ == "__main__":
    unittest.main()
