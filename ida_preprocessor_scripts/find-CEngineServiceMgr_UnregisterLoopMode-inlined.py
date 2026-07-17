#!/usr/bin/env python3
"""Preprocess script for find-CEngineServiceMgr_UnregisterLoopMode-inlined skill (deinline-fix chain, link 3/3).

Collects the ``CLoopTypeBase::GetImplType`` (+0x50 Linux / +0x48 Windows),
``ILoopModeFactory::GetLoopModeType`` (+0x20) and ``ILoopModeFactory::Shutdown`` (+0x8)
vcalls by decompiling ``CEngineServiceMgr::UnregisterLoopMode`` directly.

This is the inlined link of an inline/noinline decompile fallback pair (formerly the sole
``find-CLoopTypeBase_GetImplType-AND-ILoopModeFactory_GetLoopModeType-AND-ILoopModeFactory_Shutdown``
skill).  It applies whenever the ``UnregisterLoopModeFactory`` helper is inlined into the
parent so all three vcalls live in the parent body -- i.e. Windows (all builds) and older
Linux builds (<= 14167).  It is the fallback for
``find-CEngineServiceMgr_UnregisterLoopMode-noinline`` (which handles the de-inlined Linux
layout) and is skipped whenever the three vcall outputs already exist (i.e. the -noinline
path already produced them on de-inlined Linux).

GENERATE_YAML_DESIRED_FIELDS are kept identical to the -noinline link so the three symbols'
output shape does not depend on which path wins.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeBase_GetImplType",
    "ILoopModeFactory_GetLoopModeType",
    "ILoopModeFactory_Shutdown",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CLoopTypeBase_GetImplType",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CEngineServiceMgr_UnregisterLoopMode.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
    },
    {
        "symbol_name": "ILoopModeFactory_GetLoopModeType",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CEngineServiceMgr_UnregisterLoopMode.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
    },
    {
        "symbol_name": "ILoopModeFactory_Shutdown",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CEngineServiceMgr_UnregisterLoopMode.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CLoopTypeBase_GetImplType", "CLoopTypeBase"),
    ("ILoopModeFactory_GetLoopModeType", "ILoopModeFactory"),
    ("ILoopModeFactory_Shutdown", "ILoopModeFactory"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopTypeBase_GetImplType",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "ILoopModeFactory_GetLoopModeType",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "ILoopModeFactory_Shutdown",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_sig_allow_across_function_boundary:true",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
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
    """Collect the loop-mode vcalls for the inlined UnregisterLoopMode layout via LLM decompile."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
