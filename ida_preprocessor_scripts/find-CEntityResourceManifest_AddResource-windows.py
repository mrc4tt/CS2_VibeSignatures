#!/usr/bin/env python3
"""Preprocess script for find-CEntityResourceManifest_AddResource skill (vfunc, windows).

One file per platform because the artifact exists per platform and the task name
states which one. The vtable indices are not the same on both: CEntityResourceManifest
has 12 slots on either side, and slots 0-2 are the three default-argument overloads of
AddResource, but GCC and MSVC emit them in opposite order - so the maximally-defaulted
overload CounterStrikeSharp names is slot 0 on linux and slot 2 on windows.
"""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CEntityResourceManifest_AddResource",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CEntityResourceManifest_AddResource",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_sig",
            "vtable_name",
            "vfunc_offset",
            "vfunc_index",
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
    """Relocate the previous gamever's vfunc artifact onto this build."""
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
