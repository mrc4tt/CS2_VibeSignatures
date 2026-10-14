"""The defect museum: every wrong value this fork has shipped or nearly shipped, put back
into the newest build, must be contradicted by verify_plugin_gamedata against the real
binaries - and its correction verified. A change that makes the verifier blind to one of
these again fails here, not on a server.

Each exhibit is the historical record exactly as it was (offset, the offset_sig it was
read from), placed into a copy of this build's snapshot. Binary-backed, so it is skipped
where bin/<build>/ is not hydrated (CI); the pure-logic tests cover the rules there.
"""
import copy
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import verify_plugin_gamedata as P  # noqa: E402

BUILD = "14190"
SNAPSHOT = os.path.join(REPO, "gamesymbols", f"{BUILD}.yaml")
HAVE_BINARIES = (os.path.isfile(os.path.join(REPO, "bin", BUILD, "engine", "libengine2.so"))
                 and os.path.isfile(os.path.join(REPO, "bin", BUILD, "server", "libserver.so"))
                 and P.V._MD is not None and os.path.isfile(SNAPSHOT))

# (exhibit, symbol, platform, record fields as they were shipped)
EXHIBITS = (
    ("14182-14190 linux m_Server: dword store to 0x4c, the qword is at 0x50",
     "CServerSideClient_m_Server", "linux",
     {"offset": "0x4c", "offset_sig": "89 57 4C 31 D2 48 89 77 50 31 F6 66 89 47 60 66 89 57 68 0F 29 47 70 0F 29"}),
    ("14182-14190 linux m_SteamID: a byte test at 0xa0",
     "CServerSideClient_m_SteamID", "linux",
     {"offset": "0xa0", "offset_sig": "0F B6 87 A0 00 00 00 84 C0 75 6B 48 8B 83 AB 00 00 00 C7 45 D4 01 00 00 00 48"}),
    ("14182-14190 linux m_NetChannel: a byte compare at 0xa0",
     "CServerSideClient_m_NetChannel", "linux",
     {"offset": "0xa0", "offset_sig": "41 80 BF A0 00 00 00 00 49 89 5F 58 45 88 67 60 75 28 48 8B"}),
    ("14182-14190 linux m_nEntityIndex: 0x48, m_nClientSlot's offset",
     "CServerSideClient_m_nEntityIndex", "linux",
     {"offset": "0x48", "offset_sig": "8B 43 48 48 89 DF 83 C0 01 89 43 4C"}),
    ("14182-14190 windows m_bFakePlayer: a byte getter of another field at 0x9f8",
     "CServerSideClient_m_bFakePlayer", "windows",
     {"offset": "0x9f8", "offset_sig": "0F B6 81 F8 09 00 00"}),
    ("14182-14185 linux m_designerName: the neighbouring EHandle's 0x10",
     "CEntityIdentity_m_designerName", "linux",
     {"offset": "0x10", "offset_sig": "66 81 48 10 FF 7F 39 8F"}),
)

# (exhibit, symbol, platform, wrong vfunc_index): a slot that names the NEXT virtual
SLOT_EXHIBITS = (
    ("vtidx_FinishMove-type: index one past the function (windows)", "CCSPlayer_WeaponServices_DropWeapon", "windows", 29),
    ("vtidx_DropWeapon-type: index from another class layout (linux)", "CCSPlayer_WeaponServices_DropWeapon", "linux", 25),
)


@unittest.skipUnless(HAVE_BINARIES, f"needs bin/{BUILD} binaries, capstone and the {BUILD} snapshot")
class DefectMuseum(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = P.load_snapshot_index(SNAPSHOT)
        cls.binaries = P.Binaries(os.path.join(REPO, "bin"), BUILD)
        cls.saved = dict(P._SNAPSHOT_INDEX)

    @classmethod
    def tearDownClass(cls):
        P._SNAPSHOT_INDEX.clear()
        P._SNAPSHOT_INDEX.update(cls.saved)
        P._MEMBERS.clear()

    def _judge(self, symbol, platform, overrides):
        """The row verify_plugin_gamedata builds for `symbol` with one platform's record
        replaced by the exhibit, judged against the real binaries."""
        index = copy.deepcopy(self.index)
        index[P.fold(symbol)][platform].update(overrides)
        P._SNAPSHOT_INDEX.clear()
        P._SNAPSHOT_INDEX.update(index)
        P._MEMBERS.clear()
        row = {"name": symbol, "kind": "offset", "module": "engine", "platforms": {}}
        for plat in ("linux", "windows"):
            record = index[P.fold(symbol)][plat]
            value = P._int(record.get("offset")) if record.get("offset") is not None else record.get("vfunc_index")
            row["platforms"][plat] = P.check_offset(index, self.binaries, symbol, plat, value)
        P.anchor_disagreement(row, self.binaries)
        P.cross_platform(row)
        for cell in row["platforms"].values():
            cell["verification"] = P.verification(cell)   # what _report records
        return {plat: cell["verification"] for plat, cell in row["platforms"].items()}, row

    def test_every_exhibit_is_contradicted(self):
        for exhibit, symbol, platform, overrides in EXHIBITS:
            with self.subTest(exhibit):
                states, row = self._judge(symbol, platform, overrides)
                self.assertEqual(states[platform], "contradicted",
                                 f"{exhibit}: verifier now says {states[platform]}: {row['platforms'][platform]}")

    def test_the_correction_verifies(self):
        for exhibit, symbol, platform, _overrides in EXHIBITS:
            with self.subTest(exhibit):
                states, row = self._judge(symbol, platform, {})
                self.assertEqual(states[platform], "verified", f"{exhibit}: {row['platforms'][platform]}")

    def test_auto_repair_plans_the_right_slot(self):
        import auto_repair
        for exhibit, symbol, platform, wrong in SLOT_EXHIBITS:
            with self.subTest(exhibit):
                _states, row = self._judge(symbol, platform, {"vfunc_index": wrong})
                right = self.index[P.fold(symbol)][platform]["vfunc_index"]
                repairs, left = auto_repair.plan(BUILD, [{"results": [row]}], self.binaries)
                self.assertEqual([(r[0], r[1], r[3]) for r in repairs], [(symbol, platform, right)], left)

    def test_auto_repair_plans_the_right_instruction(self):
        import auto_repair
        expected = {"CServerSideClient_m_Server": 0x50, "CServerSideClient_m_SteamID": 0xab,
                    "CServerSideClient_m_NetChannel": 0x58, "CServerSideClient_m_nEntityIndex": 0x4c,
                    "CServerSideClient_m_bFakePlayer": 0xa0}
        for exhibit, symbol, platform, overrides in EXHIBITS:
            if symbol not in expected:
                continue
            with self.subTest(exhibit):
                _states, row = self._judge(symbol, platform, overrides)
                repairs, left = auto_repair.plan(BUILD, [{"results": [row]}], self.binaries)
                self.assertEqual([(r[0], r[3]) for r in repairs], [(symbol, expected[symbol])], left)

    def test_a_slot_naming_the_next_virtual_is_contradicted(self):
        for exhibit, symbol, platform, wrong in SLOT_EXHIBITS:
            with self.subTest(exhibit):
                states, row = self._judge(symbol, platform, {"vfunc_index": wrong})
                self.assertEqual(states[platform], "contradicted", f"{exhibit}: {row['platforms'][platform]}")


if __name__ == "__main__":
    unittest.main()
