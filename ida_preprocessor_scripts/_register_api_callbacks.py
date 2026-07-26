#!/usr/bin/env python3
"""Shared helpers for extracting named API callbacks from a registrar function."""

import json
import os

try:
    import yaml
except ImportError:
    yaml = None

from ida_analyze_util import (
    _build_ida_exact_string_index_py_lines,
    _normalize_generate_yaml_desired_fields,
    parse_mcp_result,
    preprocess_gen_func_sig_via_mcp,
    write_func_yaml,
)


_SUPPORTED_FIELDS = {
    "func_name",
    "func_sig",
    "func_sig_allow_across_function_boundary",
    "func_va",
    "func_rva",
    "func_size",
}


_REGISTER_API_CALLBACKS_PY_EVAL_TEMPLATE = r"""
def _run():
    import json
    import traceback
    try:
        import idaapi, ida_bytes, idautils, ida_nalt, idc
        params = json.loads(__PARAMS_JSON__)
        platform, source_func_va, api_names = params['platform'], params['source_func_va'], params['api_names']
        search_window_after_xref = int(params['search_window_after_xref'])
        search_window_before_call = int(params['search_window_before_call'])
        target_texts = api_names
__EXACT_STRING_INDEX_LINES__
        if platform != 'windows':
            return {'ok': False, 'error': 'only the Windows x64 ABI is supported'}
        arg_registers = ('rcx', 'rdx', 'r8', 'r9')
        direct_value_types = tuple(int(value) for value in (idaapi.o_imm, idaapi.o_mem, idaapi.o_near, idaapi.o_far, idaapi.o_displ))
        def _canonical_reg(name):
            raw = (name or '').lower().strip()
            aliases = dict(eax='rax', ax='rax', al='rax', ebx='rbx', bx='rbx', bl='rbx', ecx='rcx', cx='rcx', cl='rcx',
                           edx='rdx', dx='rdx', dl='rdx', esi='rsi', si='rsi', sil='rsi', edi='rdi', di='rdi', dil='rdi',
                           ebp='rbp', bp='rbp', bpl='rbp', esp='rsp', sp='rsp', spl='rsp')
            if raw in aliases:
                return aliases[raw]
            if raw.startswith('r') and raw.endswith(('d', 'w', 'b')) and raw[1:-1].isdigit():
                return raw[:-1]
            return raw
        def _operand_type(ea, index):
            try: return int(idc.get_operand_type(ea, index))
            except Exception: return -1
        def _prev_heads(start_ea, min_ea):
            cur = idc.prev_head(start_ea, min_ea)
            while cur != idaapi.BADADDR and cur >= min_ea:
                yield cur
                next_cur = idc.prev_head(cur, min_ea)
                if next_cur == cur:
                    break
                cur = next_cur
        def _recover_register_value(before_ea, reg_name, depth=0, stop_at_call=True):
            if depth > 5: return None
            wanted = _canonical_reg(reg_name)
            if not wanted: return None
            min_ea = max(source_func.start_ea, before_ea - search_window_before_call)
            for cur in _prev_heads(before_ea, min_ea):
                mnem = (idc.print_insn_mnem(cur) or '').lower()
                if stop_at_call and mnem in ('call', 'jmp'): break
                op0 = _canonical_reg(idc.print_operand(cur, 0) or '')
                if op0 != wanted: continue
                if mnem in ('mov', 'lea'):
                    op1_type = _operand_type(cur, 1)
                    if op1_type == int(idaapi.o_reg):
                        return _recover_register_value(cur, idc.print_operand(cur, 1), depth + 1, stop_at_call)
                    if op1_type in direct_value_types:
                        value = idc.get_operand_value(cur, 1)
                        return None if value in (None, idaapi.BADADDR) else int(value)
                    return None
                if mnem == 'xor' and _canonical_reg(idc.print_operand(cur, 1) or '') == wanted:
                    return 0
                return None
            return None
        def _stack_slot_key(ea, index):
            if _operand_type(ea, index) != int(idaapi.o_displ):
                return None
            text = (idc.print_operand(ea, index) or '').lower()
            base = 'sp' if 'rsp' in text or 'esp' in text else 'bp' if 'rbp' in text or 'ebp' in text else None
            if base is None:
                return None
            try: displacement = int(idc.get_operand_value(ea, index))
            except Exception: return None
            return base + ':' + str(displacement)
        def _recover_stack_slot(before_ea, reg_name, depth=0):
            if depth > 5: return None
            wanted = _canonical_reg(reg_name)
            min_ea = max(source_func.start_ea, before_ea - search_window_before_call)
            for cur in _prev_heads(before_ea, min_ea):
                mnem = (idc.print_insn_mnem(cur) or '').lower()
                if mnem in ('call', 'jmp'): break
                if _canonical_reg(idc.print_operand(cur, 0) or '') != wanted: continue
                if mnem == 'lea':
                    return _stack_slot_key(cur, 1)
                if mnem == 'mov' and _operand_type(cur, 1) == int(idaapi.o_reg):
                    return _recover_stack_slot(cur, idc.print_operand(cur, 1), depth + 1)
                return None
            return None
        def _recover_slot_value(before_ea, slot_key):
            min_ea = max(source_func.start_ea, before_ea - search_window_before_call)
            for cur in _prev_heads(before_ea, min_ea):
                mnem = (idc.print_insn_mnem(cur) or '').lower()
                if mnem not in ('mov', 'lea') or _stack_slot_key(cur, 0) != slot_key:
                    continue
                op1_type = _operand_type(cur, 1)
                if op1_type == int(idaapi.o_reg):
                    return _recover_register_value(cur, idc.print_operand(cur, 1), stop_at_call=True)
                if op1_type in direct_value_types:
                    value = idc.get_operand_value(cur, 1)
                    return None if value in (None, idaapi.BADADDR) else int(value)
                return None
            return None
        def _is_function_entry(value):
            if value in (None, 0, idaapi.BADADDR):
                return False
            try: func = idaapi.get_func(int(value)); return bool(func and int(func.start_ea) == int(value))
            except Exception: return False
        def _candidate_at_call(call_ea, string_ea):
            string_args = [reg for reg in arg_registers
                           if _recover_register_value(call_ea, reg, stop_at_call=True) == string_ea]
            if len(string_args) != 1:
                return None
            string_arg = string_args[0]
            callback_candidates = []
            for callback_arg in arg_registers:
                if callback_arg == string_arg: continue
                slot_key = _recover_stack_slot(call_ea, callback_arg)
                if slot_key is None: continue
                callback_va = _recover_slot_value(call_ea, slot_key)
                if _is_function_entry(callback_va):
                    callback_candidates.append((callback_arg, slot_key, callback_va))
            if len(callback_candidates) != 1:
                return None
            callback_arg, slot_key, callback_va = callback_candidates[0]
            return dict(callback_va=hex(callback_va), call_ea=hex(call_ea),
                        string_arg=string_arg, callback_arg=callback_arg, stack_slot=slot_key)
        source_func_va = int(str(source_func_va), 0)
        source_func = idaapi.get_func(source_func_va)
        if source_func is None or int(source_func.start_ea) != source_func_va:
            return {'ok': False, 'error': 'source function not found'}
        entries = []
        errors = []
        for api_name in api_names:
            candidates = {}
            for string_ea in string_hits.get(api_name, []):
                for xref in idautils.XrefsTo(string_ea, 0):
                    xref_ea = int(xref.frm)
                    if not source_func.start_ea <= xref_ea < source_func.end_ea: continue
                    if not idc.is_code(ida_bytes.get_full_flags(xref_ea)): continue
                    max_ea = min(source_func.end_ea - 1, xref_ea + search_window_after_xref)
                    cur = xref_ea
                    while cur != idaapi.BADADDR and cur <= max_ea:
                        if (idc.print_insn_mnem(cur) or '').lower() in ('call', 'jmp'):
                            candidate = _candidate_at_call(cur, int(string_ea))
                            if candidate is not None:
                                key = (candidate['call_ea'], candidate['callback_va'])
                                candidates[key] = candidate
                        next_cur = idc.next_head(cur, max_ea + 1)
                        if next_cur in (idaapi.BADADDR, cur): break
                        cur = next_cur
            if len(candidates) != 1:
                errors.append({'api_name': api_name, 'candidate_count': len(candidates)})
                continue
            entry = next(iter(candidates.values()))
            entry['api_name'] = api_name
            entries.append(entry)
        if errors:
            return dict(ok=False, error='API callback resolution failed', errors=errors, entries=entries)
        return dict(ok=True, entries=entries)
    except Exception:
        return {'ok': False, 'traceback': traceback.format_exc()}
try:
    import json
    result = json.dumps(_run())
except Exception:
    import json, traceback
    result = json.dumps(dict(ok=False, traceback=traceback.format_exc()))
"""


