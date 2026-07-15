#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeClientServer_DeactivateLoopInternal skill.

Resolves the standalone ``CLoopTypeClientServer_DeactivateLoopInternal`` helper as the
single caller of ``CLoopTypeClientServer_WritePerfStats``.

This is the first link of the inline/noinline fallback chain.  On builds where
``DeactivateLoopInternal`` is de-inlined (e.g. Linux 14168) it is the function whose body
holds the ``if (m_bShouldWritePerfStats) WritePerfStats()`` guard, so it is the caller of
``WritePerfStats``.  On builds where it is inlined into
``CLoopTypeClientServer_DeactivateLoop`` the standalone helper is absent and the caller of
``WritePerfStats`` is the ``DeactivateLoop`` vfunc itself; in that case this skill's output
is optional and it is skipped whenever
``CLoopTypeClientServer_DeactivateLoop.{platform}.yaml`` already exists.

The helper symbol is deliberately NOT registered in config.yaml: in the inlined case it
would resolve to the ``DeactivateLoop`` vfunc's own address, which would be a wrong
gamedata entry.  The YAML is used only as an intermediate so the
``find-CLoopTypeClientServer_DeactivateLoop-noinline`` skill can key its xref_funcs lookup
off the renamed helper.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeClientServer_DeactivateLoopInternal",
]

FUNC_XREFS = [
    {
        "func_name": "CLoopTypeClientServer_DeactivateLoopInternal",
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

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopTypeClientServer_DeactivateLoopInternal",
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
