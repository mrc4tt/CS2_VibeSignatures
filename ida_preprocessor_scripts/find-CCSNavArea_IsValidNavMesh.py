#!/usr/bin/env python3
"""Preprocess script for find-CCSNavArea_IsValidNavMesh skill.

Tiny non-string predicate: returns `g_pNavMesh != nullptr`. Whole body is 15 bytes
(`lea rax, g_pNavMesh ; cmp qword ptr [rax], 0 ; setnz al ; retn`), referenced only from a
vtable slot. No debug string to anchor on, and `g_pNavMesh` has 200+ referencers, so the
function is pinned by intersecting the g_pNavMesh reference with the distinctive tail byte
pattern `48 83 38 ? 0F 95 C0 C3` (cmp [rax],0 ; setnz al ; retn), which is unique in .text.
Windows has no separate load (`cmp qword ptr [rip+g_pNavMesh], 0`), so it gets its own pattern.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSNavArea_IsValidNavMesh",
]

FUNC_XREFS_BY_PLATFORM = {
    "linux": [
        {
            "func_name": "CCSNavArea_IsValidNavMesh",
            "xref_strings": [],
            "xref_gvs": ["g_pNavMesh"],
            # cmp qword ptr [rax], 0 ; setnz al ; retn  -> unique in .text on its own,
            # intersected with the g_pNavMesh reference for forward robustness.
            "xref_signatures": ["48 83 38 ? 0F 95 C0 C3"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
    "windows": [
        {
            "func_name": "CCSNavArea_IsValidNavMesh",
            "xref_strings": [],
            "xref_gvs": ["g_pNavMesh"],
            # MSVC folds the load into the compare: cmp qword ptr [rip+g_pNavMesh], 0 ;
            # setnz al ; retn. Two hits in .text on 14157-14188; the g_pNavMesh
            # reference picks the right one on every build.
            "xref_signatures": ["48 83 3D ?? ?? ?? ?? 00 0F 95 C0 C3"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
}
FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]  # kept for recipe importers; preprocess_skill picks per platform

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CCSNavArea_IsValidNavMesh",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
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
