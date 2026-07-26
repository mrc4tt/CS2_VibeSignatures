import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.ida_preprocessor_test_support import load_module as _load_module


ON_EVENT_MAP_CALLBACKS_CLIENT_SCRIPT_PATH = Path(
    "ida_preprocessor_scripts/find-CLoopModeGame_OnEventMapCallbacks-client.py"
)
REALLOCATING_FACTORY_SCRIPT_PATH = Path(
    "ida_preprocessor_scripts/find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_vtable.py"
)
REALLOCATING_FACTORY_DEALLOCATE_SCRIPT_PATH = Path(
    "ida_preprocessor_scripts/find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem-impl.py"
)
CSPAWNGROUP_VTABLE2_SCRIPT_PATH = Path("ida_preprocessor_scripts/find-CSpawnGroupMgrGameSystem_vtable2.py")
CSPAWNGROUP_DOES_REALLOCATE_SCRIPT_PATH = Path(
    "ida_preprocessor_scripts/find-CSpawnGroupMgrGameSystem_DoesGameSystemReallocate.py"
)
CLOOPMODE_FACTORY_GAME_INIT_SCRIPT_PATH = Path("ida_preprocessor_scripts/find-CLoopModeFactory_CLoopModeGame_Init.py")
CONNECT_INTERFACES_SCRIPT_PATH = Path("ida_preprocessor_scripts/find-ConnectInterfaces.py")


