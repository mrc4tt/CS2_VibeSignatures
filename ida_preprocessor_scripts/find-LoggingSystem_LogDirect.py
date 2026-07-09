#!/usr/bin/env python3
"""Preprocess script for find-LoggingSystem_LogDirect skill.

Internal, non-exported LogDirect worker in tier0. Every exported
LoggingSystem_LogDirect* variadic wrapper forwards to it; the robust discovery
(intersect the wrappers' call targets) is documented in SKILL.md and handled by
the agent fallback. This preprocess reuses the previous gamever's func_sig to
relocate the worker on a fresh binary. On failure the runner falls back to the
agent SKILL.md.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "LoggingSystem_LogDirect",
]

FUNC_XREFS = [
    {
        "func_name": "LoggingSystem_LogDirect",
        "xref_strings": [],
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
        "LoggingSystem_LogDirect",
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
    _ = skill_name

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
