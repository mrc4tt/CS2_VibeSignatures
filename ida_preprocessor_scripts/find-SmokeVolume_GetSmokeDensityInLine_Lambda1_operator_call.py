#!/usr/bin/env python3
"""Preprocess script for find-SmokeVolume_GetSmokeDensityInLine_Lambda1_operator_call skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "SmokeVolume_GetSmokeDensityInLine_Lambda1_operator_call",
]

FUNC_XREFS = [
    {
        "func_name": "SmokeVolume_GetSmokeDensityInLine_Lambda1_operator_call",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [
            "C3 30 0C 03",
            "C6 00 01",
        ],
        "xref_funcs": [],
        "xref_floats": [
            "50.0",
        ],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [
            "g_GameTraceManager",
        ],
        "exclude_signatures": [],
        "exclude_floats": [
            "0.2",
            "6.0",
            "1.2",
        ],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "SmokeVolume_GetSmokeDensityInLine_Lambda1_operator_call",
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
    """Locate the GetSmokeDensityInLine lambda call operator via xref intersections."""
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