def _debug(enabled, message):
    if enabled:
        print(f"    Preprocess: {message}")


def _parse_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value.strip(), 0)
    return int(value)


def _read_yaml(path):
    if yaml is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception:
        return None


def _read_source_func_va(new_binary_dir, source_yaml_stem, platform, debug=False):
    source_path = os.path.join(new_binary_dir, f"{source_yaml_stem}.{platform}.yaml")
    source_yaml = _read_yaml(source_path)
    value = source_yaml.get("func_va") if isinstance(source_yaml, dict) else None
    try:
        return hex(_parse_int(value))
    except Exception:
        _debug(debug, f"invalid source func_va in {source_path}")
        return None


def _build_register_api_callbacks_py_eval(
    platform,
    source_func_va,
    api_names,
    search_window_after_xref,
    search_window_before_call,
):
    params = json.dumps(
        {
            "platform": platform,
            "source_func_va": source_func_va,
            "api_names": list(api_names),
            "search_window_after_xref": search_window_after_xref,
            "search_window_before_call": search_window_before_call,
        }
    )
    exact_lines = "\n".join(
        "        " + line
        for line in _build_ida_exact_string_index_py_lines(
            target_texts_var_name="target_texts",
            result_var_name="string_hits",
        )
    )
    return (
        _REGISTER_API_CALLBACKS_PY_EVAL_TEMPLATE.replace("__PARAMS_JSON__", repr(params))
        .replace("__EXACT_STRING_INDEX_LINES__", exact_lines)
        .lstrip()
    )


