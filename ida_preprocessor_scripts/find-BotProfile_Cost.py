#!/usr/bin/env python3
"""Preprocess script for find-BotProfile_Cost skill (auto-generated, structmember)."""

from ida_analyze_util import preprocess_gen_struct_member_via_mcp

TARGET_FUNCTION_NAMES = [
    "BotProfile_Cost",
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
    """Reuse previous gamever struct member offset to locate and write YAML."""
    return await preprocess_gen_struct_member_via_mcp(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        target_name="BotProfile_Cost",
        debug=debug,
    )
