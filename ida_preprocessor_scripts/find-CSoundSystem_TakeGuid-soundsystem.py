#!/usr/bin/env python3
"""Preprocess script for find-CSoundSystem_TakeGuid-soundsystem skill.

CSoundSystem_TakeGuid in soundsystem itself, found by its own body and placed in
CSoundSystem's vtable by RTTI. The server record of the same name reads the slot off
a call site (g_pSoundSystem's [rax+0x268] / [rax+0x270]); validate_artifacts compares
the two indices on each platform, so a call site that drifts to another slot fails
the build instead of shipping.

linux slot 77: mov eax,[rdi+0x3c]; add 1; cmovns - the counter, wrapped to 0 and returned.
windows slot 78: inc [rcx+0x3c]; the same wrap, the value written through rdx.
Both bodies hold no relocatable byte and are unique as a whole.
"""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CSoundSystem_TakeGuid",
]

FUNC_VTABLE_RELATIONS = [
    ("CSoundSystem_TakeGuid", "CSoundSystem"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CSoundSystem_TakeGuid",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
            "vtable_name",
            "vfunc_offset",
            "vfunc_index",
            # 0x12 / 0x1a bytes: too short to grow a pattern inside the body alone
            "func_sig_allow_across_function_boundary:true",
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
    """Relocate the previous gamever's soundsystem TakeGuid onto this build."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGETS,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
