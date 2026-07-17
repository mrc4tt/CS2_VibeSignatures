#!/usr/bin/env python3
"""Preprocess script for find-CEntitySystem_Init-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "INetworkMessages_SetNetworkSerializationContextData",
    "IFlattenedSerializers_CreateFieldChangedEventQueue",
]

TARGET_FUNCTION_NAMES_LINUX = [
    "CEntitySystem_ProcessEntityRegistration",
]

TARGET_STRUCT_MEMBER_NAMES = [
    "CEntitySystem_m_sEntSystemName",
    "CEntitySystem_m_eNetworkSerializationMode",
    "CEntitySystem_m_Symbols",
    "CEntitySystem_m_pNetworkFieldChangedEventQueue",
    "CEntitySystem_m_pNetworkFieldScratchData",
    "CEntitySystem_m_pFieldChangeLimitSpew",
    "CEntitySystem_m_ComponentUnserializerInfoAllocator",
]

TARGET_STRUCT_MEMBER_NAMES_WINDOWS = [
    "CEntitySystem_m_EntityMaterialAttributes",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "INetworkMessages_SetNetworkSerializationContextData",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
    },
    {
        "symbol_name": "IFlattenedSerializers_CreateFieldChangedEventQueue",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
    },
    {
        "symbol_name": "CEntitySystem_m_sEntSystemName",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CEntitySystem_m_eNetworkSerializationMode",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CEntitySystem_m_Symbols",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CEntitySystem_m_pNetworkFieldChangedEventQueue",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CEntitySystem_m_pNetworkFieldScratchData",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CEntitySystem_m_pFieldChangeLimitSpew",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CEntitySystem_m_ComponentUnserializerInfoAllocator",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("INetworkMessages_SetNetworkSerializationContextData", "INetworkMessages"),
    ("IFlattenedSerializers_CreateFieldChangedEventQueue", "IFlattenedSerializers"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "INetworkMessages_SetNetworkSerializationContextData",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "IFlattenedSerializers_CreateFieldChangedEventQueue",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "CEntitySystem_m_sEntSystemName",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
        ],
    ),
    (
        "CEntitySystem_m_eNetworkSerializationMode",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
        ],
    ),
    (
        "CEntitySystem_m_Symbols",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
        ],
    ),
    (
        "CEntitySystem_m_pNetworkFieldChangedEventQueue",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
            # "offset_sig_max_match:2",
            "offset_sig_allow_across_function_boundary:true",
        ],
    ),
    (
        "CEntitySystem_m_pNetworkFieldScratchData",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
            # "offset_sig_max_match:2",
            "offset_sig_allow_across_function_boundary:true",
        ],
    ),
    (
        "CEntitySystem_m_pFieldChangeLimitSpew",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
            # "offset_sig_max_match:2",
            "offset_sig_allow_across_function_boundary:true",
        ],
    ),
    (
        "CEntitySystem_m_ComponentUnserializerInfoAllocator",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
        ],
    ),
]

LLM_DECOMPILE_LINUX = [
    {
        "symbol_name": "CEntitySystem_ProcessEntityRegistration",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
    },
]

LLM_DECOMPILE_WINDOWS = [
    {
        "symbol_name": "CEntitySystem_m_EntityMaterialAttributes",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
]

GENERATE_YAML_DESIRED_FIELDS_WINDOWS = [
    (
        "CEntitySystem_m_EntityMaterialAttributes",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
            "offset_sig",
            "offset_sig_disp",
        ],
    ),
]

GENERATE_YAML_DESIRED_FIELDS_LINUX = [
    (
        "CEntitySystem_ProcessEntityRegistration",
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
    llm_config=None,
    debug=False,
):
    """Locate vfuncs and struct member offsets from CEntitySystem_Init via LLM decompile."""
    func_names = list(TARGET_FUNCTION_NAMES)
    struct_member_names = list(TARGET_STRUCT_MEMBER_NAMES)
    llm_decompile = list(LLM_DECOMPILE)
    generate_yaml_desired_fields = list(GENERATE_YAML_DESIRED_FIELDS)

    if platform == "linux":
        func_names += TARGET_FUNCTION_NAMES_LINUX
        generate_yaml_desired_fields += GENERATE_YAML_DESIRED_FIELDS_LINUX
        llm_decompile += LLM_DECOMPILE_LINUX

    if platform == "windows":
        struct_member_names += TARGET_STRUCT_MEMBER_NAMES_WINDOWS
        generate_yaml_desired_fields += GENERATE_YAML_DESIRED_FIELDS_WINDOWS
        llm_decompile += LLM_DECOMPILE_WINDOWS

    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=func_names,
        struct_member_names=struct_member_names,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=llm_decompile,
        llm_config=llm_config,
        generate_yaml_desired_fields=generate_yaml_desired_fields,
        debug=debug,
    )
