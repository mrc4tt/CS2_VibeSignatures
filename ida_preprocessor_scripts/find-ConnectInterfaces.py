#!/usr/bin/env python3
"""Preprocess script for find-ConnectInterfaces skill."""

from copy import deepcopy
from pathlib import Path

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "ConnectInterfaces",
]

FUNC_XREFS = [
    {
        "func_name": "ConnectInterfaces",
        "xref_strings": [
            "APPSYSTEM: In ConnectInterfaces(), s_nRegistrationCount is %d!",
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": ["CNetSupportImpl_Connect"],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "ConnectInterfaces",
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
    func_xrefs = deepcopy(FUNC_XREFS)
    module_name = Path(new_binary_dir).name.casefold() if new_binary_dir else ""
    if module_name != "engine":
        func_xrefs[0]["exclude_funcs"] = []

    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=func_xrefs,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
