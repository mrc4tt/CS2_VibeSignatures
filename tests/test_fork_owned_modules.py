"""A module this fork adds has to survive an upstream merge.

sync_upstream.sh resolves config conflicts with -X theirs, so a module block added
by hand to configs/<VER>.yaml is gone the next time upstream touches that file. The
module therefore lives in FORK_OWNED_MODULES and is re-created on every run of
ensure_local_gamedata_symbols.py - and it has to be created FIRST, because inject()
resolves each symbol to a module with next(...) and raises StopIteration when the
module is not in the config at all.
"""

import unittest

import yaml

import auto_hunt_headless
import ensure_local_gamedata_symbols as ensure
import verify_plugin_gamedata


UPSTREAM = """modules:
  - name: server
    path_windows: game/bin/win64/server.dll
    path_linux: game/bin/linuxsteamrt64/libserver.so
    skills:
      - name: find-ClientPrint
        expected_output:
          - ClientPrint.{platform}.yaml
    symbols:
      - name: ClientPrint
        category: func
cpp_tests:
  - name: CEntityInstance_MSVC
    symbol: CEntityInstance
"""


class TestForkOwnedModules(unittest.TestCase):
    def test_recreates_the_module_an_upstream_merge_dropped(self):
        patched, added = ensure.enforce_fork_owned_modules(UPSTREAM)
        self.assertEqual(added, len(ensure.FORK_OWNED_MODULES))

        document = yaml.safe_load(patched)
        names = [module["name"] for module in document["modules"]]
        # upstream's own modules are untouched, and cpp_tests is still top-level
        self.assertEqual(names[0], "server")
        self.assertIn("cpp_tests", document)

        for name, path_windows, path_linux, symbols in ensure.FORK_OWNED_MODULES:
            self.assertIn(name, names)
            block = next(m for m in document["modules"] if m["name"] == name)
            self.assertEqual(block["path_windows"], path_windows)
            self.assertEqual(block["path_linux"], path_linux)
            for symbol_name, category, alias in symbols:
                # A real hunting task, declared optional: the older gamevers carry no
                # artifact for a symbol this fork added, and expected_output would make
                # pack fail with "Missing required symbol YAML" (rule 11).
                task = next(s for s in block["skills"] if s["name"] == f"find-{symbol_name}")
                self.assertNotIn("expected_output", task)
                self.assertEqual(task["optional_output"], [f"{symbol_name}.{{platform}}.yaml"])
                entry = next(s for s in block["symbols"] if s["name"] == symbol_name)
                self.assertEqual(entry["category"], category)
                self.assertEqual(entry["alias"], [alias])

    def test_adds_nothing_on_a_config_that_already_has_it(self):
        once, _ = ensure.enforce_fork_owned_modules(UPSTREAM)
        twice, added = ensure.enforce_fork_owned_modules(once)
        self.assertEqual(added, 0)
        self.assertEqual(twice, once)

    def test_every_fork_owned_module_routes_and_resolves_to_a_binary(self):
        for name, path_windows, path_linux, _ in ensure.FORK_OWNED_MODULES:
            # module_for() has to send the symbol's library to this module, or inject()
            # files it under server and the module stays empty.
            self.assertEqual(ensure.module_for(name, "Whatever"), name)
            # Two hand-maintained module -> filename maps, in two files: the one in
            # auto_hunt_headless is what validate_artifacts imports, and
            # verify_plugin_gamedata keeps its own copy. Missing an entry there means
            # the artifact is never checked against its binary.
            for maps in ((auto_hunt_headless.BIN_LINUX, auto_hunt_headless.BIN_WIN),
                         (verify_plugin_gamedata.BIN_LINUX, verify_plugin_gamedata.BIN_WIN)):
                linux_map, windows_map = maps
                self.assertEqual(linux_map[name], path_linux.rsplit("/", 1)[-1])
                self.assertEqual(windows_map[name], path_windows.rsplit("/", 1)[-1])
            self.assertEqual(verify_plugin_gamedata.LIBRARY_TO_MODULE[name], name)


if __name__ == "__main__":
    unittest.main()
