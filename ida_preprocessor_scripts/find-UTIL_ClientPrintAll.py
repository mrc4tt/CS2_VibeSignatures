#!/usr/bin/env python3
"""Preprocess script for find-UTIL_ClientPrintAll skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "UTIL_ClientPrintAll",
]

LLM_DECOMPILE_WINDOWS = [
    {
        "symbol_name": "UTIL_ClientPrintAll",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CCSPlayerPawnBase_CheckForIdle.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "CCSPlayerPawnBase_CheckForIdle.{platform}.yaml": "required",
        },
    },
]

LLM_DECOMPILE_LINUX = [
    {
        "symbol_name": "UTIL_ClientPrintAll",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CCSPlayerPawnBase_CheckForIdleInternal.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "CCSPlayerPawnBase_CheckForIdleInternal.{platform}.yaml": "required",
        },
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "UTIL_ClientPrintAll",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
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
    """Reuse previous gamever func_sig to locate target function(s) and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        llm_decompile_specs=LLM_DECOMPILE_WINDOWS if platform == "windows" else LLM_DECOMPILE_LINUX,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
