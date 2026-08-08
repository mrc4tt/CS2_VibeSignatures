#!/usr/bin/env python3
"""Preprocess script for find-CNetworkGameServer_IsPausable-noinline skill.

Deinline-fix chain, link 2/3.  Resolves ``CNetworkGameServer_IsPausable`` (a vfunc of
``CNetworkGameServer_vtable``) as the caller of the standalone
``CNetworkGameServer_IsPausable_OfflineCheck`` helper.  This path only applies when the
helper is NOT inlined into the vfunc (e.g. Linux 14174, where the ``offline`` /
``System/network`` strings live in the de-inlined ``sub_4F4EC0`` helper and IsPausable merely
calls it).  When the helper is inlined the helper YAML resolves to the vfunc's own address and
the ``func_xrefs`` vtable-self fallback re-selects it.  The ``CNetworkGameServer_vtable`` relation
alone does NOT collapse the caller set here: ``CNetworkGameServerBase::ConnectClient`` is also a
caller of the offline/network-session check helper AND a member of ``CNetworkGameServer_vtable``,
so it survives the vtable intersection alongside IsPausable (e.g. Linux 14174 yields
``{ConnectClient 0x504280, IsPausable 0x510460}``).  ``exclude_funcs`` drops ConnectClient (its
address is read from ``CNetworkGameServerBase_ConnectClient.{platform}.yaml``) to leave IsPausable
as the sole candidate.  Its output is optional, so when the caller cannot be resolved (e.g. the
helper YAML is absent because the inlined anchor was ambiguous) the
``find-CNetworkGameServer_IsPausable-inlined`` fallback runs instead.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CNetworkGameServer_IsPausable",
]

FUNC_XREFS = [
    {
        "func_name": "CNetworkGameServer_IsPausable",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [
            "CNetworkGameServer_IsPausable_OfflineCheck",
        ],
        "exclude_funcs": [
            "CNetworkGameServerBase_ConnectClient",
        ],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CNetworkGameServer_IsPausable", "CNetworkGameServer_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CNetworkGameServer_IsPausable",
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
