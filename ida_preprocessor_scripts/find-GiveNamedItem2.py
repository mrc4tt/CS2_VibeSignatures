#!/usr/bin/env python3
"""Preprocess script for find-GiveNamedItem2 skill.

GiveNamedItem2 is a small thunk that zeroes the trailing args and tail-jumps
into GiveNamedItem:

    xor r9d, r9d
    xor r8d, r8d
    xor ecx, ecx
    xor edx, edx
    jmp  GiveNamedItem        ; linux: 45 31 C9 45 31 C0 31 C9 31 D2 E9 ? ? ? ?

It has no debug string and is not a vtable slot, so it is discovered as a
caller (tail-jmp) of the already-known GiveNamedItem (Pattern A,
static FUNC_XREFS via xref_funcs). Across game updates the previous gamever
func_sig relocates it; xref_funcs is the bootstrap/fallback anchor.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "GiveNamedItem2",
]

FUNC_XREFS = [
    {
        "func_name": "GiveNamedItem2",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": ["GiveNamedItem"],  # thunk tail-jmps into GiveNamedItem
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "GiveNamedItem2",
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
