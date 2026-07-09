#!/usr/bin/env python3
"""Preprocess script for find-CNetworkGameServerBase_GetPlayerInfo skill.

Resolves ``CNetworkGameServerBase_GetPlayerInfo`` (a vfunc of
``CNetworkGameServerBase_vtable``) from the exact ``"userinfo"`` string reference.
The ``CNetworkGameServerBase_vtable`` intersection collapses the multiple
``"userinfo"`` string references down to the single vtable member.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CNetworkGameServerBase_GetPlayerInfo",
]

FUNC_XREFS = [
    {
        "func_name": "CNetworkGameServerBase_GetPlayerInfo",
        "xref_strings": [
            "FULLMATCH:userinfo",
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
        # On Linux a second CNetworkGameServerBase_vtable entry (the fake-client
        # connect path) also references "userinfo"; it calls
        # CNetworkGameServer_GetFreeClient, which GetPlayerInfo does not, so it is
        # dropped via exclude_callees (exclude candidates that call the named func).
        # Windows has only the single GetPlayerInfo candidate, so this is a no-op there.
        "exclude_callees": ["CNetworkGameServer_GetFreeClient"],
    },
]

# CNetworkGameServerBase_GetPlayerInfo is a vfunc of CNetworkGameServerBase
FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CNetworkGameServerBase_GetPlayerInfo", "CNetworkGameServerBase_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CNetworkGameServerBase_GetPlayerInfo",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
            "vtable_name",
            "vfunc_offset",
            "vfunc_index",
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
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
