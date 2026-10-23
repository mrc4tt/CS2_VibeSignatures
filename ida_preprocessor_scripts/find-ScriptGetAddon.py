#!/usr/bin/env python3
"""Preprocess script for find-ScriptGetAddon skill.

MultiAddonManager calls this to learn which workshop addon the server runs. It
takes no arguments and returns the first mounted addon's workshop id as uint64
(IVApplication vfunc at +312 fills a CUtlVector of addon strings, then V_atoui64 on
the first).

No string of its own, so this relocates the previous gamever's func_sig. When that
fails, the anchor for the agent fallback is the caller: the function that prints
"Saving existing workshop save file from %s\n" calls it first, with no arguments,
and passes the result straight to the next call.

Confirmed on 14192 (rule 12): linux 0xb88db0, windows 0x18026e4a0, by that call and
by decompiling the body; MAM's own signatures land on both.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "ScriptGetAddon",
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "ScriptGetAddon",
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
    """Reuse previous gamever func_sig to locate the target function and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
