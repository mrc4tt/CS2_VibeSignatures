#!/usr/bin/env python3
"""Preprocess script for find-CMapListService_IsMapValid-noinline skill (deinline-fix chain).

Resolves ``CMapListService_IsMapValid`` (a vfunc of ``CMapListService_vtable``) for
the build where the vtable member is a thin wrapper that calls the standalone
string-owning ``IsMapValid`` body -- i.e. the body is NOT inlined into the vtable
member (Linux 14167).  The wrapper is the only ``CMapListService_vtable`` member that
calls ``IsMapValid``, so ``xref_funcs: ["IsMapValid"]`` intersected with the vtable
collapses to it uniquely (``CEngineServer_ChangeLevel`` / ``CEngineServer_IsMapValid``
also call ``IsMapValid`` but live in ``CEngineServer_vtable``).

When the body is fused into the vtable member instead (Windows both versions, where
there is no standalone ``IsMapValid`` symbol; and Linux 14168, where the member *is*
``IsMapValid`` so its only caller is ``CNetworkGameServer_IsMapValid``, which is not a
``CMapListService_vtable`` member) this path produces nothing (its output is optional)
and the ``find-CMapListService_IsMapValid-inlined`` fallback runs instead.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CMapListService_IsMapValid",
]

FUNC_XREFS = [
    {
        "func_name": "CMapListService_IsMapValid",
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

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CMapListService_IsMapValid", "CMapListService_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CMapListService_IsMapValid",
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
