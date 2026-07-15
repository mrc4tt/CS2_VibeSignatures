#!/usr/bin/env python3
"""Preprocess script for find-CNetworkGameServer_IsMapValid skill (deinline-fix chain, link 1/3).

Resolves the de-inlined ``CNetworkGameServer_IsMapValid`` helper -- the thin
``if (a2 && *a2) return IsMapValid(&g_MapListService, a2);`` guard that sits
between ``CEngineServer_IsMapValid`` and the string-owning ``IsMapValid`` body.

CS2 flips this inline state: on Linux 14168 the guard is a standalone function
and is the *sole* caller of ``IsMapValid`` (so ``xref_funcs: ["IsMapValid"]``
resolves it uniquely); on Windows (both versions) and Linux 14167 the guard is
inlined into ``CEngineServer_IsMapValid`` so no separate helper exists -- on
Windows there is no ``IsMapValid`` symbol at all, and on Linux 14167 ``IsMapValid``
has multiple callers, so this skill legitimately produces nothing (its output is
optional) and control falls through to ``find-CEngineServer_IsMapValid-inlined``.

``func_sig`` is intentionally omitted: the helper is a ~0x25-byte forwarding
guard whose head bytes do not sign uniquely, and it is re-derived from the
``xref_funcs`` intersection on every run, so ``func_va`` is all the downstream
``-noinline`` skill needs.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CNetworkGameServer_IsMapValid",
]

FUNC_XREFS = [
    {
        "func_name": "CNetworkGameServer_IsMapValid",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": ["IsMapValid"],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CNetworkGameServer_IsMapValid",
        [
            "func_name",
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
