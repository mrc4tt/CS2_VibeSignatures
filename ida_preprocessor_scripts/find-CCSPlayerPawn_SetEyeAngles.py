#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayerPawn_SetEyeAngles skill (auto-generated, func)."""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CCSPlayerPawn_SetEyeAngles",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSPlayerPawn_SetEyeAngles",
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
    """Relocate the previous gamever's func artifact onto this build."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGETS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
