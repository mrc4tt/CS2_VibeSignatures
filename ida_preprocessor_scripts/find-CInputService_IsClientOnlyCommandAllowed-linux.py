#!/usr/bin/env python3
"""Preprocess script for find-CInputService_IsClientOnlyCommandAllowed-linux skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CInputService_IsClientOnlyCommandAllowed",
]

FUNC_XREFS = [
    {
        "func_name": "CInputService_IsClientOnlyCommandAllowed",
        "xref_strings": [],
        # On Linux the FCVAR_CLIENTCMD_CAN_EXECUTE gate that Windows inlines into
        # CInputService::ProcessConVar / ProcessCommand is emitted as this shared
        # 84-byte helper: it branches on a server-service vfunc and then calls
        # either another server-service vfunc or INetworkClientService::
        # IsPutInServer. It is the ONLY function that references both service
        # globals AND calls the server-service vfuncs at 0xf0 and 0xd0 (verified:
        # 20 functions reference both globals; the 3-way intersection is unique).
        "xref_gvs": [
            "g_pNetworkClientService",
            "g_pNetworkServerService",
        ],
        "xref_signatures": [
            "FF 90 F0 00 00 00",
            "FF 90 D0 00 00 00",
        ],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    # func_va/func_rva/func_size are required: this helper is the Linux
    # LLM_DECOMPILE predecessor of find-CInputService_ProcessConVar-decompiles.
    (
        "CInputService_IsClientOnlyCommandAllowed",
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
    """Reuse previous gamever func_sig to locate the Linux de-inlined command-gate helper."""
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
