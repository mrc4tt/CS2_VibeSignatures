#!/usr/bin/env python3
"""Preprocess script for find-KickBotFromTeam skill.

KickBotFromTeam(int team) -> bool is a free function (no this) that only
CCSBotManager::MaintainBotQuota calls (6 sites linux, 5 windows on 14196). It walks the player
slots for a controller with m_iTeamNum == team and FL_FAKECLIENT, prefers a missing/dead pawn,
and kicks it with IVEngineServer2::KickClient(slot, nullptr, NETWORK_DISCONNECT_KICKED=39)
through the engine vtable (+0x308, slot 97). 14196: linux 0xC09C40, windows 0x1802E7800.
MatchZy hooks it so the quota never kicks SourceTV (team 0, FL_FAKECLIENT, no pawn).

Anchor: inside MaintainBotQuota, the KickBotFromTeam(0) call is a direct call right after
`xor edi, edi` (linux) / `xor ecx, ecx` (windows). Other calls there take 0 too (the bot add
helper, the human counters), so a candidate must also be called at least 3 times from the
quota and must itself reach the engine vtable at +0x308 with the 39 immediate. Exactly one
callee passes on 14196 both platforms.
"""

import os

from ida_analyze_util import write_func_yaml
from ida_preprocessor_scripts._direct_branch_target_common import (
    _build_requested_payload,
    _call_py_eval_json,
    _debug,
    _normalize_requested_fields,
    _read_yaml,
    _rename_func_best_effort,
    _resolve_output_path,
)

SOURCE_FUNCTION_NAME = "CCSBotManager_MaintainBotQuota"

TARGET_FUNCTION_NAMES = [
    "KickBotFromTeam",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "KickBotFromTeam",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
        ],
    ),
]

MIN_CALLS_FROM_SOURCE = 3
ENGINE_KICKCLIENT_DISP = 0x308
NETWORK_DISCONNECT_KICKED = 39

_PY_EVAL = r"""
import idaapi, idautils, idc, ida_ua, json
src_ea = __SRC__
zero_reg = __ZERO_REG__
min_calls = __MIN_CALLS__
kick_disp = __KICK_DISP__
kick_reason = __KICK_REASON__

def _direct_callee(ea):
    if idc.print_insn_mnem(ea) != 'call':
        return None
    insn = ida_ua.insn_t()
    if not ida_ua.decode_insn(insn, ea):
        return None
    if insn.ops[0].type not in (idaapi.o_near, idaapi.o_far):
        return None
    f = idaapi.get_func(insn.ops[0].addr)
    if f is None or f.start_ea != insn.ops[0].addr:
        return None
    return int(f.start_ea)

def _reaches_kickclient(fea):
    f = idaapi.get_func(fea)
    if f is None:
        return False
    has_disp = False
    has_reason = False
    for h in idautils.Heads(f.start_ea, f.end_ea):
        insn = ida_ua.insn_t()
        if not ida_ua.decode_insn(insn, h):
            continue
        mnem = idc.print_insn_mnem(h)
        for op in insn.ops:
            if op.type == idaapi.o_void:
                break
            if op.type in (idaapi.o_displ, idaapi.o_phrase) and op.addr == kick_disp and mnem in ('mov', 'call'):
                has_disp = True
            if op.type == idaapi.o_imm and op.value == kick_reason and mnem == 'mov':
                has_reason = True
    return has_disp and has_reason

def _main():
    src = idaapi.get_func(src_ea)
    if src is None:
        return None
    counts = {}
    anchored = set()
    for h in idautils.Heads(src.start_ea, src.end_ea):
        callee = _direct_callee(h)
        if callee is None:
            continue
        counts[callee] = counts.get(callee, 0) + 1
        prev = idc.prev_head(h, src.start_ea)
        if prev != idaapi.BADADDR and idc.print_insn_mnem(prev) == 'xor' \
                and idc.print_operand(prev, 0) == zero_reg and idc.print_operand(prev, 1) == zero_reg:
            anchored.add(callee)
    cands = sorted(c for c in anchored if counts.get(c, 0) >= min_calls and _reaches_kickclient(c))
    f = idaapi.get_func(cands[0]) if len(cands) == 1 else None
    return {
        'candidates': [hex(c) for c in cands],
        'func_va': hex(f.start_ea) if f else None,
        'func_size': hex(f.end_ea - f.start_ea) if f else None,
    }
globals().update(locals())
result = json.dumps(_main())
"""


def _build_py_eval(source_func_va, platform):
    zero_reg = "ecx" if platform == "windows" else "edi"
    return (
        _PY_EVAL.replace("__SRC__", str(int(str(source_func_va), 0)))
        .replace("__ZERO_REG__", repr(zero_reg))
        .replace("__MIN_CALLS__", str(MIN_CALLS_FROM_SOURCE))
        .replace("__KICK_DISP__", str(ENGINE_KICKCLIENT_DISP))
        .replace("__KICK_REASON__", str(NETWORK_DISCONNECT_KICKED))
    )


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
    _ = skill_name, old_yaml_map
    target_name = TARGET_FUNCTION_NAMES[0]

    requested_fields = _normalize_requested_fields(GENERATE_YAML_DESIRED_FIELDS, target_name, debug=debug)
    if requested_fields is None:
        return False
    output_path = _resolve_output_path(expected_outputs, target_name, platform, debug=debug)
    if output_path is None:
        return False

    source_path = os.path.join(new_binary_dir, f"{SOURCE_FUNCTION_NAME}.{platform}.yaml")
    source_yaml = _read_yaml(source_path)
    if not isinstance(source_yaml, dict) or not source_yaml.get("func_va"):
        _debug(debug, f"failed to read source function YAML: {source_path}")
        return False

    parsed = await _call_py_eval_json(
        session=session,
        code=_build_py_eval(source_yaml["func_va"], platform),
        debug=debug,
        error_label="py_eval locating KickBotFromTeam",
    )
    if not isinstance(parsed, dict) or not parsed.get("func_va"):
        _debug(debug, f"KickBotFromTeam anchor not unique: {parsed}")
        return False

    payload = await _build_requested_payload(
        session=session,
        target_name=target_name,
        requested_fields=requested_fields,
        func_info={"func_va": parsed["func_va"], "func_size": parsed["func_size"]},
        image_base=image_base,
        debug=debug,
    )
    if payload is None:
        return False

    write_func_yaml(output_path, payload)
    await _rename_func_best_effort(session=session, func_va=parsed["func_va"], func_name=target_name, debug=debug)
    _debug(debug, f"written {os.path.basename(output_path)} from {SOURCE_FUNCTION_NAME} anchor {parsed['func_va']}")
    return True
