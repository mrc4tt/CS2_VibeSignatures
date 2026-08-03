#!/usr/bin/env python3
"""Preprocess script for find-CSource2GameClients_ClientSetupVisibility skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CSource2GameClients_ClientSetupVisibility",
]

FUNC_XREFS = [
    {
        "func_name": "CSource2GameClients_ClientSetupVisibility",
        "xref_strings": [],
        # g_pEntitySystem disambiguates the target from the other three
        # CSource2GameClients vtable members that also call both xref_funcs
        # (slots 16 ClientDisconnect, 23, 38); only ClientSetupVisibility
        # references g_pEntitySystem. Verified on both windows and linux.
        "xref_gvs": ["g_pEntitySystem"],
        "xref_signatures": [],
        "xref_funcs": [
            "UTIL_PlayerSlotToPlayerController",
            "CBasePlayerController_GetPawn",
        ],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CSource2GameClients_ClientSetupVisibility", "CSource2GameClients_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CSource2GameClients_ClientSetupVisibility",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
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
