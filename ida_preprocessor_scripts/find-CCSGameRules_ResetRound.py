#!/usr/bin/env python3
"""Preprocess script for find-CCSGameRules_ResetRound skill.

Predecessor anchor for the PostCleanUp chain. CCSGameRules::ResetRound is the only function
that references the "GMR_ResetRound\\n" debug log string; PostCleanUp is the entity-cleanup
function it calls, resolved downstream via LLM_DECOMPILE.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSGameRules_ResetRound",
]

FUNC_XREFS = [
    {
        "func_name": "CCSGameRules_ResetRound",
        "xref_strings": [
            "GMR_ResetRound\n",
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
    # Include func_va/func_rva/func_size: this function is the predecessor for the
    # downstream find-CCSGameRules_PostCleanUp LLM_DECOMPILE step.
    (
        "CCSGameRules_ResetRound",
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