class TestFindCLoopModeGameOnEventMapCallbacksClient(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_skill_forwards_register_event_listener_contract(
        self,
    ) -> None:
        module = _load_module(
            ON_EVENT_MAP_CALLBACKS_CLIENT_SCRIPT_PATH,
            "find_CLoopModeGame_OnEventMapCallbacks_client",
        )
        mock_helper = AsyncMock(return_value=True)

        with patch.object(
            module,
            "preprocess_register_event_listener_abstract_skill",
            mock_helper,
            create=True,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        mock_helper.assert_awaited_once_with(
            session="session",
            expected_outputs=["out.yaml"],
            new_binary_dir="bin_dir",
            platform="windows",
            image_base=0x180000000,
            source_yaml_stem=module.SOURCE_YAML_STEM,
            register_func_target_name=module.REGISTER_FUNC_TARGET_NAME,
            anchor_event_name=module.ANCHOR_EVENT_NAME,
            target_specs=module.TARGET_SPECS,
            generate_yaml_desired_fields=module.GENERATE_YAML_DESIRED_FIELDS,
            search_window_after_anchor=module.SEARCH_WINDOW_AFTER_ANCHOR,
            search_window_before_call=module.SEARCH_WINDOW_BEFORE_CALL,
            debug=True,
        )


class TestFindCGameSystemReallocatingFactoryCSpawnGroupMgrGameSystemVtable(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_skill_forwards_expected_vtable_and_aliases(self) -> None:
        module = _load_module(
            REALLOCATING_FACTORY_SCRIPT_PATH,
            "find_CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_vtable",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)
        expected_vtable_class_names = ["CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem"]
        expected_mangled_class_names = {
            "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem": [
                "??_7?$CGameSystemReallocatingFactory@VCSpawnGroupMgrGameSystem@@V1@@@6B@",
                "_ZTV30CGameSystemReallocatingFactoryI24CSpawnGroupMgrGameSystemS0_E",
            ]
        }
        expected_generate_yaml_desired_fields = [
            (
                "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem",
                [
                    "vtable_class",
                    "vtable_symbol",
                    "vtable_va",
                    "vtable_rva",
                    "vtable_size",
                    "vtable_numvfunc",
                    "vtable_entries",
                ],
            )
        ]

        with patch.object(
            module,
            "preprocess_common_skill",
            mock_preprocess_common_skill,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        mock_preprocess_common_skill.assert_awaited_once_with(
            session="session",
            expected_outputs=["out.yaml"],
            vtable_class_names=expected_vtable_class_names,
            mangled_class_names=expected_mangled_class_names,
            generate_yaml_desired_fields=expected_generate_yaml_desired_fields,
            platform="windows",
            image_base=0x180000000,
            debug=True,
        )


class TestFindCGameSystemReallocatingFactoryCSpawnGroupMgrGameSystemDeallocateImpl(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_skill_forwards_expected_inherit_vfuncs(self) -> None:
        module = _load_module(
            REALLOCATING_FACTORY_DEALLOCATE_SCRIPT_PATH,
            "find_CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem_impl",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)
        expected_inherit_vfuncs = [
            (
                "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem",
                "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem",
                "../client/IGameSystemFactory_DestroyGameSystem",
                True,
            )
        ]
        expected_generate_yaml_desired_fields = [
            (
                "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem",
                [
                    "func_name",
                    "func_va",
                    "func_rva",
                    "func_size",
                    "func_sig",
                    "vtable_name",
                    "vfunc_offset",
                    "vfunc_index",
                ],
            )
        ]

        with patch.object(
            module,
            "preprocess_common_skill",
            mock_preprocess_common_skill,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        mock_preprocess_common_skill.assert_awaited_once_with(
            session="session",
            expected_outputs=["out.yaml"],
            old_yaml_map={"k": "v"},
            new_binary_dir="bin_dir",
            platform="windows",
            image_base=0x180000000,
            inherit_vfuncs=expected_inherit_vfuncs,
            generate_yaml_desired_fields=expected_generate_yaml_desired_fields,
            debug=True,
        )


class TestFindCSpawnGroupMgrGameSystemVtable2(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_skill_uses_windows_secondary_vtable_alias(self) -> None:
        module = _load_module(
            CSPAWNGROUP_VTABLE2_SCRIPT_PATH,
            "find_CSpawnGroupMgrGameSystem_vtable2_windows",
        )
        mock_preprocess_ordinal_vtable = AsyncMock(
            return_value={
                "vtable_class": "CSpawnGroupMgrGameSystem",
                "vtable_symbol": "??_7CSpawnGroupMgrGameSystem@@6B@_0 + 0x10",
                "vtable_va": "0x1819682c0",
                "vtable_rva": "0x19682c0",
                "vtable_size": "0x20",
                "vtable_numvfunc": 4,
                "vtable_entries": {0: "0x180100000"},
            }
        )

        with (
            patch.object(
                module,
                "preprocess_ordinal_vtable_via_mcp",
                mock_preprocess_ordinal_vtable,
            ),
            patch.object(module, "write_vtable_yaml") as mock_write_vtable_yaml,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["tmp/CSpawnGroupMgrGameSystem_vtable2.windows.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        mock_preprocess_ordinal_vtable.assert_awaited_once_with(
            session="session",
            class_name="CSpawnGroupMgrGameSystem",
            ordinal=0,
            image_base=0x180000000,
            platform="windows",
            debug=True,
            symbol_aliases=["??_7CSpawnGroupMgrGameSystem@@6B@_0"],
            expected_offset_to_top=None,
        )
        mock_write_vtable_yaml.assert_called_once_with(
            "tmp/CSpawnGroupMgrGameSystem_vtable2.windows.yaml",
            mock_preprocess_ordinal_vtable.return_value,
        )

    async def test_preprocess_skill_uses_linux_offset_to_top_filter(self) -> None:
        module = _load_module(
            CSPAWNGROUP_VTABLE2_SCRIPT_PATH,
            "find_CSpawnGroupMgrGameSystem_vtable2_linux",
        )
        mock_preprocess_ordinal_vtable = AsyncMock(
            return_value={
                "vtable_class": "CSpawnGroupMgrGameSystem",
                "vtable_symbol": "_ZTI24CSpawnGroupMgrGameSystem ref 0x0",
                "vtable_va": "0x1819682d0",
                "vtable_rva": "0x19682d0",
                "vtable_size": "0x18",
                "vtable_numvfunc": 3,
                "vtable_entries": {0: "0x180100000"},
            }
        )

        with (
            patch.object(
                module,
                "preprocess_ordinal_vtable_via_mcp",
                mock_preprocess_ordinal_vtable,
            ),
            patch.object(module, "write_vtable_yaml") as mock_write_vtable_yaml,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["tmp/CSpawnGroupMgrGameSystem_vtable2.linux.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="linux",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        mock_preprocess_ordinal_vtable.assert_awaited_once_with(
            session="session",
            class_name="CSpawnGroupMgrGameSystem",
            ordinal=0,
            image_base=0x180000000,
            platform="linux",
            debug=True,
            symbol_aliases=None,
            expected_offset_to_top=-8,
        )
        mock_write_vtable_yaml.assert_called_once_with(
            "tmp/CSpawnGroupMgrGameSystem_vtable2.linux.yaml",
            mock_preprocess_ordinal_vtable.return_value,
        )


class TestFindCSpawnGroupMgrGameSystemDoesGameSystemReallocate(unittest.IsolatedAsyncioTestCase):
    def test_build_factory_yaml_paths_prefers_local_then_sibling_client(self) -> None:
        module = _load_module(
            CSPAWNGROUP_DOES_REALLOCATE_SCRIPT_PATH,
            "find_CSpawnGroupMgrGameSystem_DoesGameSystemReallocate_paths",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir) / "bin" / "14141" / "server"
            paths = module._build_factory_yaml_paths(module_dir, "linux")

        self.assertEqual(
            [
                str(Path(temp_dir) / "bin" / "14141" / "server" / "IGameSystemFactory_IsReallocating.linux.yaml"),
                str(Path(temp_dir) / "bin" / "14141" / "client" / "IGameSystemFactory_IsReallocating.linux.yaml"),
            ],
            paths,
        )

    async def test_preprocess_skill_binds_to_secondary_vtable_artifact(self) -> None:
        module = _load_module(
            CSPAWNGROUP_DOES_REALLOCATE_SCRIPT_PATH,
            "find_CSpawnGroupMgrGameSystem_DoesGameSystemReallocate",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)

        with (
            patch.object(
                module,
                "preprocess_common_skill",
                mock_preprocess_common_skill,
            ),
            patch.object(
                module,
                "_read_vfunc_offset",
                return_value=0x18,
            ),
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        self.assertEqual(
            [
                (
                    "CSpawnGroupMgrGameSystem_DoesGameSystemReallocate",
                    "CSpawnGroupMgrGameSystem_vtable2",
                )
            ],
            mock_preprocess_common_skill.await_args.kwargs["func_vtable_relations"],
        )
        self.assertEqual(
            "48 8B 0D ?? ?? ?? ?? 48 8B 01 48 FF 60 18",
            mock_preprocess_common_skill.await_args.kwargs["func_xrefs"][0]["xref_signatures"][0],
        )

    async def test_preprocess_skill_reads_factory_yaml_from_sibling_client(self) -> None:
        module = _load_module(
            CSPAWNGROUP_DOES_REALLOCATE_SCRIPT_PATH,
            "find_CSpawnGroupMgrGameSystem_DoesGameSystemReallocate_linux",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)

        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir) / "bin" / "14141"
            server_dir = module_dir / "server"
            client_dir = module_dir / "client"
            server_dir.mkdir(parents=True, exist_ok=True)
            client_dir.mkdir(parents=True, exist_ok=True)
            (client_dir / "IGameSystemFactory_IsReallocating.linux.yaml").write_text(
                "vfunc_offset: 0x20\n", encoding="utf-8"
            )

            with patch.object(
                module,
                "preprocess_common_skill",
                mock_preprocess_common_skill,
            ):
                result = await module.preprocess_skill(
                    session="session",
                    skill_name="skill",
                    expected_outputs=["out.yaml"],
                    old_yaml_map={"k": "v"},
                    new_binary_dir=str(server_dir),
                    platform="linux",
                    image_base=0x180000000,
                    debug=True,
                )

        self.assertTrue(result)
        self.assertEqual(
            "48 8B 3D ?? ?? ?? ?? 48 8B 07 FF 60 20",
            mock_preprocess_common_skill.await_args.kwargs["func_xrefs"][0]["xref_signatures"][0],
        )


class TestFindCLoopModeFactoryCLoopModeGameInit(unittest.IsolatedAsyncioTestCase):
    async def test_script_forwards_inline_alias_func_xrefs(self) -> None:
        module = _load_module(
            CLOOPMODE_FACTORY_GAME_INIT_SCRIPT_PATH,
            "find_CLoopModeFactory_CLoopModeGame_Init",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)
        expected_func_xrefs = [
            {
                "func_name": "CLoopModeFactory_CLoopModeGame_Init",
                "xref_strings": [],
                "xref_gvs": [],
                "xref_signatures": [],
                "xref_funcs": [],
                "exclude_funcs": [],
                "exclude_strings": [],
                "exclude_gvs": [],
                "exclude_signatures": [],
                "inline_alias": "CLoopModeGame_StaticInit",
            }
        ]
        expected_func_vtable_relations = [
            (
                "CLoopModeFactory_CLoopModeGame_Init",
                "CLoopModeFactory_CLoopModeGame_vtable",
            )
        ]
        expected_generate_yaml_desired_fields = [
            (
                "CLoopModeFactory_CLoopModeGame_Init",
                [
                    "func_name",
                    "func_va",
                    "func_rva",
                    "func_size",
                    "vtable_name",
                    "vfunc_offset",
                    "vfunc_index",
                ],
            )
        ]

        with patch.object(
            module,
            "preprocess_common_skill",
            mock_preprocess_common_skill,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        self.assertTrue(result)
        mock_preprocess_common_skill.assert_awaited_once_with(
            session="session",
            expected_outputs=["out.yaml"],
            old_yaml_map={"k": "v"},
            new_binary_dir="bin_dir",
            platform="windows",
            image_base=0x180000000,
            func_names=["CLoopModeFactory_CLoopModeGame_Init"],
            func_xrefs=expected_func_xrefs,
            func_vtable_relations=expected_func_vtable_relations,
            generate_yaml_desired_fields=expected_generate_yaml_desired_fields,
            debug=True,
        )


class TestFindILoopTypeDeallocateLoopMode(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_skill_forwards_multiple_reference_paths_in_fixed_order(self) -> None:
        module = _load_module(
            Path("ida_preprocessor_scripts/find-CLoopTypeBase_DeallocateLoopMode.py"),
            "find_CLoopTypeBase_DeallocateLoopMode",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)
        llm_config = {"model": "gpt-5.4", "fake_as": "codex"}
        expected_llm_decompile_specs = [
            {
                "symbol_name": "CLoopTypeBase_DeallocateLoopMode",
                "prompt_path": "prompt/call_llm_decompile.md",
                "reference_yaml_paths": [
                    "references/engine/CEngineServiceMgr_DeactivateLoop.{platform}.yaml",
                    "references/engine/CEngineServiceMgr__MainLoop.{platform}.yaml",
                ],
                "expected_result_sections": ["found_vcall"],
                "dependency_policy": {
                    "CEngineServiceMgr_DeactivateLoop.{platform}.yaml": "optional",
                    "CEngineServiceMgr__MainLoop.{platform}.yaml": "required",
                },
            },
        ]

        with patch.object(module, "preprocess_common_skill", mock_preprocess_common_skill):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={"k": "v"},
                new_binary_dir="bin_dir",
                platform="linux",
                image_base=0x180000000,
                llm_config=llm_config,
                debug=True,
            )

        self.assertTrue(result)
        mock_preprocess_common_skill.assert_awaited_once_with(
            session="session",
            expected_outputs=["out.yaml"],
            old_yaml_map={"k": "v"},
            new_binary_dir="bin_dir",
            platform="linux",
            image_base=0x180000000,
            func_names=["CLoopTypeBase_DeallocateLoopMode"],
            func_vtable_relations=[("CLoopTypeBase_DeallocateLoopMode", "CLoopTypeBase")],
            llm_decompile_specs=expected_llm_decompile_specs,
            llm_config=llm_config,
            generate_yaml_desired_fields=[
                (
                    "CLoopTypeBase_DeallocateLoopMode",
                    [
                        "func_name",
                        "vfunc_sig",
                        "vfunc_offset",
                        "vfunc_index",
                        "vtable_name",
                    ],
                )
            ],
            debug=True,
        )


class TestFindCEngineServiceMgrDeactivateLoop(unittest.IsolatedAsyncioTestCase):
    async def test_preprocess_skill_returns_absent_ok_for_verified_inline_sequence(
        self,
    ) -> None:
        module = _load_module(
            Path("ida_preprocessor_scripts/find-CEngineServiceMgr_DeactivateLoop.py"),
            "find_CEngineServiceMgr_DeactivateLoop",
        )

        with (
            patch.object(
                module,
                "preprocess_common_skill",
                AsyncMock(return_value=False),
            ),
            patch.object(
                module,
                "_load_llm_decompile_target_detail_via_mcp",
                AsyncMock(
                    return_value={
                        "func_name": "CEngineServiceMgr__MainLoop",
                        "func_va": "0x180555500",
                        "disasm_code": ("call    qword ptr [rax+40h]\ncall    qword ptr [rax+30h]"),
                        "procedure": ("loop_type->LoopDeactivate(loop_state);\nloop_type->DeallocateLoopMode();"),
                    }
                ),
            ) as mock_load_detail,
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={},
                new_binary_dir="bin_dir",
                platform="linux",
                image_base=0x180000000,
                llm_config={"model": "gpt-5.4", "fake_as": "codex"},
                debug=True,
            )

        self.assertEqual("absent_ok", result)
        mock_load_detail.assert_awaited_once_with(
            "session",
            "CEngineServiceMgr__MainLoop",
            new_binary_dir="bin_dir",
            platform="linux",
            debug=True,
        )

    async def test_preprocess_skill_keeps_failure_when_inline_markers_are_incomplete(
        self,
    ) -> None:
        module = _load_module(
            Path("ida_preprocessor_scripts/find-CEngineServiceMgr_DeactivateLoop.py"),
            "find_CEngineServiceMgr_DeactivateLoop",
        )

        with (
            patch.object(
                module,
                "preprocess_common_skill",
                AsyncMock(return_value=False),
            ),
            patch.object(
                module,
                "_load_llm_decompile_target_detail_via_mcp",
                AsyncMock(
                    return_value={
                        "func_name": "CEngineServiceMgr__MainLoop",
                        "func_va": "0x180555500",
                        "disasm_code": "call    qword ptr [rax+40h]",
                        "procedure": "loop_type->LoopDeactivate(loop_state);",
                    }
                ),
            ),
        ):
            result = await module.preprocess_skill(
                session="session",
                skill_name="skill",
                expected_outputs=["out.yaml"],
                old_yaml_map={},
                new_binary_dir="bin_dir",
                platform="linux",
                image_base=0x180000000,
                llm_config={"model": "gpt-5.4", "fake_as": "codex"},
                debug=True,
            )

        self.assertFalse(result)


class TestFindConnectInterfaces(unittest.IsolatedAsyncioTestCase):
    async def test_non_engine_modules_omit_engine_exclude_func(self) -> None:
        module = _load_module(
            CONNECT_INTERFACES_SCRIPT_PATH,
            "find_ConnectInterfaces_non_engine",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)

        with patch.object(module, "preprocess_common_skill", mock_preprocess_common_skill):
            for module_name in ("client", "server"):
                with self.subTest(module_name=module_name):
                    await module.preprocess_skill(
                        session="session",
                        skill_name="find-ConnectInterfaces",
                        expected_outputs=["ConnectInterfaces.windows.yaml"],
                        old_yaml_map={},
                        new_binary_dir=str(Path("bin") / "14168" / module_name),
                        platform="windows",
                        image_base=0x180000000,
                        debug=True,
                    )

                    func_xrefs = mock_preprocess_common_skill.await_args.kwargs["func_xrefs"]
                    self.assertEqual([], func_xrefs[0]["exclude_funcs"])

    async def test_engine_keeps_exclude_func_in_per_call_copy(self) -> None:
        module = _load_module(
            CONNECT_INTERFACES_SCRIPT_PATH,
            "find_ConnectInterfaces_engine",
        )
        mock_preprocess_common_skill = AsyncMock(return_value=True)

        with patch.object(module, "preprocess_common_skill", mock_preprocess_common_skill):
            await module.preprocess_skill(
                session="session",
                skill_name="find-ConnectInterfaces",
                expected_outputs=["ConnectInterfaces.windows.yaml"],
                old_yaml_map={},
                new_binary_dir=str(Path("bin") / "14168" / "engine"),
                platform="windows",
                image_base=0x180000000,
                debug=True,
            )

        func_xrefs = mock_preprocess_common_skill.await_args.kwargs["func_xrefs"]
        self.assertIsNot(module.FUNC_XREFS, func_xrefs)
        self.assertEqual(["CNetSupportImpl_Connect"], func_xrefs[0]["exclude_funcs"])
        self.assertEqual(
            ["CNetSupportImpl_Connect"],
            module.FUNC_XREFS[0]["exclude_funcs"],
        )


if __name__ == "__main__":
    unittest.main()
