#!/usr/bin/env python3
"""Preprocess script for find-CEntityIdentity_AcceptInputInternal skill.

Platform-independent: located via xref strings that are only present in the
function body regardless of whether the compiler keeps AcceptInputInternal as
a separate tail-called function (e.g. Linux 14167) or fully inlines it into
CEntityIdentity_AcceptInput (e.g. both platforms since 14168). In the inlined
case this resolves to the same func_va as CEntityIdentity_AcceptInput, which
is fine since only find-CEntityInstance_ScriptAcceptInput depends on it.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CEntityIdentity_AcceptInputInternal",
]

FUNC_XREFS = [
    {
        "func_name": "CEntityIdentity_AcceptInputInternal",
        "xref_strings": [
            "FULLMATCH:Input",
            "FULLMATCH:activator",
            "FULLMATCH:value",
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
        "CEntityIdentity_AcceptInputInternal",
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
    """Locate CEntityIdentity_AcceptInputInternal via unique xref strings and write YAML."""
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
