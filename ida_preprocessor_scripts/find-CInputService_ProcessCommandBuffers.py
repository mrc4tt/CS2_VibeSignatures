#!/usr/bin/env python3
"""Preprocess script for find-CInputService_ProcessCommandBuffers skill."""

from ida_analyze_util import preprocess_common_skill


TARGET_FUNCTION_NAMES = [
    "CInputService_ProcessCommandBuffers",
]

FUNC_XREFS = [
    {
        "func_name": "CInputService_ProcessCommandBuffers",
        "xref_strings": [
            "FULLMATCH:__beginseq",
            "FULLMATCH:__endseq",
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": ["CInputService_ProcessCommand"],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CInputService_ProcessCommandBuffers",
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
    """Reuse previous gamever func_sig to locate CInputService::ProcessCommandBuffers."""
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
