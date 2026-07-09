#!/usr/bin/env python3
"""Preprocess script for find-Setang_CommandHandler skill.

Anchor for the SnapViewAngles chain. The "setang" console command handler is the only
function that references the setang usage string; SnapViewAngles is the function it calls
in its non-teleport (else) branch, resolved downstream via LLM_DECOMPILE.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "Setang_CommandHandler",
]

FUNC_XREFS = [
    {
        "func_name": "Setang_CommandHandler",
        "xref_strings": [
            "Usage:  setang pitch yaw <roll optional> <prediction sync ticks optional>\n",
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # Include func_va/func_rva/func_size: this function is a predecessor for the
    # downstream find-CCSPlayerPawn_SnapViewAngles LLM_DECOMPILE step.
    (
        "Setang_CommandHandler",
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
