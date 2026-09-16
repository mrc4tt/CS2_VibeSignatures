#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayer_MovementServices_ProcessMovement skill."""

from abi_guard import make_llm_result_validator
from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSPlayer_MovementServices_ProcessMovement",
]

# ProcessMovement is VIRTUAL (CCSPlayer_MovementServices vtable slot 29 linux / 28 windows on
# 14181). The old anchor (s_pRunCommandPawn gv + floats) selected the non-virtual caller helper
# instead (IDA-verified). Anchor on the function's own head bytes and require vtable membership
# via FUNC_VTABLE_RELATIONS, so a wrong candidate can never pass.
FUNC_XREFS_BY_PLATFORM = {
    "linux": [
        {
            "func_name": "CCSPlayer_MovementServices_ProcessMovement",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["55 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 53 48 89 FB 48 83 EC ?? 48 8B 7F"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
    "windows": [
        {
            "func_name": "CCSPlayer_MovementServices_ProcessMovement",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["40 57 41 57 48 81 EC ?? ?? ?? ?? 48 83 79"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
}
FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]  # kept for recipe importers; preprocess_skill picks per platform

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class) - candidates are intersected with this class's vtable entries
    ("CCSPlayer_MovementServices_ProcessMovement", "CCSPlayer_MovementServices"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CCSPlayer_MovementServices_ProcessMovement",
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
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        # ABI guard: reject LLM-fallback candidates with a known-bad function head (see abi_guard.py)
        llm_result_validator=make_llm_result_validator(
            "CCSPlayer_MovementServices_ProcessMovement", platform, new_binary_dir
        ),
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
