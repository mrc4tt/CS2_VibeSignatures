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
            for symbol_name, category, alias, *task_name in symbols:
                # A real hunting task, declared optional: the older gamevers carry no
                # artifact for a symbol this fork added, and expected_output would make
                # pack fail with "Missing required symbol YAML" (rule 11).
                task_name = task_name[0] if task_name else f"find-{symbol_name}"
                task = next(s for s in block["skills"] if s["name"] == task_name)
                self.assertNotIn("expected_output", task)
                self.assertEqual(task["optional_output"], [f"{symbol_name}.{{platform}}.yaml"])
                entry = next(s for s in block["symbols"] if s["name"] == symbol_name)
                self.assertEqual(entry["category"], category)
                if alias:
                    self.assertEqual(entry["alias"], [alias])
                else:
                    self.assertNotIn("alias", entry)

    def test_vtables_land_in_existing_modules_once(self):
        config = UPSTREAM.replace("cpp_tests:\n", (
            "  - name: engine\n"
            "    path_windows: game/bin/win64/engine2.dll\n"
            "    path_linux: game/bin/linuxsteamrt64/libengine2.so\n"
            "    skills:\n"
            "      - name: find-CEngineServer_vtable\n"
            "        expected_output:\n"
            "          - CEngineServer_vtable.{platform}.yaml\n"
            "    symbols:\n"
            "      - name: CEngineServer_vtable\n"
            "        category: vtable\n"
            "cpp_tests:\n"
        ), 1)
        config, _ = ensure.enforce_fork_owned_modules(config)
        once, added = ensure.enforce_fork_owned_vtables(config)
        self.assertGreater(added, 0)
        twice, again = ensure.enforce_fork_owned_vtables(once)
        self.assertEqual(again, 0)
        self.assertEqual(twice, once)

        document = yaml.safe_load(once)
        for cls, module in ensure.FORK_OWNED_VTABLES:
            block = next(m for m in document["modules"] if m["name"] == module)
            task = next(s for s in block["skills"] if s["name"] == f"find-{cls}_vtable")
            # optional: a vtable for the SDK check must never stop a gamedata release
            self.assertNotIn("expected_output", task)
            self.assertEqual(task["optional_output"], [f"{cls}_vtable.{{platform}}.yaml"])
            entry = next(s for s in block["symbols"] if s["name"] == f"{cls}_vtable")
            self.assertEqual(entry["category"], "vtable")

    def test_adds_nothing_on_a_config_that_already_has_it(self):
        once, _ = ensure.enforce_fork_owned_modules(UPSTREAM)
        twice, added = ensure.enforce_fork_owned_modules(once)
        self.assertEqual(added, 0)
        self.assertEqual(twice, once)

    def test_completes_a_block_built_before_its_entry_was_listed(self):
        full, _ = ensure.enforce_fork_owned_modules(UPSTREAM)
        lines = full.split("\n")
        # drop the last symbol and task of soundsystem, as an older config would lack them
        symbol_name, _category, _alias, task_name = next(
            symbols for name, _w, _l, symbols in ensure.FORK_OWNED_MODULES if name == "soundsystem"
        )[-1]
        at = lines.index(f"      - name: {task_name}")
        del lines[at:at + 3]
        at = lines.index(f"      - name: {symbol_name}", lines.index("  - name: soundsystem"))
        del lines[at:at + 2]
        stale = "\n".join(lines)

        completed, added = ensure.enforce_fork_owned_modules(stale)
        self.assertEqual(added, 2)
        def by_name(text):
            return {m["name"]: {key: sorted(map(repr, m[key])) if isinstance(m[key], list) else m[key]
                                for key in m}
                    for m in yaml.safe_load(text)["modules"]}
        self.assertEqual(by_name(completed), by_name(full))
        again, more = ensure.enforce_fork_owned_modules(completed)
        self.assertEqual((again, more), (completed, 0))

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


RETIRED = """modules:
  - name: vphysics2
    path_windows: game/bin/win64/vphysics2.dll
    path_linux: game/bin/linuxsteamrt64/libvphysics2.so
    skills:
      - name: find-CVPhys2World_vtable
  - name: server
    path_windows: game/bin/win64/server.dll
    path_linux: game/bin/linuxsteamrt64/libserver.so
  - name: matchmaking
    path_windows: game/csgo/bin/win64/matchmaking.dll
    path_linux: game/csgo/bin/linuxsteamrt64/libmatchmaking.so
cpp_tests:
  - name: CEntityInstance_MSVC
    symbol: CEntityInstance
"""


class TestForkOwnedModuleRemovals(unittest.TestCase):
    def test_drops_retired_modules_and_keeps_the_rest(self):
        patched, removed = ensure.enforce_fork_owned_module_removals(RETIRED)
        self.assertEqual(removed, 2)
        document = yaml.safe_load(patched)
        self.assertEqual([m["name"] for m in document["modules"]], ["server"])
        # the last module block must not take cpp_tests: with it
        self.assertEqual(document["cpp_tests"][0]["name"], "CEntityInstance_MSVC")

    def test_is_idempotent(self):
        once, _ = ensure.enforce_fork_owned_module_removals(RETIRED)
        self.assertEqual(ensure.enforce_fork_owned_module_removals(once), (once, 0))

    def test_never_retires_a_module_the_fork_creates(self):
        created = {name for name, *_ in ensure.FORK_OWNED_MODULES}
        retired = {name for name, _why in ensure.FORK_OWNED_MODULE_REMOVALS}
        self.assertFalse(created & retired)
