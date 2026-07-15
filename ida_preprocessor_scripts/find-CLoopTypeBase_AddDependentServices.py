#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeBase_AddDependentServices skill.

Resolves the standalone ``CLoopTypeBase_AddDependentServices`` helper from its
assertion string ``Unable to find service "%s" which is depended on by service "%s"!``.

This is the first link of the inline/noinline fallback chain for
``CLoopTypeBase_LoadDependentServices``.  ``AddDependentServices`` is a separate
function on some builds (Windows: de-inlined) but is inlined into
``CLoopTypeBase_LoadDependentServices`` on others (Linux), where the assertion string
lives inside the parent function body.

To keep this skill from mis-resolving the parent as the helper in the inlined case, the
two sibling-helper assertion strings are excluded:
``Service "%s" is specified to both run before and after service "%s"!`` (from
``CLoopTypeBase_GenerateServiceDependencies``) and
``Loop "%s" contains a circular dependency with service "%s"!`` (from
``CLoopTypeBase_GenerateSecondaryDependencies``).  Those two helpers are also inlined
into ``CLoopTypeBase_LoadDependentServices`` on Linux, so in the inlined case the single
function that references the ``Unable to find service`` string ALSO references the other
two -- excluding them collapses the Linux match to zero and this skill soft-skips
(``optional_output``), yielding to the ``-inlined`` fallback.  On Windows the standalone
helper references only its own string, so the exclusion is a no-op and it resolves
normally.  This skill is also skipped whenever
``CLoopTypeBase_LoadDependentServices.{platform}.yaml`` already exists.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeBase_AddDependentServices",
]

FUNC_XREFS = [
    {
        "func_name": "CLoopTypeBase_AddDependentServices",
        "xref_strings": [
            'Unable to find service "%s" which is depended on by service "%s"!',
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [],
        # Exclude the sibling-helper assertion strings so the inlined-parent match
        # (Linux, where all three helpers fold into CLoopTypeBase_LoadDependentServices)
        # collapses to zero and this skill soft-skips in favour of the -inlined fallback.
        "exclude_strings": [
            'Service "%s" is specified to both run before and after service "%s"!',
            'Loop "%s" contains a circular dependency with service "%s"!',
        ],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopTypeBase_AddDependentServices",
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
