#!/usr/bin/env python3
"""Preprocess script for find-CWorldRendererMgr_CreateWorld_Internal skill.

String-anchored rather than relocation-only, because this symbol is fork-owned and
has no baseline in any earlier gamever: a relocation preprocessor would fail on its
first run and every re-run of 14181. The anchor is the function's own name, which it
prints in its bail-out path, and which both binaries carry verbatim:

    CWorldRendererMgr::CreateWorld_Internal( %s ):  Blocking load because marked for
    deletion during load

Confirmed on 14181 (rule 12 - a unique sig match alone would only prove *a* function
head was found):
  linux   0x2b1180,    lea at 0x2b1622  -> the string at 0x16ad88
  windows 0x18002b1a0, lea at 0x18002b2ad -> the string at 0x180195940

`preprocess_common_skill` still tries relocation first, so from the gamever after
the first one this costs nothing; the xref is the fallback that makes the first run
- and any run whose baseline sig has gone stale - resolve on its own.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CWorldRendererMgr_CreateWorld_Internal",
]

FUNC_XREFS = [
    {
        "func_name": "CWorldRendererMgr_CreateWorld_Internal",
        "xref_strings": [
            "CWorldRendererMgr::CreateWorld_Internal( %s ):  Blocking load because marked for deletion during load",
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
        "CWorldRendererMgr_CreateWorld_Internal",
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