async def _call_py_eval_json(session, code, debug=False, error_label="py_eval"):
    try:
        result = await session.call_tool(name="py_eval", arguments={"code": code})
        result_data = parse_mcp_result(result)
    except Exception:
        _debug(debug, f"{error_label} error")
        return None
    raw = result_data.get("result", "") if isinstance(result_data, dict) else None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        _debug(debug, f"invalid JSON result from {error_label}")
        return None


async def _collect_register_api_entries(
    session,
    platform,
    source_func_va,
    api_names,
    search_window_after_xref,
    search_window_before_call,
    debug=False,
):
    code = _build_register_api_callbacks_py_eval(
        platform=platform,
        source_func_va=source_func_va,
        api_names=api_names,
        search_window_after_xref=search_window_after_xref,
        search_window_before_call=search_window_before_call,
    )
    parsed = await _call_py_eval_json(
        session,
        code,
        debug=debug,
        error_label="py_eval collecting register API callbacks",
    )
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        if isinstance(parsed, dict):
            _debug(debug, str(parsed.get("error") or parsed.get("traceback") or parsed))
        return None
    entries = parsed.get("entries")
    if not isinstance(entries, list):
        return None
    expected_names = list(api_names)
    found_names = [entry.get("api_name") for entry in entries if isinstance(entry, dict)]
    if len(entries) != len(expected_names) or found_names != expected_names:
        _debug(debug, "register API callback result count/order mismatch")
        return None
    if any(not entry.get("callback_va") for entry in entries):
        return None
    return entries


async def _query_func_info(session, func_va, debug=False):
    try:
        func_va_int = _parse_int(func_va)
    except Exception:
        return None
    code = (
        "import idaapi, json\n"
        f"target_ea = {func_va_int}\n"
        "func = idaapi.get_func(target_ea)\n"
        "if func and func.start_ea == target_ea:\n"
        "    result = json.dumps({'func_va': hex(func.start_ea), "
        "'func_size': hex(func.end_ea - func.start_ea)})\n"
        "else:\n"
        "    result = json.dumps(None)\n"
    )
    parsed = await _call_py_eval_json(session, code, debug=debug, error_label="querying API callback")
    return parsed if isinstance(parsed, dict) else None


async def _rename_func_best_effort(session, func_va, func_name, debug=False):
    try:
        await session.call_tool(
            name="rename",
            arguments={"batch": {"func": {"addr": str(func_va), "name": str(func_name)}}},
        )
    except Exception:
        _debug(debug, f"failed to rename {func_name} (non-fatal)")


def _normalize_specs(target_specs, debug=False):
    if not isinstance(target_specs, list) or not target_specs:
        return None
    specs = []
    api_names = set()
    target_names = set()
    for item in target_specs:
        api_name = item.get("api_name") if isinstance(item, dict) else None
        target_name = item.get("target_name") if isinstance(item, dict) else None
        if not api_name or not target_name or api_name in api_names or target_name in target_names:
            _debug(debug, f"invalid or duplicate target spec: {item}")
            return None
        specs.append({"api_name": str(api_name), "target_name": str(target_name)})
        api_names.add(api_name)
        target_names.add(target_name)
    return specs


