#!/usr/bin/env python3
"""Preprocess script for find-CBaseTrigger_vtable-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

INHERIT_VFUNCS = [
    # (target_func_name, inherit_vtable_class, base_vfunc_name, generate_func_sig)
    ("CBaseTrigger_StartTouch", "CBaseTrigger", "CBaseEntity_StartTouch", False),
    ("CBaseTrigger_EndTouch", "CBaseTrigger", "CBaseEntity_EndTouch", False),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CBaseTrigger_StartTouch",
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
    (
        "CBaseTrigger_EndTouch",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
            # linux slot 149 is a 17-byte wrapper (test rsi,rsi; je; jmp body), so a
            # body-only sig is not unique and the jmp displacement must stay
            # wildcarded. Windows has no wrapper and is unaffected by the flag.
            "func_sig_allow_across_function_boundary:true",
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
    """Resolve CBaseTrigger StartTouch/EndTouch by their respective CBaseEntity vfunc indices."""
    _ = skill_name

    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        inherit_vfuncs=INHERIT_VFUNCS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
