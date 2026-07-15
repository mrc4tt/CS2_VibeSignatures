#!/usr/bin/env python3
"""Preprocess script for find-CServerSideClientBase_Connect skill.

Resolves ``CServerSideClientBase_Connect`` (a vfunc of ``CServerSideClientBase_vtable``)
from the intersection of the exact ``"userinfo"`` string and the
``"CServerSideClientBase::Connect"`` string.  The ``"CServerSideClientBase::Connect"``
string distinguishes ``Connect`` from its vtable-mate
``CServerSideClientBase_GetPlayerInfo`` (which also references ``"userinfo"`` but not
the ``Connect`` name string).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CServerSideClientBase_Connect",
]

FUNC_XREFS = [
    {
        "func_name": "CServerSideClientBase_Connect",
        "xref_strings": [
            "FULLMATCH:userinfo",
            "CServerSideClientBase::Connect",
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

# CServerSideClientBase_Connect is a vfunc of CServerSideClientBase
FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CServerSideClientBase_Connect", "CServerSideClientBase_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CServerSideClientBase_Connect",
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
