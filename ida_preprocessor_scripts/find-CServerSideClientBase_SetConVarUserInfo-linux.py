#!/usr/bin/env python3
"""Preprocess script for find-CServerSideClientBase_SetConVarUserInfo-linux skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CServerSideClientBase_SetConVarUserInfo",
]

FUNC_XREFS = [
    {
        "func_name": "CServerSideClientBase_SetConVarUserInfo",
        "xref_strings": [],
        # On Linux the ISource2GameClients::ClientSetConVarUserInfoSet dispatch
        # that Windows inlines into CServerSideClientBase::~CServerSideClientBase
        # is emitted as this shared out-of-line helper. Its ClientSetConVarUserInfoSet
        # vcall (g_pSource2GameClients slot 18, offset 0x90) is TAIL-CALL OPTIMIZED,
        # so it appears as `mov rax, [rax+90h]` (48 8B 80 90 00 00 00) followed by
        # `jmp rax`, NOT as `call qword ptr [rax+90h]` -- there is no
        # `FF 90 90 00 00 00` byte sequence in this helper (that pattern lives in an
        # unrelated function). 36 functions reference g_pSource2GameClients; the
        # intersection with the `mov rax,[rax+90h]` load byte-signature is unique to
        # this helper on the whole binary.
        "xref_gvs": [
            "g_pSource2GameClients",
        ],
        "xref_signatures": [
            "48 8B 80 90 00 00 00",
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
    # LLM_DECOMPILE predecessor of find-CServerSideClientBase_dtor-decompiles.
    (
        "CServerSideClientBase_SetConVarUserInfo",
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
    """Locate the Linux de-inlined ClientSetConVarUserInfoSet dispatch helper."""
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
