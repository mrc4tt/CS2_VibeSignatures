#!/usr/bin/env python3
"""Preprocess script for find-GetPlayerInfo skill.

Resolves the standalone ``GetPlayerInfo`` helper from the exact ``"userinfo"`` string
reference.  Several sibling functions reference ``"userinfo"`` too, so the three vtable
members that share it (``CNetworkGameServerBase_GetPlayerInfo``,
``CServerSideClientBase_Connect``, ``CServerSideClientBase_GetPlayerInfo``) are excluded
by ``exclude_funcs`` and the demo/query recorders are excluded by ``exclude_strings``.

This is the first link of the inline/noinline fallback chain: when ``GetPlayerInfo`` is
inlined into ``CEngineServer_GetPlayerInfo`` the standalone helper is absent, so this
skill's output is optional and it is skipped whenever
``CEngineServer_GetPlayerInfo.{platform}.yaml`` already exists.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "GetPlayerInfo",
]

FUNC_XREFS = [
    {
        "func_name": "GetPlayerInfo",
        "xref_strings": [
            "FULLMATCH:userinfo",
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [
            "CNetworkGameServerBase_GetPlayerInfo",
            "CServerSideClientBase_Connect",
            "CServerSideClientBase_GetPlayerInfo",
        ],
        "exclude_strings": [
            "FULLMATCH:[demoscrub]",
            "FULLMATCH:server_query_info",
        ],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "GetPlayerInfo",
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
