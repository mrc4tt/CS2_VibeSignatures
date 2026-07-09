#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeClientServer_DeactivateLoop-noinline skill.

Resolves ``CLoopTypeClientServer_DeactivateLoop`` (a vfunc of ``CLoopTypeClientServer``)
as the single caller of the standalone ``CLoopTypeClientServer_DeactivateLoopInternal``.
This path only applies when ``DeactivateLoopInternal`` is NOT inlined into
``DeactivateLoop`` (e.g. Linux 14168, where ``DeactivateLoop`` merely calls
``DeactivateLoopInternal`` then a vtable method).  When it is inlined the xref callee is
absent and this skill legitimately produces nothing (its output is optional), so the
``find-CLoopTypeClientServer_DeactivateLoop-inlined`` fallback runs instead.
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
            "CLoopTypeClientServer_DeactivateLoopInternal",
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
    # NOTE: func_sig is intentionally omitted so the DeactivateLoop vfunc output has an
    # identical shape regardless of inline state.  On the de-inlined build the vfunc body
    # is a small forwarder (call DeactivateLoopInternal / vtable call) whose head bytes
    # differ from the large inlined body, so the vtable slot (vfunc_offset/vfunc_index) is
    # the stable locator instead.  The -inlined fallback drops func_sig too so the symbol's
    # output shape does not depend on which path wins.
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
