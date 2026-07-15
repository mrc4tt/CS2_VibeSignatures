#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeBase_LoadDependentServices-noinline skill.

Resolves ``CLoopTypeBase_LoadDependentServices`` as the single caller of the standalone
``CLoopTypeBase_AddDependentServices`` helper.  This path only applies when the
dependency helpers are NOT inlined into ``LoadDependentServices`` (Windows: de-inlined),
so the parent still contains a direct call to the standalone helper.

When the helpers ARE inlined (Linux), the standalone ``AddDependentServices`` is absent,
so the xref callee cannot be resolved and this skill legitimately produces nothing (its
output is optional); the ``find-CLoopTypeBase_LoadDependentServices-inlined`` fallback
runs instead.

``CLoopTypeBase_LoadDependentServices`` is a regular function (not a vfunc), so ``func_sig``
is its stable cross-build locator and is retained (no vtable slot is available).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeBase_LoadDependentServices",
]

FUNC_XREFS = [
    {
        "func_name": "CLoopTypeBase_LoadDependentServices",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": ["CLoopTypeBase_AddDependentServices"],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopTypeBase_LoadDependentServices",
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
