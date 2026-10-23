"""A plugin-only key lives in its generator's KEY_SYMBOL_OVERRIDES, not the shared ALIAS_OVERRIDES."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ensure_local_gamedata_symbols as E  # noqa: E402
from gamedata_utils import enabled_generator_key_overrides, generator_key_overrides  # noqa: E402


class ReaderTests(unittest.TestCase):
    def _generator(self, root, name, body):
        os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, name, "gamedata.py"), "w") as handle:
            handle.write(body)

    def test_reads_the_table_with_comments_inside(self):
        with tempfile.TemporaryDirectory() as root:
            self._generator(root, "p", 'KEY_SYMBOL_OVERRIDES = {\n    # why\n    "A::B": "A_C",\n}\n')
            self.assertEqual(generator_key_overrides("p", root), {"A::B": "A_C"})
            self.assertEqual(generator_key_overrides("missing", root), {})

    def test_a_file_scoped_route_applies_to_that_file_only(self):
        with tempfile.TemporaryDirectory() as root:
            self._generator(root, "p", 'KEY_SYMBOL_OVERRIDES = {"A": "S"}\n'
                                       'KEY_SYMBOL_OVERRIDES_BY_OUTPUT = {"sigs.jsonc": {"D": "Handler"}}\n')
            self.assertEqual(generator_key_overrides("p", root, output="x/sigs.jsonc"), {"A": "S", "D": "Handler"})
            self.assertEqual(generator_key_overrides("p", root, output="x/offsets.jsonc"), {"A": "S"})
            self.assertEqual(generator_key_overrides("p", root), {"A": "S", "D": "Handler"})

    def test_a_disabled_generator_routes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            self._generator(root, "on", 'KEY_SYMBOL_OVERRIDES = {"K": "S"}\n')
            self._generator(root, "off", 'MODULE_ENABLED = False\nKEY_SYMBOL_OVERRIDES = {"K2": "S2"}\n')
            self.assertEqual(enabled_generator_key_overrides(root), {"on": {"K": "S"}})


class SeparationTests(unittest.TestCase):
    def test_no_key_is_both_shared_and_plugin_owned(self):
        owned = {key for table in enabled_generator_key_overrides().values() for key in table}
        self.assertEqual(owned & set(E.ALIAS_OVERRIDES), set())

    def test_no_two_plugins_route_one_key_differently(self):
        seen = {}
        for plugin, table in enabled_generator_key_overrides().items():
            for key, symbol in table.items():
                self.assertEqual(seen.setdefault(key, symbol), symbol, f"{key} in {plugin}")


if __name__ == "__main__":
    unittest.main()
