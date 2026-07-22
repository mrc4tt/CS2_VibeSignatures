#!/usr/bin/env python3
"""Preprocess script for find-CNetworkGameClient_OnSource1Source1LegacyGameEvent-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "IGameEventManager2_UnserializeEvent",
    "IGameEventManager2_FireEventClientSide",
]

FUNC_VTABLE_RELATIONS = [
    ("IGameEventManager2_UnserializeEvent", "IGameEventManager2"),
    ("IGameEventManager2_FireEventClientSide", "IGameEventManager2"),
]

LLM_DECOMPILE = [
    {
        "symbol_name": "IGameEventManager2_UnserializeEvent",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/client/CNetworkGameClient_OnSource1Source1LegacyGameEvent.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CNetworkGameClient_OnSource1Source1LegacyGameEvent.{platform}.yaml": "required",
        },
    },
    {
        "symbol_name": "IGameEventManager2_FireEventClientSide",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/client/CNetworkGameClient_OnSource1Source1LegacyGameEvent.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CNetworkGameClient_OnSource1Source1LegacyGameEvent.{platform}.yaml": "required",
        },
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "IGameEventManager2_UnserializeEvent",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_sig_allow_across_function_boundary:true",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "IGameEventManager2_FireEventClientSide",
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
    """Resolve the two abstract IGameEventManager2 slots from the predecessor decompile."""
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
