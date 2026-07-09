#!/usr/bin/env python3
"""Preprocess script for find-CMsgSource2NetworkFlowQuality_PrintStatsInternal skill.

Locates the standalone ``CMsgSource2NetworkFlowQuality_PrintStatsInternal`` (the printing
body that owns the ``"Bandwidth . . . . . . . : Total:%.1fkb"`` status string) via that
string.  It exists as a distinct function only when the body is de-inlined out of the
``PrintStats`` guard wrapper (Linux 14168+); this skill is registered ``platform: linux``
because on Windows the body is always fused into ``PrintStats`` and no separate ``Internal``
function exists.

Its output is optional and intentionally NOT registered as a gamedata symbol: it is only an
intermediate anchor for ``find-CMsgSource2NetworkFlowQuality_PrintStats-noinline`` (which
resolves the wrapper as the caller of ``Internal`` other than ``CNetworkGameClient_PrintNetStats``).
On the still-fused Linux 14167 build the string resolves to the fused ``PrintStats`` itself;
that is harmless (unregistered, and the ``-noinline`` intersection then soft-skips because the
fused function has more than one non-``PrintNetStats`` caller).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CMsgSource2NetworkFlowQuality_PrintStatsInternal",
]

FUNC_XREFS = [
    {
        "func_name": "CMsgSource2NetworkFlowQuality_PrintStatsInternal",
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
        "CMsgSource2NetworkFlowQuality_PrintStatsInternal",
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
