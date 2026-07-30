#!/usr/bin/env python3
"""Generate the OnServerVoiceData IsPlayingDemo call-site patch YAML on Windows."""

import os
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from ida_analyze_util import parse_mcp_result, write_patch_yaml


SOURCE_VFUNC_NAME = "IVEngineClient2_IsPlayingDemo"
SOURCE_VTABLE_NAME = "IVEngineClient2"
TARGET_PATCH_NAME = "OnServerVoiceData_IsPlayingDemo_Callee"
PATCH_SIG_DISP = 0
VTABLE_ENTRY_SIZE = 8
FIND_BYTES_LIMIT = 2

_SIGNATURE_TOKEN_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}|\?\?)$")


def _debug(enabled, message):
    if enabled:
        print(f"    Preprocess: {message}")


def _read_yaml(path, debug=False):
    if yaml is None:
        _debug(debug, "PyYAML is required")
        return None
    try:
        with open(path, "r", encoding="utf-8") as yaml_file:
            data = yaml.safe_load(yaml_file)
    except Exception as exc:
        _debug(debug, f"failed to read {os.path.basename(path)}: {exc}")
        return None
    if not isinstance(data, dict):
        _debug(debug, f"invalid YAML payload in {os.path.basename(path)}")
        return None
    return data


def _parse_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return None


def _normalize_signature(value):
    if not isinstance(value, str):
        return None
    tokens = value.split()
    if not tokens or any(_SIGNATURE_TOKEN_RE.fullmatch(token) is None for token in tokens):
        return None
    return " ".join(token.upper() for token in tokens)


def _expected_rax_vcall_prefix(vfunc_offset):
    """Return the concrete bytes for ``call qword ptr [rax+vfunc_offset]``."""
    if vfunc_offset < 0:
        return None
    if vfunc_offset == 0:
        return ["FF", "10"]
    if vfunc_offset <= 0x7F:
        return ["FF", "50", f"{vfunc_offset:02X}"]
    if vfunc_offset > 0x7FFF_FFFF:
        return None
    return ["FF", "90", *(f"{byte:02X}" for byte in vfunc_offset.to_bytes(4, "little"))]


def _read_source_signature(source_path, debug=False):
    data = _read_yaml(source_path, debug=debug)
    if data is None:
        return None

    if data.get("func_name") != SOURCE_VFUNC_NAME:
        _debug(debug, f"unexpected func_name in {os.path.basename(source_path)}")
        return None
    if data.get("vtable_name") != SOURCE_VTABLE_NAME:
        _debug(debug, f"unexpected vtable_name in {os.path.basename(source_path)}")
        return None

    vfunc_offset = _parse_int(data.get("vfunc_offset"))
    vfunc_index = _parse_int(data.get("vfunc_index"))
    if vfunc_offset is None or vfunc_index is None:
        _debug(debug, f"missing or invalid vfunc slot metadata in {os.path.basename(source_path)}")
        return None
    if vfunc_offset % VTABLE_ENTRY_SIZE != 0 or vfunc_index != vfunc_offset // VTABLE_ENTRY_SIZE:
        _debug(debug, f"inconsistent vfunc_offset/vfunc_index in {os.path.basename(source_path)}")
        return None

    signature = _normalize_signature(data.get("vfunc_sig"))
    if signature is None:
        _debug(debug, f"missing or invalid vfunc_sig in {os.path.basename(source_path)}")
        return None

    expected_prefix = _expected_rax_vcall_prefix(vfunc_offset)
    signature_tokens = signature.split()
    if expected_prefix is None or signature_tokens[: len(expected_prefix)] != expected_prefix:
        _debug(
            debug,
            f"vfunc_sig does not start with call [rax+0x{vfunc_offset:X}] in {os.path.basename(source_path)}",
        )
        return None
    return signature


def _match_output(expected_outputs, platform):
    expected_filename = f"{TARGET_PATCH_NAME}.{platform}.yaml"
    matches = [output_path for output_path in expected_outputs if Path(output_path).name == expected_filename]
    return matches[0] if len(matches) == 1 else None


async def _find_unique_signature_match(session, signature, debug=False):
    try:
        result = await session.call_tool(
            name="find_bytes",
            arguments={"patterns": [signature], "limit": FIND_BYTES_LIMIT},
        )
        data = parse_mcp_result(result)
    except Exception as exc:
        _debug(debug, f"find_bytes failed: {exc}")
        return None

    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        _debug(debug, "find_bytes returned an invalid response")
        return None

    matches = data[0].get("matches", [])
    fallback_count = len(matches) if isinstance(matches, list) else None
    match_count = _parse_int(data[0].get("n", fallback_count))
    if not isinstance(matches, list) or match_count != 1 or len(matches) != 1:
        _debug(debug, f"vfunc_sig matched {match_count} location(s), expected exactly 1")
        return None

    try:
        return int(matches[0], 0) if isinstance(matches[0], str) else int(matches[0])
    except (TypeError, ValueError):
        _debug(debug, "find_bytes returned an invalid match address")
        return None


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
    """Convert IVEngineClient2_IsPlayingDemo vfunc metadata into a call-site patch YAML."""
    _ = skill_name, old_yaml_map

    if platform != "windows":
        _debug(debug, "OnServerVoiceData_IsPlayingDemo_Callee is Windows-only")
        return False

    output_path = _match_output(expected_outputs, platform)
    if output_path is None:
        _debug(debug, f"expected exactly one {TARGET_PATCH_NAME}.{platform}.yaml output")
        return False

    source_path = os.path.join(new_binary_dir, f"{SOURCE_VFUNC_NAME}.{platform}.yaml")
    signature = _read_source_signature(source_path, debug=debug)
    if signature is None:
        return False

    patch_va = await _find_unique_signature_match(session, signature, debug=debug)
    image_base_int = _parse_int(image_base)
    if patch_va is None or image_base_int is None or patch_va < image_base_int:
        _debug(debug, "invalid patch match or image base")
        return False

    payload = {
        "patch_name": TARGET_PATCH_NAME,
        "patch_va": hex(patch_va),
        "patch_rva": hex(patch_va - image_base_int),
        "patch_sig": signature,
        "patch_sig_disp": PATCH_SIG_DISP,
    }
    try:
        write_patch_yaml(output_path, payload)
    except Exception as exc:
        _debug(debug, f"failed to write patch YAML: {exc}")
        return False

    _debug(debug, f"generated {TARGET_PATCH_NAME}.{platform}.yaml from {os.path.basename(source_path)}")
    return True
