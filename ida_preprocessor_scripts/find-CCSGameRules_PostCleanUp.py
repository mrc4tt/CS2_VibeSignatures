#!/usr/bin/env python3
"""Preprocess script for find-CCSGameRules_PostCleanUp skill.

PostCleanUp is non-virtual and has no unique string of its own (it references "cs_respawn",
shared with another large function). It is found via LLM_DECOMPILE on the CCSGameRules_ResetRound
predecessor: the LLM picks the entity-cleanup callee -- the one that iterates the entity list,
dynamic-casts CCSWeaponBase / CBombTarget / CHostageRescueZone, and references "cs_respawn".
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSGameRules_PostCleanUp",
]

LLM_DECOMPILE = [
    # (symbol_name, path_to_prompt, path_to_reference)
    (
        "CCSGameRules_PostCleanUp",
        "prompt/call_llm_decompile.md",
        "references/server/CCSGameRules_ResetRound.{platform}.yaml",
    ),
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSGameRules_PostCleanUp",
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
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
