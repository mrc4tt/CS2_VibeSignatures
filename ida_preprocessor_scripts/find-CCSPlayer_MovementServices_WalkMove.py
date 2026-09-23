#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayer_MovementServices_WalkMove skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSPlayer_MovementServices_WalkMove",
]

# The old xref_strings anchor ("PlayerMove_PostMove") selected the small helper that *references*
# that string, not WalkMove (IDA-verified 14181; swiftlys2/cs2kz/modsharp all agree on the real
# body). Anchor on WalkMove's own head bytes per platform; abi_guard.py enforces the identity.
FUNC_XREFS_BY_PLATFORM = {
    "linux": [
        {
            "func_name": "CCSPlayer_MovementServices_WalkMove",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": [
                # 14182 head; 14181 was "... 4C 8D B5 ?? ?? ?? ?? 41 55 41 BD" (lea r14 / mov r13d,-1).
                "48 B8 ?? ?? ?? ?? ?? ?? ?? ?? 55 66 0F EF C0 48 89 E5 41 57 41 56 4C 8D BD ?? ?? ?? ?? 41 55 49 89 F5"
            ],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": ["PlayerMove_PostMove"],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
    "windows": [
        {
            "func_name": "CCSPlayer_MovementServices_WalkMove",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": [
                "48 8B C4 48 89 70 ?? 48 89 78 ?? 55 41 54 41 55 41 56 41 57 48 8D A8 ?? ?? ?? ?? 48 81 EC ?? ?? ?? ?? 0F 29 70 ?? 48 8B F1"
            ],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": ["PlayerMove_PostMove"],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
}
FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]  # kept for recipe importers; preprocess_skill picks per platform

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CCSPlayer_MovementServices_WalkMove",
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
        func_xrefs=FUNC_XREFS_BY_PLATFORM.get(platform, FUNC_XREFS),
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
