import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ensure_seed_preprocessors as E


class VtableRenderTests(unittest.TestCase):
    """find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_vtable-server was
    generated with its field list keyed by the artifact stem, so preprocessing always
    failed with "unknown desired-fields symbol" and an agent wrote a func-shaped vtable."""

    def _render(self, mangled=()):
        return E.render(
            "CFoo_CBar_vtable", "vtable", ["vtable_class", "vtable_va"], "CFoo_CBar", mangled
        )

    def test_fields_are_keyed_by_the_class_name(self):
        namespace = {}
        exec(compile(self._render(), "gen", "exec"), namespace)
        self.assertEqual("CFoo_CBar", namespace["GENERATE_YAML_DESIRED_FIELDS"][0][0])
        self.assertEqual(["CFoo_CBar"], namespace["TARGETS"])
        self.assertNotIn("MANGLED_CLASS_NAMES", namespace)

    def test_mangled_names_are_passed_through(self):
        text = self._render(["_ZTV4CFooI4CBarE", "??_7?$CFoo@VCBar@@@@6B@"])
        namespace = {}
        exec(compile(text, "gen", "exec"), namespace)
        self.assertEqual({"CFoo_CBar": ["_ZTV4CFooI4CBarE", "??_7?$CFoo@VCBar@@@@6B@"]},
                         namespace["MANGLED_CLASS_NAMES"])
        self.assertIn("mangled_class_names=MANGLED_CLASS_NAMES", text)

    def test_other_categories_keep_the_symbol_key(self):
        text = E.render("CFoo_Bar", "func", ["func_name", "func_va"], "CFoo_Bar")
        namespace = {}
        exec(compile(text, "gen", "exec"), namespace)
        self.assertEqual("CFoo_Bar", namespace["GENERATE_YAML_DESIRED_FIELDS"][0][0])
        self.assertNotIn("@", text)

    def test_mangled_names_come_from_the_baseline_symbol(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.linux.yaml")
            with open(path, "w") as handle:
                handle.write("vtable_class: CFoo_CBar\nvtable_symbol: _ZTV4CFooI4CBarE + 0x10\n")
            self.assertEqual(["_ZTV4CFooI4CBarE"], E.mangled_names([path]))


class ExistingPreprocessorTests(unittest.TestCase):
    """The runner loads ida_preprocessor_scripts/<task>.py only. A sibling task's
    find-X-linux.py counted as covering find-X, so the windows DestroyGameSystem task
    never got a script and its artifact went missing from 14193 on."""

    def test_only_the_task_name_counts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("find-X-linux.py", "find-X-decompiles.py"):
                open(os.path.join(tmp, name), "w").close()
            self.assertIsNone(E.existing_preprocessor(tmp, "X"))
            self.assertEqual(os.path.join(tmp, "find-X-linux.py"), E.existing_preprocessor(tmp, "X-linux"))
            open(os.path.join(tmp, "find-X.py"), "w").close()
            self.assertEqual(os.path.join(tmp, "find-X.py"), E.existing_preprocessor(tmp, "X"))

    def test_every_task_of_the_newest_config_has_its_own_script(self):
        import yaml

        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = E.newest_config()
        if not config:
            self.skipTest("no config")
        cfg = yaml.safe_load(open(os.path.join(repo, config), encoding="utf-8"))
        missing = [
            task["name"]
            for module in cfg.get("modules", [])
            for task in module.get("skills", [])
            if task.get("name", "").startswith("find-")
            and not os.path.exists(os.path.join(repo, "ida_preprocessor_scripts", f"{task['name']}.py"))
        ]
        self.assertEqual([], missing)
