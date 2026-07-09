#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayerPawn_SnapViewAngles skill.

SnapViewAngles is non-virtual and has no string of its own. It is found via LLM_DECOMPILE
on the Setang_CommandHandler predecessor: the LLM picks the direct call in the handler's
non-teleport (else) branch -- NOT the CPredictionEvent_Teleport branch.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSPlayerPawn_SnapViewAngles",
]

LLM_DECOMPILE = [
    # (symbol_name, path_to_prompt, path_to_reference)
    (
        "CCSPlayerPawn_SnapViewAngles",
        "prompt/call_llm_decompile.md",
        "references/server/Setang_CommandHandler.{platform}.yaml",
    ),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # Include func_va/func_rva/func_size: SnapViewAngles is the predecessor anchor for the
    # find-CCSPlayerPawn_SnapEyeAngles sibling step.
    (
        "CCSPlayerPawn_SnapViewAngles",
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
