#!/usr/bin/env python3
"""Preprocess script for find-CUserMessageServerFrameTime_t_vtable skill."""

from ida_analyze_util import preprocess_common_skill


TARGET_CLASS_NAMES = ["CUserMessageServerFrameTime_t"]

MANGLED_CLASS_NAMES = {
    "CUserMessageServerFrameTime_t": [
        "??_7CUserMessageServerFrameTime_t@@6B@",
        "_ZTV29CUserMessageServerFrameTime_t",
    ],
}

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CUserMessageServerFrameTime_t",
        [
            "vtable_class",
            "vtable_symbol",
            "vtable_va",
            "vtable_rva",
            "vtable_size",
            "vtable_numvfunc",
            "vtable_entries",
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
    """Generate the CUserMessageServerFrameTime_t vtable YAML via mangled aliases."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        vtable_class_names=TARGET_CLASS_NAMES,
        mangled_class_names=MANGLED_CLASS_NAMES,
        platform=platform,
        image_base=image_base,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
