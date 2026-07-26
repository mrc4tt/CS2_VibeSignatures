#!/usr/bin/env python3
"""Preprocess script for find-SC_DumpWorld_CommandHandler-decompiles skill."""

from ida_analyze_util import preprocess_common_skill


TARGET_FUNCTION_NAMES = [
    "ISceneSystem_GetWorldsInfo",
    "ISceneWorld_GetObjectsInfo",
    "ISceneWorld_GetWorldName",
    "ISceneSystem_GetObjectBounds",
    "ISceneSystem_GetObjectClassName",
]

TARGET_STRUCT_MEMBER_NAMES = [
    "CSceneObject_pDesc",
    "CSceneObject_nFlags",
    "CSceneObject_fOriginX",
    "CSceneObject_fOriginY",
    "CSceneObject_fOriginZ",
    "CSceneObject_nClassIndex",
]


def _llm_decompile_spec(symbol_name, expected_result_section):
    return {
        "symbol_name": symbol_name,
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/scenesystem/SC_DumpWorld_CommandHandler.{platform}.yaml",
        ],
        "expected_result_sections": [expected_result_section],
        "dependency_policy": {
            "SC_DumpWorld_CommandHandler.{platform}.yaml": "required",
        },
    }


LLM_DECOMPILE = [
    *[_llm_decompile_spec(symbol_name, "found_vcall") for symbol_name in TARGET_FUNCTION_NAMES],
    *[_llm_decompile_spec(symbol_name, "found_struct_offset") for symbol_name in TARGET_STRUCT_MEMBER_NAMES],
]

FUNC_VTABLE_RELATIONS = [
    ("ISceneSystem_GetWorldsInfo", "ISceneSystem"),
    ("ISceneWorld_GetObjectsInfo", "ISceneWorld"),
    ("ISceneWorld_GetWorldName", "ISceneWorld"),
    ("ISceneSystem_GetObjectBounds", "ISceneSystem"),
    ("ISceneSystem_GetObjectClassName", "ISceneSystem"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    *[
        (
            symbol_name,
            [
                "func_name",
                "vfunc_sig",
                "vfunc_offset",
                "vfunc_index",
                "vtable_name",
            ],
        )
        for symbol_name in TARGET_FUNCTION_NAMES
    ],
    *[
        (
            symbol_name,
            [
                "struct_name",
                "member_name",
                "offset",
                "size",
                "offset_sig",
                "offset_sig_disp",
            ],
        )
        for symbol_name in TARGET_STRUCT_MEMBER_NAMES
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
    """Locate scene-system vfuncs and CSceneObject members via LLM decompile."""
    _ = skill_name
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        struct_member_names=TARGET_STRUCT_MEMBER_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
