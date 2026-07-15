import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import update_gamedata
from gamesymbol_store import DirectorySymbolStore


class TestLoadAllYamlData(unittest.TestCase):
    def test_load_all_yaml_data_skips_symbol_on_non_matching_platform(self) -> None:
        config = {
            "modules": [
                {
                    "name": "engine",
                    "symbols": [
                        {"name": "CommonGlobal", "category": "gv"},
                        {
                            "name": "WindowsOnlyGlobal",
                            "category": "gv",
                            "platform": "windows",
                        },
                    ],
                }
            ]
        }

        with TemporaryDirectory() as temp_dir:
            engine_dir = Path(temp_dir) / "14141" / "engine"
            engine_dir.mkdir(parents=True)
            (engine_dir / "CommonGlobal.windows.yaml").write_text(
                "gv_name: CommonGlobal\ngv_va: '0x180100000'\n",
                encoding="utf-8",
            )
            (engine_dir / "CommonGlobal.linux.yaml").write_text(
                "gv_name: CommonGlobal\ngv_va: '0x100000'\n",
                encoding="utf-8",
            )
            (engine_dir / "WindowsOnlyGlobal.windows.yaml").write_text(
                "gv_name: WindowsOnlyGlobal\ngv_va: '0x180200000'\n",
                encoding="utf-8",
            )

            store = DirectorySymbolStore(temp_dir, "14141")
            yaml_data, missing_symbols = update_gamedata.load_all_yaml_data(
                config, store, ["windows", "linux"], debug=True
            )
            linux_only_data, _missing = update_gamedata.load_all_yaml_data(config, store, ["linux"], debug=True)

        self.assertIn("windows", yaml_data["WindowsOnlyGlobal"])
        self.assertNotIn("linux", yaml_data["WindowsOnlyGlobal"])
        self.assertNotIn("WindowsOnlyGlobal", linux_only_data)
        self.assertFalse(
            any(item["name"] == "WindowsOnlyGlobal" and item["platform"] == "linux" for item in missing_symbols)
        )

    def test_structmember_prefers_new_format_then_uses_store_legacy_fallback(self) -> None:
        config = {
            "modules": [
                {
                    "name": "server",
                    "symbols": [
                        {
                            "name": "CEntity_NewMember",
                            "category": "structmember",
                            "struct": "CEntity",
                            "member": "m_new",
                        },
                        {
                            "name": "CLegacy_OldMember",
                            "category": "structmember",
                            "struct": "CLegacy",
                            "member": "m_old",
                        },
                    ],
                }
            ]
        }
        with TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir) / "14141" / "server"
            module_dir.mkdir(parents=True)
            (module_dir / "CEntity_NewMember.windows.yaml").write_text(
                "struct_name: CEntity\nmember_name: m_new\noffset: 0x20\n",
                encoding="utf-8",
            )
            (module_dir / "CEntity.windows.yaml").write_text(
                "struct_name: CEntity\nstruct_offsets:\n  0x10: m_new 4\n",
                encoding="utf-8",
            )
            (module_dir / "CLegacy.windows.yaml").write_text(
                "struct_name: CLegacy\nstruct_offsets:\n  0x30: m_old 4\n",
                encoding="utf-8",
            )
            data, _missing = update_gamedata.load_all_yaml_data(
                config,
                DirectorySymbolStore(temp_dir, "14141"),
                ["windows"],
                debug=True,
            )

        self.assertEqual(0x20, data["CEntity_NewMember"]["windows"]["struct_member_offset"])
        self.assertEqual(0x30, data["CLegacy_OldMember"]["windows"]["struct_member_offset"])

    def test_patch_alias_and_missing_diagnostics_use_canonical_store_keys(self) -> None:
        config = {
            "modules": [
                {
                    "name": "server",
                    "symbols": [
                        {
                            "name": "CCSPlayer_MovementServices_FullWalkMove_SpeedClamp",
                            "category": "patch",
                        },
                        {"name": "MissingFunction", "category": "func"},
                    ],
                }
            ]
        }
        with TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir) / "14141" / "server"
            module_dir.mkdir(parents=True)
            (module_dir / "ServerMovementUnlock.windows.yaml").write_text(
                "patch_bytes: 90 90\n",
                encoding="utf-8",
            )
            data, missing = update_gamedata.load_all_yaml_data(
                config,
                DirectorySymbolStore(temp_dir, "14141"),
                ["windows"],
                debug=True,
            )

        patch_name = "CCSPlayer_MovementServices_FullWalkMove_SpeedClamp"
        self.assertEqual("90 90", data[patch_name]["windows"]["patch_bytes"])
        self.assertEqual("server/MissingFunction.windows.yaml", missing[0]["path"])


if __name__ == "__main__":
    unittest.main()
