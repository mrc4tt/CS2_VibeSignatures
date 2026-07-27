#!/usr/bin/env python3
"""Preprocess script for find-CInputService_ProcessConVar skill."""

from ida_analyze_util import preprocess_common_skill


TARGET_FUNCTION_NAMES = [
    "CInputService_ProcessConVar",
]

FUNC_XREFS = [
    {
        "func_name": "CInputService_ProcessConVar",
        # Substring matching is intentional here: the literals carry a trailing
        # "\n", and "%s = %s" is also a substring of the CalcDelta warning
        # string. The intersection with "Unknown convar '%s'!" collapses the
        # candidate set to the convar-echo path inside ProcessConVar.
        "xref_strings": [
            "%s = %s",
            "Unknown convar '%s'!",
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
    # (symbol_name, generate_yaml_fields)
    # func_va/func_rva/func_size are required: this function is the
    # LLM_DECOMPILE predecessor of find-CInputService_ProcessConVar-decompiles.
    (
        "CInputService_ProcessConVar",
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
    """Reuse previous gamever func_sig to locate CInputService::ProcessConVar."""
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
