#!/usr/bin/env python3
"""Preprocess script for find-CBasePlayerController_CheckForLocalPlayer skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBasePlayerController_CheckForLocalPlayer",
]

FUNC_XREFS = [
    {
        "func_name": "CBasePlayerController_CheckForLocalPlayer",
        "xref_strings": ["snd_soundmixer"],
        "xref_gvs": ["g_pEngineClient"],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": [
            "FULLMATCH:cl_player_ragdolls_collide",
            "FULLMATCH:dsp_volume",
        ],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CBasePlayerController_CheckForLocalPlayer",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
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
    debug=False,
):
    """Reuse previous gamever func_sig to locate the target function and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=FUNC_XREFS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
