#!/usr/bin/env python3
"""Preprocess script for find-CSource2Server_Connect-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "IVEngineServer2_GetServerGlobals",
]

TARGET_GLOBALVAR_NAMES = [
    "g_engine",
    "g_pEngineServer",
    "g_pSource2Engine",
    "g_networkstringtable",
    "g_pGameTypes",
]

FUNC_VTABLE_RELATIONS = [
    # IVEngineServer2 is an abstract interface; vtable_name is metadata only.
    ("IVEngineServer2_GetServerGlobals", "IVEngineServer2"),
]

LLM_DECOMPILE = [
    {
        "symbol_name": "IVEngineServer2_GetServerGlobals",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_Connect.{platform}.yaml"],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {"CSource2Server_Connect.{platform}.yaml": "required"},
    },
    {
        "symbol_name": "g_engine",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_Connect.{platform}.yaml"],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {"CSource2Server_Connect.{platform}.yaml": "required"},
    },
    {
        "symbol_name": "g_pEngineServer",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_Connect.{platform}.yaml"],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {"CSource2Server_Connect.{platform}.yaml": "required"},
    },
    {
        "symbol_name": "g_pSource2Engine",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_Connect.{platform}.yaml"],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {"CSource2Server_Connect.{platform}.yaml": "required"},
    },
    {
        "symbol_name": "g_networkstringtable",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_Connect.{platform}.yaml"],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {"CSource2Server_Connect.{platform}.yaml": "required"},
    },
    {
        "symbol_name": "g_pGameTypes",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_Connect.{platform}.yaml"],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {"CSource2Server_Connect.{platform}.yaml": "required"},
    },
]

GLOBALVAR_YAML_FIELDS = [
    "gv_name",
    "gv_va",
    "gv_rva",
    "gv_sig",
    "gv_sig_va",
    "gv_inst_offset",
    "gv_inst_length",
    "gv_inst_disp",
]

GLOBALVAR_YAML_FIELDS_BY_NAME = {
    "g_networkstringtable": [
        *GLOBALVAR_YAML_FIELDS,
        "gv_sig_allow_across_function_boundary: true",
    ],
}

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "IVEngineServer2_GetServerGlobals",
        ["func_name", "vfunc_sig", "vfunc_offset", "vfunc_index", "vtable_name"],
    ),
    *[
        (
            globalvar_name,
            GLOBALVAR_YAML_FIELDS_BY_NAME.get(globalvar_name, GLOBALVAR_YAML_FIELDS),
        )
        for globalvar_name in TARGET_GLOBALVAR_NAMES
    ],
]


async def preprocess_skill(
    session,
    skill_name,
    expected_outputs,
    old_yaml_map,
    new_binary_dir,
    platform,
    image_base,
    llm_config=None,
    debug=False,
):
    """Find engine globals and GetServerGlobals from CSource2Server::Connect."""
    _ = skill_name
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        gv_names=TARGET_GLOBALVAR_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
