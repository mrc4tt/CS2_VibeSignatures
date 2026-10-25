#!/usr/bin/env python3
"""Preprocess ConnectClient's GetFreeClient call and CheckPassword vcall.

GetFreeClient is written straight from the live anchor (the free-slot allocator's
call on the server-full path, _connect_client_anchor), with no LLM: the anchor already
names the function, and an LLM asked for the "first" acquisition chose linux's
reconnect lookup instead. CheckPassword still relocates by vfunc_sig, then LLM.
"""

import os

from ida_analyze_util import preprocess_common_skill, write_func_yaml
from ida_preprocessor_scripts._connect_client_anchor import SYMBOL, load_anchor
from ida_preprocessor_scripts._direct_branch_target_common import DirectBranchTargetLocator


TARGET_FUNCTION_NAMES = [
    "CNetworkGameServerBase_CheckPassword",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CNetworkGameServerBase_CheckPassword",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CNetworkGameServerBase_ConnectClient.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CNetworkGameServerBase_ConnectClient.{platform}.yaml": "required",
        },
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CNetworkGameServerBase_CheckPassword", "CNetworkGameServerBase"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # No func_sig: GetFreeClient's head bytes are not unique in the binary.
    # The ConnectClient anchor locates it each time.
    (
        "CNetworkGameServer_GetFreeClient",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
        ],
    ),
    # vfunc_sig is MANDATORY for Pattern C (LLM_DECOMPILE vfunc).
    (
        "CNetworkGameServerBase_CheckPassword",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
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
    """Locate GetFreeClient from the live anchor, CheckPassword via vfunc_sig or LLM."""
    try:
        anchor = await load_anchor(session, new_binary_dir, platform)
    except Exception as exc:
        if debug:
            print(f"    Preprocess: GetFreeClient semantic anchor unavailable: {exc}")
        return False
    if debug:
        print(f"    Preprocess: GetFreeClient verified anchor {hex(anchor['insn_va'])} -> {hex(anchor['target_va'])}")
    name = f"{SYMBOL}.{platform}.yaml"
    free_client = [path for path in expected_outputs if os.path.basename(path) == name]
    if len(free_client) != 1:
        return False
    info = await DirectBranchTargetLocator(session=session, debug=debug).query_func_info(anchor["target_va"])
    if not info:
        if debug:
            print(f"    Preprocess: {hex(anchor['target_va'])} is not a function head")
        return False
    func_va = int(info["func_va"], 16)
    fields = dict(GENERATE_YAML_DESIRED_FIELDS)[SYMBOL]
    available = {"func_name": SYMBOL, "func_va": hex(func_va), "func_rva": hex(func_va - image_base),
                 "func_size": info["func_size"]}
    write_func_yaml(free_client[0], {field: available[field] for field in fields})
    return await preprocess_common_skill(
        session=session,
        expected_outputs=[path for path in expected_outputs if path not in free_client],
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=[entry for entry in GENERATE_YAML_DESIRED_FIELDS if entry[0] != SYMBOL],
        debug=debug,
    )
