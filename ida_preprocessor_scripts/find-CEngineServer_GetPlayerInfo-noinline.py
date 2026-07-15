#!/usr/bin/env python3
"""Preprocess script for find-CEngineServer_GetPlayerInfo-noinline skill.

Resolves ``CEngineServer_GetPlayerInfo`` (a vfunc of ``CEngineServer_vtable``) as the
single caller of the standalone ``GetPlayerInfo``.  This path only applies when
``GetPlayerInfo`` is NOT inlined into ``CEngineServer_GetPlayerInfo``; when it is
inlined the xref callee is absent and this skill legitimately produces nothing (its
output is optional), so the ``find-CEngineServer_GetPlayerInfo-inlined`` fallback runs
instead.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CEngineServer_GetPlayerInfo",
]

FUNC_XREFS = [
    {
        "func_name": "CEngineServer_GetPlayerInfo",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": ["GetPlayerInfo"],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

# CEngineServer_GetPlayerInfo is a vfunc of CEngineServer
FUNC_VTABLE_RELATIONS = [
    ("CEngineServer_GetPlayerInfo", "CEngineServer_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CEngineServer_GetPlayerInfo",
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
