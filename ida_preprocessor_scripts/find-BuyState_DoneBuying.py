#!/usr/bin/env python3
"""Relocate BuyState_DoneBuying using caller-supplied prior artifact signatures.

This implements the shared signature-reuse path, not an independent discovery
rule. No verified string/decompilation anchors are available yet. Missing or
non-unique prior signatures leave the retained agent skill as fallback.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_STRUCT_MEMBER_NAMES = ["BuyState_DoneBuying"]
GENERATE_YAML_DESIRED_FIELDS = [
    ("BuyState_DoneBuying", ["struct_name", "member_name", "offset", "size", "offset_sig", "offset_sig_disp"])
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
