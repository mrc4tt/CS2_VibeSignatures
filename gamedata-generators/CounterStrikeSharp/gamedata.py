#!/usr/bin/env python3
"""
CounterStrikeSharp Gamedata Update Module

Updates gamedata.json for CounterStrikeSharp plugin framework.
"""

import json
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from gamedata_utils import convert_sig_to_css, normalize_func_name_colons_to_underscore

# Version 2: the context names the game build, whose binaries prove each vtable slot.
GENERATOR_API_VERSION = 2

# Module metadata
MODULE_NAME = "CounterStrikeSharp"
MODULE_ENABLED = True

# Relative path to gamedata file within the module output directory
GAMEDATA_PATH = "config/addons/counterstrikesharp/gamedata/gamedata.json"
OUTPUT_PATHS = (GAMEDATA_PATH,)

# Source-owned upstream baseline; provenance is recorded in templates/upstream.json.
DOWNLOAD_SOURCES = ()
STATIC_SOURCES = (("templates/gamedata.json", GAMEDATA_PATH),)


def _slot_prover(context, bindir="bin"):
    """prove(library, platform, class_name, index, func_va) -> verdict, or None without a build.

    The verdict is verify_plugin_gamedata.check_vtable_slot's, i.e. the slot read the way
    CounterStrikeSharp reads it (literal RTTI name, primary vtable, raw pointer). The
    artifact's index comes from validate_artifacts' verify_vfunc_slot, which accepts a hit in
    ANY of a class's vtables and resolves template names by their identifiers, so an index it
    passed can still be one the runtime cannot read or reads as another function. Shipping
    such a slot would fail the publish gate and stop every plugin's deploy over metadata CSS
    works fine without, so it is dropped here instead.
    """
    game_version = getattr(context, "game_version", None)
    if not game_version:
        return None
    import verify_plugin_gamedata as VPG

    binaries = VPG.Binaries(bindir, str(game_version))

    def prove(library, platform, class_name, index, func_va):
        module = VPG.LIBRARY_TO_MODULE.get(str(library or "server"), "server")
        block = {"class": class_name, f"{platform}_index": index}
        return VPG.check_vtable_slot(binaries, module, platform, block, func_va)

    return prove


def _func_va(record):
    value = record.get("func_va")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(str(value), 16) if value not in (None, "") else None
    except ValueError:
        return None


def _update_vtable_slot(entry, yaml_entry, platforms, prove=None):
    """Write the vtable slot of a virtual function next to its signature.

    CounterStrikeSharp falls back to the slot when the byte pattern stops resolving and logs
    when both resolve to different functions (src/core/gamedata_vtable.h there). Shape:

        "vtable": {"class": "CBaseTrigger", "linux_index": 151, "windows_index": 152}

    No "linux"/"windows" keys on purpose: every gamedata walker here (verify_plugin_gamedata,
    consumer_drift_audit, publish_site_data, the Pages parser) treats an object holding
    platform keys as an entry of its own.

    The block is rebuilt from this build's artifacts for every processed platform, so a stale
    index is dropped rather than carried forward; a platform outside `platforms` keeps its
    value unless the class changed. Returns True when the block was written.

    With `prove` (see _slot_prover), an index is written only when its binary confirms it;
    a missing binary ("no-binary") proves nothing either way and keeps it, which is also
    what the verifier does.
    """
    block = entry.get("vtable") if isinstance(entry.get("vtable"), dict) else {}
    classes = {}
    indices = {}
    for platform in platforms:
        record = yaml_entry.get(platform) or {}
        name, index = record.get("vtable_name"), record.get("vfunc_index")
        if isinstance(name, str) and name and isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            if prove is not None:
                verdict = prove(yaml_entry.get("library"), platform, name, index, _func_va(record))
                if verdict not in ("ok", "no-binary"):
                    print(f"  Warning: vtable slot {name}[{index}] on {platform} is {verdict} as "
                          f"CounterStrikeSharp reads it, dropping it")
                    continue
            classes[platform] = name
            indices[platform] = index

    if len(set(classes.values())) > 1:
        print(f"  Warning: vtable class differs between platforms ({classes}), dropping the vtable slot")
        classes, indices = {}, {}

    class_name = next(iter(classes.values()), None)
    if class_name is not None and block.get("class") != class_name:
        block = {"class": class_name}
    for platform in platforms:
        block.pop(f"{platform}_index", None)
        if platform in indices:
            block[f"{platform}_index"] = indices[platform]

    if not any(key.endswith("_index") for key in block) or not block.get("class"):
        entry.pop("vtable", None)
        return False

    entry["vtable"] = {"class": block["class"], **{k: block[k] for k in sorted(block) if k.endswith("_index")}}
    return bool(indices)


