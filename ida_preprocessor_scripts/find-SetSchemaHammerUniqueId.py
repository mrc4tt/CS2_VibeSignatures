#!/usr/bin/env python3
"""Preprocess script for find-SetSchemaHammerUniqueId skill (auto-generated, patch)."""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "SetSchemaHammerUniqueId",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "SetSchemaHammerUniqueId",
        [
            "patch_name",
            "patch_va",
            "patch_rva",
            "patch_sig",
            "patch_bytes",
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
    """Relocate the previous gamever's patch artifact onto this build."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        patch_names=TARGETS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
