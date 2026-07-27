#!/usr/bin/env python3
"""Preprocess script for find-CLoopModeFactory_CLoopModeGame_vtable skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_CLASS_NAMES = [
    "CLoopModeFactory_CLoopModeGame",
]
CANONICAL_VTABLE_SYMBOLS_BY_PLATFORM = {
    "windows": {"CLoopModeFactory_CLoopModeGame": "CLoopModeFactory_CLoopModeGame_vtable"},
    "linux": {"CLoopModeFactory_CLoopModeGame": "_ZTV16CLoopModeFactoryI13CLoopModeGameE + 0x10"},
}

MANGLED_CLASS_NAMES = {
    "CLoopModeFactory_CLoopModeGame": [
        "??_R4?$CLoopModeFactory@VCLoopModeGame@@@@6B@",
        "_ZTV16CLoopModeFactoryI13CLoopModeGameE",
    ],
}

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopModeFactory_CLoopModeGame",
        [
            "vtable_class",
            "vtable_symbol",
            "vtable_va",
            "vtable_rva",
            "vtable_size",
            "vtable_numvfunc",
            "vtable_entries",
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
    """Generate CLoopModeFactory_CLoopModeGame vtable YAML by class-name lookup via MCP."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        vtable_class_names=TARGET_CLASS_NAMES,
        mangled_class_names=MANGLED_CLASS_NAMES,
        platform=platform,
        image_base=image_base,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        canonical_vtable_symbols=CANONICAL_VTABLE_SYMBOLS_BY_PLATFORM.get(platform),
        debug=debug,
    )
