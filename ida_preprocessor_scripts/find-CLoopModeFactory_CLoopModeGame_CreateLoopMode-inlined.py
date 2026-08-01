#!/usr/bin/env python3
"""Preprocess script for find-CLoopModeFactory_CLoopModeGame_CreateLoopMode-inlined skill.

Resolves ``CLoopModeFactory_CLoopModeGame_CreateLoopMode`` (a vfunc of
``CLoopModeFactory_CLoopModeGame_vtable``) directly from the
``"%s:  CLoopModeGame constructed\n"`` debug string reference.  This applies when
``CLoopModeGame_ctor`` is inlined into ``CreateLoopMode`` so the constructor's anchor
string lives inside the factory method body.  The trailing newline is dropped from the
xref pattern because IDA lists the string literal without it; substring matching still
resolves the factory method.  It is the fallback for the
``find-CLoopModeFactory_CLoopModeGame_CreateLoopMode-noinline`` path (which handles the
de-inlined case) and is skipped whenever
``CLoopModeFactory_CLoopModeGame_CreateLoopMode.{platform}.yaml`` already exists.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopModeFactory_CLoopModeGame_CreateLoopMode",
]

FUNC_XREFS = [
    {
        "func_name": "CLoopModeFactory_CLoopModeGame_CreateLoopMode",
        "xref_strings": [
            "%s:  CLoopModeGame constructed",
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

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CLoopModeFactory_CLoopModeGame_CreateLoopMode", "CLoopModeFactory_CLoopModeGame_vtable"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopModeFactory_CLoopModeGame_CreateLoopMode",
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
