"""patch_mam_source.py rewrites MultiAddonManager's constexpr literals and nothing else.

The deploy commits whatever it writes into a plugin's C++ source and pushes it, so a
literal written into the wrong platform's block, or one byte changed outside a
literal, would ship. These pin both.
"""

import copy
import unittest

import patch_mam_source as P

SOURCE = """\
// Signatures
#ifdef PLATFORM_WINDOWS
constexpr const char *g_HostStateRequest_Sig = "48 89 74 24 ? 57";
constexpr const char *g_ReplyConnection_Sig = "48 8B C4 55";
constexpr const char *g_ScriptGetAddon_Sig = "40 56 48 83";
#else
constexpr const char *g_HostStateRequest_Sig = "55 48 89 E5";
constexpr const char *g_ReplyConnection_Sig = "55 B9 ? ? ? ? 41 B8";
constexpr const char *g_ScriptGetAddon_Sig = "55 48 89 E5 41 55";
#endif


// Offsets
"""

GAMEDATA = {
    "CHostStateMgr::StartNewRequest": {"signatures": {"windows": "48 89 74 24 ? 57", "linux": "55 48 89 E5"}},
    "CNetworkGameServer::ReplyConnection": {
        "signatures": {"windows": "48 8B C4 55", "linux": "55 B9 ? ? ? ? 41 B8 ? ? ? ? 48 89 E5"}
    },
    "ScriptGetAddon": {"signatures": {"windows": "40 56 48 83 ?", "linux": "55 48 89 E5 41 55 ?"}},
    "CNetworkGameServer::ServerAddons": {"offsets": {"windows": 376, "linux": 376}},
    "CNetworkGameServer::ClientList": {"offsets": {"windows": 624, "linux": 624}},
}


class PatchMamSource(unittest.TestCase):
    def test_reports_only_real_differences(self):
        diffs = P.differences(GAMEDATA, SOURCE)
        # trailing wildcards on ScriptGetAddon are not a difference
        self.assertEqual(
            [(var, platform) for var, platform, _, _ in diffs],
            [("g_ReplyConnection_Sig", "linux")],
        )

    def test_patch_touches_only_the_literals_in_the_right_block(self):
        patched = P.patch(GAMEDATA, SOURCE)
        expected = SOURCE.replace(
            '"55 B9 ? ? ? ? 41 B8"', '"55 B9 ? ? ? ? 41 B8 ? ? ? ? 48 89 E5"'
        )
        self.assertEqual(patched, expected)
        self.assertEqual(P.differences(GAMEDATA, patched), [])

    def test_offsets_are_not_required_since_the_sdk_reads_them(self):
        # b4353a1 dropped the constexpr offsets; their absence must not fail the deploy
        self.assertNotIn("constexpr int", SOURCE)
        self.assertEqual(P.OFFSETS, {})
        P.patch(GAMEDATA, SOURCE)

    def test_missing_literal_is_refused(self):
        with self.assertRaises(P.PatchError):
            P.patch(GAMEDATA, SOURCE.replace("g_ScriptGetAddon_Sig", "g_RenamedSig"))

    def test_deploy_script_patches_and_pushes_the_source(self):
        import os

        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy_local_plugins.sh")
        with open(path, encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn("patch_mam_source.py", script)
        self.assertIn('commit_push "$HOME/customGIT/MultiAddonManager" src/multiaddonmanager.cpp', script)


if __name__ == "__main__":
    unittest.main()
