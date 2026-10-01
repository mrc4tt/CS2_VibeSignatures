#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayerPawn_CreatePlayerPawnServices skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = ["CCSPlayerPawn_CreatePlayerPawnServices"]
# The function allocates each pawn service, stores it on the pawn and hands it the
# pawn. Up to 14181 it also carried the literal "m_pBulletServices" (an inlined
# NetworkStateChanged); from 14182 on that literal is referenced only by the schema
# registration, so a string anchor finds nothing. The anchor is the store-and-init
# step instead, which every service repeats:
#   linux    mov [rbx+disp32], r12 ; mov rsi, rbx ; mov rdi, r12 ; call   (14157-14188)
#   windows  mov rdx, this ; mov [this+disp32], rax ; mov rcx, rax ; call  (14157-14188)
# Neither is unique in the binary (7-13 hits); among the CCSPlayerPawn vtable entries,
# which FUNC_VTABLE_RELATIONS restricts the xref path to, each is.
FUNC_XREFS_BY_PLATFORM = {
    "linux": [
        {
            "func_name": "CCSPlayerPawn_CreatePlayerPawnServices",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["4C 89 A3 ?? ?? 00 00 48 89 DE 4C 89 E7 E8"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
    "windows": [
        {
            "func_name": "CCSPlayerPawn_CreatePlayerPawnServices",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["48 8B ?? 48 89 ?? ?? ?? 00 00 48 8B C8 E8"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
}
FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]  # kept for recipe importers; preprocess_skill picks per platform
FUNC_VTABLE_RELATIONS = [("CCSPlayerPawn_CreatePlayerPawnServices", "CCSPlayerPawn_vtable")]
GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSPlayerPawn_CreatePlayerPawnServices",
        ["func_name", "func_va", "func_rva", "func_size", "func_sig", "vtable_name", "vfunc_offset", "vfunc_index"],
    )
]


async def preprocess_skill(
    session, skill_name, expected_outputs, old_yaml_map, new_binary_dir, platform, image_base, debug=False
):
    """Relocate the pawn-services vfunc; fall back to the store-and-init anchor."""
    _ = skill_name
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=FUNC_XREFS_BY_PLATFORM.get(platform, FUNC_XREFS),
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
