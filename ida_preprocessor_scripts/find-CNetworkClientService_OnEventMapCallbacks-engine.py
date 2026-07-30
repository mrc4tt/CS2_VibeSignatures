#!/usr/bin/env python3
"""Preprocess script for find-CNetworkClientService_OnEventMapCallbacks-engine skill."""

from ida_analyze_util import preprocess_common_skill

SOURCE_YAML_STEM = "CNetworkClientService_RegisterEventMapInternal"

CALLBACK_FUNCTION_NAMES = [
    "CNetworkClientService_OnClientAdvanceTick",
    "CNetworkClientService_OnClientProcessGameInput",
    "CNetworkClientService_OnClientPollNetworking",
    "CNetworkClientService_OnClientProcessNetworking",
    "CNetworkClientService_OnClientSimulate",
    "CNetworkClientService_OnClientPauseSimulate",
    "CNetworkClientService_OnClientFrameSimulate",
    "CNetworkClientService_OnSimpleLoopFrameUpdate",
    "CNetworkClientService_OnFrameBoundary",
    "CNetworkClientService_OnServerPostSimulate",
    "CNetworkClientService_OnServerBeginAsyncPostTickWork",
]

TARGET_FUNCTION_NAMES = [
    "RegisterEventListener_Abstract",
    *CALLBACK_FUNCTION_NAMES,
]


def _llm_decompile_spec(symbol_name, expected_result_section):
    return {
        "symbol_name": symbol_name,
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CNetworkClientService_RegisterEventMapInternal.{platform}.yaml",
        ],
        "dependency_policy": {
            "CNetworkClientService_RegisterEventMapInternal.{platform}.yaml": "required",
        },
        "expected_result_sections": [expected_result_section],
    }


LLM_DECOMPILE = [
    _llm_decompile_spec("RegisterEventListener_Abstract", "found_call"),
    *[_llm_decompile_spec(callback_name, "found_funcptr") for callback_name in CALLBACK_FUNCTION_NAMES],
]

_SIGNED_GENERATE_FIELDS = [
    "func_name",
    "func_sig",
    "func_va",
    "func_rva",
    "func_size",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (function_name, list(_SIGNED_GENERATE_FIELDS)) for function_name in TARGET_FUNCTION_NAMES
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
    """Resolve RegisterEventListener_Abstract and event callbacks through decompilation."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
