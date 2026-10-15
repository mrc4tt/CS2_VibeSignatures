#!/usr/bin/env python3
"""Preprocess script for find-CLoggingSystem_LogDirect skill.

CLoggingSystem::LogDirect is tier0's internal logging funnel and the function
CleanerCS2 hooks: (CLoggingSystem*, int channel, int severity,
const LoggingRareOptions_t*, const char* fmt, va_list* args). It is not exported.
Msg/Warning/ConMsg/DevMsg/SeriousWarning format into a buffer and call it with
args = NULL; every LoggingSystem_Log overload and the exported
LoggingSystem_LogDirect wrapper call it too.

String-anchored rather than relocation-only, because the symbol is fork-owned and
has no baseline in any earlier gamever. The anchor is the message it prints before
honouring an LR_ABORT response, which no other function in tier0 references:

    Exiting due to logging LR_ABORT request.

Confirmed on 14191 (rule 12 - checked against the callers, not the match alone):
  linux   0x20ca60     - LoggingSystem_LogDirect (export) tail-calls it with
                         (&g_LoggingSystem, ch, sev, 0, msg, 0); Msg calls it with
                         LOG_GENERAL, 2
  windows 0x180127e10  - same, from LoggingSystem_LogDirect at 0x18012a5c0

`preprocess_common_skill` still tries relocation first, so from the gamever after
the first one this costs nothing; the xref is the fallback for the first run and
for any run whose baseline sig has gone stale.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoggingSystem_LogDirect",
]

FUNC_XREFS = [
    {
        "func_name": "CLoggingSystem_LogDirect",
        "xref_strings": [
            "Exiting due to logging LR_ABORT request.",
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
        "CLoggingSystem_LogDirect",
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
