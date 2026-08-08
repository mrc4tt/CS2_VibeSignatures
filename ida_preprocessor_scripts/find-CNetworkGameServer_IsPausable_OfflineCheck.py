#!/usr/bin/env python3
"""Preprocess script for find-CNetworkGameServer_IsPausable_OfflineCheck skill.

Deinline-fix chain, link 1/3.  Resolves the standalone offline/network-session check helper
that ``CNetworkGameServerBase::IsPausable`` calls, anchored on the ``"offline"`` +
``"System/network"`` VProf strings the helper owns (both must be referenced -- the two are
AND-intersected, which excludes the unrelated ``sv_lan`` helper that references ``"offline"``
alongside the lowercase ``"system/network"`` literal instead).

This is the first link of the inline/noinline fallback chain.  On builds where the helper is
de-inlined (e.g. Linux 14174, standalone ``sub_4F4EC0``) the strings live inside the helper
body, so this skill resolves it directly.  On builds where the helper is inlined into the
``CNetworkGameServer_IsPausable`` vfunc (e.g. Windows 14174) the ``offline`` +
``System/network`` intersection yields >1 function (the vfunc plus a standalone sibling), so
this skill soft-skips and control falls through to ``find-CNetworkGameServer_IsPausable-inlined``
whose string-cap-vtable intersection is the load-bearing path.  The helper symbol is
deliberately NOT registered in the active version config -- the YAML is used only as an
intermediate for the ``find-CNetworkGameServer_IsPausable-noinline`` xref_funcs lookup.  The
skill's output is optional and is skipped whenever
``CNetworkGameServer_IsPausable.{platform}.yaml`` already exists.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CNetworkGameServer_IsPausable_OfflineCheck",
]

FUNC_XREFS = [
    {
        "func_name": "CNetworkGameServer_IsPausable_OfflineCheck",
        "xref_strings": [
            "FULLMATCH:offline",
            "FULLMATCH:System/network",
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
        "CNetworkGameServer_IsPausable_OfflineCheck",
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
