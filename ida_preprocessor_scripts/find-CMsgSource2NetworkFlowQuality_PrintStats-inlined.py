#!/usr/bin/env python3
"""Preprocess script for find-CMsgSource2NetworkFlowQuality_PrintStats-inlined skill.

Resolves ``CMsgSource2NetworkFlowQuality_PrintStats`` directly from the
``"Bandwidth . . . . . . . : Total:%.1fkb"`` status string.  This path is correct
whenever ``CMsgSource2NetworkFlowQuality_PrintStatsInternal`` (the actual printing
body that owns that string) is *inlined* into ``PrintStats`` -- i.e. ``PrintStats``
is the single fused function that both holds the string and is called by
``CEngineServer_DumpNetStats`` / ``CNetworkGameClient_PrintNetStats`` (Windows on all
observed builds; Linux <= 14167).

When the body is *de-inlined* (Linux 14168+), the string moves out of ``PrintStats``
(a thin guard wrapper) into the standalone ``PrintStatsInternal``, so this finder would
resolve to ``PrintStatsInternal`` instead of the wrapper.  In that case the
``find-CMsgSource2NetworkFlowQuality_PrintStats-noinline`` fallback runs first and
produces the correct wrapper address, and this skill is skipped via ``skip_if_exists``.

``PrintStats`` is a regular function (not a vfunc), so ``func_sig`` is its stable
cross-build locator and is retained.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CMsgSource2NetworkFlowQuality_PrintStats",
]

FUNC_XREFS = [
    {
        "func_name": "CMsgSource2NetworkFlowQuality_PrintStats",
        "xref_strings": [
            "Bandwidth . . . . . . . : Total:%.1fkb",
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
        "CMsgSource2NetworkFlowQuality_PrintStats",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
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
