#!/usr/bin/env python3
"""Preprocess script for find-InitSteam-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_GLOBALVAR_NAMES = [
    "g_nSteamAppId",
    "g_nBreakpadAppId",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "g_nSteamAppId",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/InitSteam.{platform}.yaml",
        ],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {
            "InitSteam.{platform}.yaml": "required",
        },
    },
    {
        "symbol_name": "g_nBreakpadAppId",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/InitSteam.{platform}.yaml",
        ],
        "expected_result_sections": ["found_gv"],
        "dependency_policy": {
            "InitSteam.{platform}.yaml": "required",
        },
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "g_nSteamAppId",
        [
            "gv_name",
            "gv_va",
            "gv_rva",
            "gv_sig",
            "gv_sig_va",
            "gv_inst_offset",
            "gv_inst_length",
            "gv_inst_disp",
        ],
    ),
    (
        "g_nBreakpadAppId",
        [
            "gv_name",
            "gv_va",
            "gv_rva",
            "gv_sig",
            "gv_sig_va",
            "gv_inst_offset",
            "gv_inst_length",
            "gv_inst_disp",
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
    """Locate Steam application ID globals by decompiling InitSteam."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        gv_names=TARGET_GLOBALVAR_NAMES,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