def _normalize_desired_fields(generate_yaml_desired_fields, debug=False):
    desired_map = _normalize_generate_yaml_desired_fields(generate_yaml_desired_fields, debug=debug)
    if desired_map is None:
        return None
    for target_name, config in desired_map.items():
        unsupported = set(config["desired_output_fields"]) - _SUPPORTED_FIELDS
        if unsupported:
            _debug(debug, f"unsupported fields for {target_name}: {sorted(unsupported)}")
            return None
    return desired_map


def _match_output_paths(expected_outputs, specs, platform, debug=False):
    output_paths = {}
    for spec in specs:
        filename = f"{spec['target_name']}.{platform}.yaml"
        matches = [path for path in expected_outputs if os.path.basename(path) == filename]
        if len(matches) != 1:
            _debug(debug, f"expected exactly one output named {filename}")
            return None
        output_paths[spec["target_name"]] = matches[0]
    return output_paths


async def _build_payload(session, spec, entry, config, image_base, debug=False):
    func_info = await _query_func_info(session, entry["callback_va"], debug=debug)
    if not isinstance(func_info, dict):
        return None
    requested_fields = config["desired_output_fields"]
    options = config["generation_options"]
    func_va = str(func_info["func_va"])
    available = {
        "func_name": spec["target_name"],
        "func_va": func_va,
        "func_rva": hex(_parse_int(func_va) - image_base),
        "func_size": str(func_info["func_size"]),
    }
    if "func_sig" in requested_fields:
        sig_info = await preprocess_gen_func_sig_via_mcp(
            session=session,
            func_va=func_va,
            image_base=image_base,
            allow_across_function_boundary=bool(options.get("func_sig_allow_across_function_boundary")),
            debug=debug,
        )
        if not isinstance(sig_info, dict) or not sig_info.get("func_sig"):
            return None
        available.update({key: sig_info[key] for key in ("func_sig", "func_rva", "func_size") if key in sig_info})
    if options.get("func_sig_allow_across_function_boundary"):
        available["func_sig_allow_across_function_boundary"] = True
    try:
        return {field: available[field] for field in requested_fields}
    except KeyError:
        return None


async def preprocess_register_api_callbacks_skill(
    session,
    expected_outputs,
    new_binary_dir,
    platform,
    image_base,
    source_yaml_stem,
    target_specs,
    generate_yaml_desired_fields,
    search_window_after_xref=96,
    search_window_before_call=128,
    debug=False,
):
    if yaml is None or platform != "windows":
        return False
    try:
        image_base_int = _parse_int(image_base)
    except Exception:
        return False
    specs = _normalize_specs(target_specs, debug=debug)
    desired_map = _normalize_desired_fields(generate_yaml_desired_fields, debug=debug)
    if not specs or desired_map is None or set(desired_map) != {spec["target_name"] for spec in specs}:
        return False
    output_paths = _match_output_paths(expected_outputs, specs, platform, debug=debug)
    source_func_va = _read_source_func_va(new_binary_dir, source_yaml_stem, platform, debug=debug)
    if output_paths is None or source_func_va is None:
        return False
    entries = await _collect_register_api_entries(
        session=session,
        platform=platform,
        source_func_va=source_func_va,
        api_names=[spec["api_name"] for spec in specs],
        search_window_after_xref=search_window_after_xref,
        search_window_before_call=search_window_before_call,
        debug=debug,
    )
    if not isinstance(entries, list):
        return False
    entry_map = {entry["api_name"]: entry for entry in entries}
    if len(entry_map) != len(specs):
        return False
    pending = []
    for spec in specs:
        entry = entry_map.get(spec["api_name"])
        config = desired_map.get(spec["target_name"])
        if entry is None or config is None:
            return False
        payload = await _build_payload(session, spec, entry, config, image_base_int, debug=debug)
        if payload is None or set(payload) != set(config["desired_output_fields"]):
            return False
        pending.append((output_paths[spec["target_name"]], payload, entry["callback_va"]))
    for output_path, payload, _ in pending:
        write_func_yaml(output_path, payload)
    for _, payload, func_va in pending:
        await _rename_func_best_effort(
            session=session,
            func_va=func_va,
            func_name=payload["func_name"],
            debug=debug,
        )
    return True
