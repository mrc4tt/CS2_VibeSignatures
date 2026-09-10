#!/usr/bin/env python3
"""Preprocess script for find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem skill (auto-generated, vfunc)."""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
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
