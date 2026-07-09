#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeBase_LoadDependentServices-inlined skill.

Resolves ``CLoopTypeBase_LoadDependentServices`` directly from the intersection of the
three dependency-helper assertion strings.  This applies when the helpers
(``AddDependentServices``, ``GenerateServiceDependencies``,
``GenerateSecondaryDependencies``) are inlined into ``LoadDependentServices`` (Linux), so
all three assertion strings live inside the single parent function body and their string
xrefs AND-intersect to exactly that function.

This is the fallback for the ``find-CLoopTypeBase_LoadDependentServices-noinline`` path
(which handles the de-inlined case via ``xref_funcs``) and is skipped whenever
``CLoopTypeBase_LoadDependentServices.{platform}.yaml`` already exists (Windows, where the
-noinline path wins).  ``LoadDependentServices`` is a regular function, so ``func_sig`` is
its stable cross-build locator and is retained.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeBase_LoadDependentServices",
]

FUNC_XREFS = [
    {
        "func_name": "CLoopTypeBase_LoadDependentServices",
        # Multiple xref_strings are AND-intersected: the target is the single
        # function that references all three inlined-helper assertion strings.
        "xref_strings": [
            'Unable to find service "%s" which is depended on by service "%s"!',
            'Service "%s" is specified to both run before and after service "%s"!',
            'Loop "%s" contains a circular dependency with service "%s"!',
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
