#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayerPawn_SnapEyeAngles skill.

SnapEyeAngles is the structural twin of SnapViewAngles (no string, not called by the setang
handler). It is resolved as the one caller of CCSPlayerPawn_ApplyEyeAngleNetworkChange that is
NOT SnapViewAngles -- the apply helper has exactly those two callers.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSPlayerPawn_SnapEyeAngles",
]

FUNC_XREFS = [
    {
        "func_name": "CCSPlayerPawn_SnapEyeAngles",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        # Callers of the apply helper = {SnapViewAngles, SnapEyeAngles}; exclude the view one.
        "xref_funcs": ["CCSPlayerPawn_ApplyEyeAngleNetworkChange"],
        "exclude_funcs": ["CCSPlayerPawn_SnapViewAngles"],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSPlayerPawn_SnapEyeAngles",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
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
    """Reuse previous gamever func_sig to locate target function(s) and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=FUNC_XREFS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