def update(yaml_data, func_lib_map, platforms, output_dir, alias_to_name_map, debug=False, *, context=None):
    """
    Update CounterStrikeSharp gamedata.json file.

    Args:
        yaml_data: Loaded YAML data
        func_lib_map: Function name to library mapping
        platforms: List of platforms to update
        output_dir: Path to this module's versioned output directory
        alias_to_name_map: Mapping from aliases to function names
        debug: If True, collect updated and skipped symbols info

    Returns:
        Tuple of (updated_count, skipped_count, updated_symbols, skipped_symbols)
    """
    gamedata_path = os.path.join(output_dir, GAMEDATA_PATH)

    if not os.path.exists(gamedata_path):
        print(f"  Warning: CounterStrikeSharp gamedata not found: {gamedata_path}")
        return 0, 0, [], []

    # Load existing gamedata
    with open(gamedata_path, "r", encoding="utf-8") as f:
        gamedata = json.load(f)

    prove = _slot_prover(context)

    updated_count = 0
    skipped_count = 0
    updated_symbols = []
    skipped_symbols = []

    for func_name, entry in gamedata.items():
        # Convert :: to _ for matching with YAML data
        yaml_func_name = normalize_func_name_colons_to_underscore(func_name, alias_to_name_map)

        # Determine library for this function
        library = None
        if "signatures" in entry and "library" in entry["signatures"]:
            library = entry["signatures"]["library"]
        elif yaml_func_name in func_lib_map:
            library = func_lib_map[yaml_func_name]

        if not library:
            print(f"  Warning: Unknown library for {func_name}, skipping")
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "unknown library"})
            continue

        # Find matching YAML data
        yaml_entry = yaml_data.get(yaml_func_name)
        if not yaml_entry or yaml_entry.get("library") != library:
            skipped_count += 1
            if debug:
                skipped_symbols.append({"name": func_name, "reason": "no matching YAML data"})
            continue

        # Update signatures
        if "signatures" in entry:
            for platform in platforms:
                record = yaml_entry.get(platform) or {}
                raw_sig = record.get("func_sig")
                # A global's key (IGameSystem_InitAllSystems_pFirst) carries gv_sig, which this
                # used to ignore: the template's value stayed from 14180 to 14182 and matched
                # twice on linux 14182. Only a gv_sig that starts AT the loading instruction
                # (gv_inst_offset 0) has the shape the plugin resolves, so only that is used.
                if raw_sig is None and yaml_entry.get("category") == "gv" and str(record.get("gv_inst_offset", "")) == "0":
                    raw_sig = record.get("gv_sig")
                if raw_sig:
                    sig = convert_sig_to_css(raw_sig)
                    entry["signatures"][platform] = sig
                    updated_count += 1
                    if debug:
                        updated_symbols.append({"name": func_name, "type": "signature", "platform": platform})

        if "signatures" in entry and _update_vtable_slot(entry, yaml_entry, platforms, prove):
            updated_count += 1
            if debug:
                updated_symbols.append({"name": func_name, "type": "vtable"})

        # Update offsets (vfunc_index or struct_member_offset)
        if "offsets" in entry:
            for platform in platforms:
                if platform in yaml_entry:
                    # Check for vfunc_index (virtual function offset)
                    if "vfunc_index" in yaml_entry[platform]:
                        entry["offsets"][platform] = yaml_entry[platform]["vfunc_index"]
                        updated_count += 1
                        if debug:
                            updated_symbols.append({"name": func_name, "type": "offset", "platform": platform})
                    # Check for struct_member_offset (struct member offset)
                    elif "struct_member_offset" in yaml_entry[platform]:
                        entry["offsets"][platform] = yaml_entry[platform]["struct_member_offset"]
                        updated_count += 1
                        if debug:
                            updated_symbols.append({"name": func_name, "type": "struct_offset", "platform": platform})

    # Write back
    with open(gamedata_path, "w", encoding="utf-8") as f:
        json.dump(gamedata, f, indent=2)
        f.write("\n")

    return updated_count, skipped_count, updated_symbols, skipped_symbols
