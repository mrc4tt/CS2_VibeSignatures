#!/usr/bin/env python3
"""Preprocess script for find-CEngineClient_SendStringCmd skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CEngineClient_SendStringCmd",
]

INHERIT_VFUNCS = [
    # (target_func_name, inherit_vtable_class, base_vfunc_name, generate_func_sig)
    (
        "CEngineClient_SendStringCmd",
        "CEngineClient",
        "../client/IVEngineClient2_SendStringCmd",
        True,
    ),
]

# The Linux CEngineClient composite vtable places this IVEngineClient2 override
# at a different slot. Its tail dispatch to INetworkGameClient is unique and
# lets the normal vtable relation recover that platform's actual slot.
FUNC_XREFS_LINUX = [
    {
        "func_name": "CEngineClient_SendStringCmd",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [
            "48 8D 05 ?? ?? ?? ?? 48 8B 38 48 8B 07 FF A0 30 01 00 00",
        ],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

FUNC_VTABLE_RELATIONS = [
    ("CEngineClient_SendStringCmd", "CEngineClient"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CEngineClient_SendStringCmd",
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
    """Resolve CEngineClient's SendStringCmd implementation on each ABI."""
    _ = skill_name

    if platform == "linux":
        return await preprocess_common_skill(
            session=session,
            expected_outputs=expected_outputs,
            old_yaml_map=old_yaml_map,
            new_binary_dir=new_binary_dir,
            platform=platform,
            image_base=image_base,
            func_names=TARGET_FUNCTION_NAMES,
            func_xrefs=FUNC_XREFS_LINUX,
            func_vtable_relations=FUNC_VTABLE_RELATIONS,
            generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
            debug=debug,
        )

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
