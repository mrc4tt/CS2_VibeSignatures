#!/usr/bin/env python3
"""Preprocess script for find-CServerSideClientBase_dtor skill.

Resolves ``CServerSideClientBase_dtor`` (a regular, non-virtual function in the
engine module) from the exact ``"Destruct"`` debug string cross-reference.
``FULLMATCH:`` is used so only the exact ``"Destruct"`` string matches, not
substrings such as ``"Destructor"``.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CServerSideClientBase_dtor",
]

FUNC_XREFS = [
    {
        "func_name": "CServerSideClientBase_dtor",
        "xref_strings": [
            "FULLMATCH:Destruct",
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
    (
        "CServerSideClientBase_dtor",
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
