#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeClientServer_DeactivateLoop-inlined skill.

Resolves ``CLoopTypeClientServer_DeactivateLoop`` (a vfunc of ``CLoopTypeClientServer``)
as the single caller of ``CLoopTypeClientServer_WritePerfStats``.  This applies when
``DeactivateLoopInternal`` is inlined into ``DeactivateLoop`` so the
``if (m_bShouldWritePerfStats) WritePerfStats()`` guard (and thus the direct call to
``WritePerfStats``) lives inside the vfunc body itself.

It is the fallback for the ``find-CLoopTypeClientServer_DeactivateLoop-noinline`` path
(which handles the de-inlined case) and is skipped whenever
``CLoopTypeClientServer_DeactivateLoop.{platform}.yaml`` already exists.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeClientServer_DeactivateLoop",
]

FUNC_XREFS = [
    {
        "func_name": "CLoopTypeClientServer_DeactivateLoop",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [
            "CLoopTypeClientServer_WritePerfStats",
        ],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CLoopTypeClientServer_DeactivateLoop", "CLoopTypeClientServer"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    # NOTE: func_sig is intentionally omitted to match the -noinline path.  Although the
    # inlined vfunc body is large enough to sign, the de-inlined vfunc is a small forwarder
    # whose head bytes differ; dropping func_sig on both paths keeps the symbol's output
    # shape identical regardless of inline state.  The vtable slot (vfunc_offset/
    # vfunc_index) is the stable locator.
    (
        "CLoopTypeClientServer_DeactivateLoop",
        [
            "func_name",
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
