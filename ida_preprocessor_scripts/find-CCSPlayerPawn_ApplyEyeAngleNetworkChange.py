#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayerPawn_ApplyEyeAngleNetworkChange skill.

The per-pawn helper that applies the m_angEyeAngles network-state change. It has exactly two
callers -- CCSPlayerPawn_SnapViewAngles and CCSPlayerPawn_SnapEyeAngles -- which is what makes
it the anchor for finding SnapEyeAngles. Located via LLM_DECOMPILE on the SnapViewAngles
predecessor (the helper is the distinctive networkvar-apply call inside it).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSPlayerPawn_ApplyEyeAngleNetworkChange",
]

LLM_DECOMPILE = [
    # (symbol_name, path_to_prompt, path_to_reference)
    (
        "CCSPlayerPawn_ApplyEyeAngleNetworkChange",
        "prompt/call_llm_decompile.md",
        "references/server/CCSPlayerPawn_SnapViewAngles.{platform}.yaml",
    ),
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSPlayerPawn_ApplyEyeAngleNetworkChange",
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
