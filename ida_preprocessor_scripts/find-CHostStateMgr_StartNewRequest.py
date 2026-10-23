#!/usr/bin/env python3
"""Preprocess script for find-CHostStateMgr_StartNewRequest skill.

MultiAddonManager hooks this (its HostStateRequest signature) to add its addons to
the map change request. String-anchored: the function alone prints

    Discarding pending request '%s, %u'

when a request is already queued (it then frees the old request and stores the new
one at this+0x30).

Confirmed on 14192 (rule 12): linux 0x38d360, windows 0x18021e480; each is the only
function referencing the string, and MAM's own signatures land on both.
`preprocess_common_skill` tries relocation first; the xref is the fallback.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CHostStateMgr_StartNewRequest",
]

FUNC_XREFS = [
    {
        "func_name": "CHostStateMgr_StartNewRequest",
        "xref_strings": [
            "Discarding pending request '%s, %u'\n",
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
        "CHostStateMgr_StartNewRequest",
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
