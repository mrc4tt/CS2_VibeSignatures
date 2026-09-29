#!/usr/bin/env python3
"""Relocate CEntityIdentity_m_pInstance from the previous gamever's offset_sig.

Shared struct-member path: find the old offset_sig, read the member offset back
out of the matched instructions (preferring the one that still carries the old
offset) and record which instruction that was as offset_sig_disp. This file used
to import a preprocess_gen_struct_member_via_mcp that ida_analyze_util never
had, so every run fell through to the hunter or an agent.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_STRUCT_MEMBER_NAMES = ["CEntityIdentity_m_pInstance"]
GENERATE_YAML_DESIRED_FIELDS = [
    ("CEntityIdentity_m_pInstance", ["struct_name", "member_name", "offset", "size", "offset_sig", "offset_sig_disp"]),
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
    """Use the shared struct_member relocation and YAML writer for either platform."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        struct_member_names=TARGET_STRUCT_MEMBER_NAMES,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
