"""sync_plugin_templates follows the plugins' own gamedata files; verify_plugin_gamedata
reports a key with no record of ours as "upstream", not as a gate failure."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync_plugin_templates as S  # noqa: E402
import verify_plugin_gamedata as P  # noqa: E402


class SourcesTests(unittest.TestCase):
    def _generator(self, root, name, seed, enabled=True):
        os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, name, "gamedata.py"), "w") as handle:
            handle.write(f'# Seed source: {seed}\nMODULE_ENABLED = {enabled}\nGAMEDATA_PATH = "gamedata/{name}.json"\n')

    def test_only_enabled_generators_with_a_web_source(self):
        with tempfile.TemporaryDirectory() as root:
            self._generator(root, "bot-hider", "https://raw.githubusercontent.com/x/y/main/gamedata.json")
            self._generator(root, "matchzy", "local")
            self._generator(root, "old", "https://example.org/g.json", enabled=False)
            found = S.sources(root)
        self.assertEqual([(p, u.split("/")[2]) for p, u, _t, _r in found], [("bot-hider", "raw.githubusercontent.com")])

    def test_a_generator_with_two_files_names_each(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "swiftlys2"))
            with open(os.path.join(root, "swiftlys2", "gamedata.py"), "w") as handle:
                handle.write("MODULE_ENABLED = True\n"
                             "# Seed source: https://h/x/signatures.jsonc template=templates/s.jsonc output=core/signatures.jsonc\n"
                             "# Seed source: https://h/x/offsets.jsonc template=templates/o.jsonc output=core/offsets.jsonc\n")
            found = S.sources(root)
        self.assertEqual([(t.split(os.sep)[-1], r) for _p, _u, t, r in found],
                         [("s.jsonc", "core/signatures.jsonc"), ("o.jsonc", "core/offsets.jsonc")])


class DisagreementTests(unittest.TestCase):
    def test_flat_lib_entries_are_read(self):
        self.assertEqual(S._values({"lib": "tier0", "linux": "55 89", "windows": "4C 89"}),
                         ("signatures", {"linux": "55 89", "windows": "4C 89"}, "tier0"))
        self.assertEqual(S._values({"linux": 13, "windows": 14})[0], "offsets")

    def test_an_offset_we_analyse_that_differs_is_reported(self):
        index = {P.fold("CServerSideClient::m_bIsHLTV"): {"linux": {"offset": "0x142"}}}
        plugin = {"CServerSideClient::m_bIsHLTV": {"offsets": {"linux": 322}}}
        ours = {"CServerSideClient::m_bIsHLTV": {"offsets": {"linux": 104}}}
        rows = S.disagreements(index, None, plugin, ours, {})
        self.assertEqual([(r[0], r[1], r[2], r[3]) for r in rows], [("CServerSideClient::m_bIsHLTV", "linux", 322, 104)])

    def test_a_key_we_do_not_analyse_is_not_a_disagreement(self):
        plugin = {"DropReleasePose::OuterDrop": {"signatures": {"linux": "48 85"}}}
        ours = {"DropReleasePose::OuterDrop": {"signatures": {"linux": "48 86"}}}
        self.assertEqual(S.disagreements({}, None, plugin, ours, {}), [])

    def test_a_signature_landing_elsewhere_is_reported(self):
        index = {P.fold("CCSBot::Upkeep"): {"windows": {"func_va": "0x1802e7580"}}}
        plugin = {"CCSBot::Upkeep": {"signatures": {"library": "server", "windows": "48 89 5C"}}}
        ours = {"CCSBot::Upkeep": {"signatures": {"library": "server", "windows": "48 89 7C"}}}
        with mock.patch.object(P, "check_signature", return_value={"status": "ok", "at": "0x1802e2140"}):
            rows = S.disagreements(index, None, plugin, ours, {})
        self.assertIn("0x1802e2140", rows[0][4])


class UpstreamStateTests(unittest.TestCase):
    def test_unrecorded_key_that_resolves_is_upstream(self):
        self.assertEqual(P.verification({"status": "ok", "unrecorded": True}), "upstream")
        self.assertEqual(P.verification({"status": "no-reference", "unrecorded": True}), "upstream")

    def test_unrecorded_broken_signature_still_fails(self):
        self.assertEqual(P.verification({"status": "broken", "unrecorded": True}), "contradicted")

    def test_a_patch_site_landing_on_the_record_is_verified(self):
        self.assertEqual(P.verification({"status": "ok-midfunction", "func": "ok"}), "verified")
        self.assertEqual(P.verification({"status": "ok-midfunction", "func": "mismatch"}), "contradicted")

    def test_recorded_but_unconfirmed_is_still_unverified(self):
        self.assertEqual(P.verification({"status": "match", "value": 8}), "unverified")


if __name__ == "__main__":
    unittest.main()
