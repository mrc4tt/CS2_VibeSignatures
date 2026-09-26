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
