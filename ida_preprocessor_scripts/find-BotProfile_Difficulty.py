#!/usr/bin/env python3
"""Preprocess script for find-BotProfile_Difficulty skill (auto-generated, structmember)."""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "BotProfile_Difficulty",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "BotProfile_Difficulty",
        [
            "struct_name",
            "member_name",
            "offset",
            "size",
            "offset_sig",
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
    """Relocate the previous gamever's structmember artifact onto this build."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        struct_member_names=TARGETS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
