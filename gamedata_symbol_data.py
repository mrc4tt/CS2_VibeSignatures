from __future__ import annotations

import copy

import yaml

from gamedata_diagnostics import GamedataDiagnostic
from gamedata_symbol_config import downstream_aliases, source_candidate_names
from gamesymbol_store import SymbolStore


def load_config(config_path):
    """
    Load and parse one YAML config file.

    Args:
        config_path: Path to the config file

    Returns:
        Dictionary containing config data
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def merge_configs(base_config, extra_config):
    """
    Merge base config with per-gamedata extra config.

    Merge rules:
      - modules are matched by module name
      - symbols are matched by symbol name within each module
      - extra config overrides existing fields and appends new entries
    """
    if not isinstance(base_config, dict):
        return {}

    if not isinstance(extra_config, dict):
        return copy.deepcopy(base_config)

    merged = copy.deepcopy(base_config)
    merged_modules = merged.setdefault("modules", [])

    # Index base modules by name for fast merge/override.
    module_index = {}
    for idx, module in enumerate(merged_modules):
        if isinstance(module, dict):
            module_name = module.get("name")
            if module_name:
                module_index[module_name] = idx

    for extra_module in extra_config.get("modules", []):
        if not isinstance(extra_module, dict):
            continue

        module_name = extra_module.get("name")
        if not module_name or module_name not in module_index:
            merged_modules.append(copy.deepcopy(extra_module))
            if module_name:
                module_index[module_name] = len(merged_modules) - 1
            continue

        target_module = merged_modules[module_index[module_name]]

        # Override module-level fields except symbols (merged separately below).
        for key, value in extra_module.items():
            if key == "symbols":
                continue
            target_module[key] = copy.deepcopy(value)

        if "symbols" not in extra_module:
            continue

        target_symbols = target_module.setdefault("symbols", [])

        symbol_index = {}
        for idx, symbol in enumerate(target_symbols):
            if isinstance(symbol, dict):
                symbol_name = symbol.get("name")
                if symbol_name:
                    symbol_index[symbol_name] = idx

        for extra_symbol in extra_module.get("symbols", []):
            if not isinstance(extra_symbol, dict):
                continue

            symbol_name = extra_symbol.get("name")
            if symbol_name and symbol_name in symbol_index:
                symbol_idx = symbol_index[symbol_name]
                merged_symbol = copy.deepcopy(target_symbols[symbol_idx])
                merged_symbol.update(copy.deepcopy(extra_symbol))
                target_symbols[symbol_idx] = merged_symbol
            else:
                target_symbols.append(copy.deepcopy(extra_symbol))
                if symbol_name:
                    symbol_index[symbol_name] = len(target_symbols) - 1

    return merged


def parse_struct_yaml(yaml_data):
    """
    Parse struct YAML data and extract member offsets.

    Supported formats:
    1) New per-member format:
        struct_name: CBaseEntity
        member_name: m_nPlayerSlot
        offset: 0x240

    2) Legacy nested format:
        struct_name: CBaseEntity
        struct_offsets:
          0x240: m_nPlayerSlot 4

    Returns:
        Dictionary mapping member names to their offsets (as integers)
    """
    if not yaml_data or not isinstance(yaml_data, dict):
        return {}

    def _parse_offset(value):
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                raise ValueError("empty offset")
            return int(raw, 0)
        return int(value)

    # New per-member format
    member_name = yaml_data.get("member_name")
    if member_name is not None and yaml_data.get("offset") is not None:
        try:
            return {str(member_name): _parse_offset(yaml_data.get("offset"))}
        except Exception:
            return {}

    # Legacy nested format
    offsets_data = yaml_data.get("struct_offsets", {})
    if not isinstance(offsets_data, dict) or not offsets_data:
        return {}

    members = {}
    for offset_raw, value in offsets_data.items():
        try:
            offset = _parse_offset(offset_raw)
        except Exception:
            continue

        if isinstance(value, str):
            parts = value.split()
            if parts:
                members[parts[0]] = offset

    return members


def build_function_library_map(config):
    """
    Build a mapping from function names to library names.

    Args:
        config: Parsed analysis config data

    Returns:
        Dictionary mapping function names (and aliases) to library names
    """
    func_lib_map = {}

    for module in config.get("modules", []):
        module_name = module.get("name")
        if not module_name:
            continue

        for symbol in module.get("symbols", []):
            func_name = symbol.get("name")
            if func_name:
                func_lib_map[func_name] = module_name

                # Also add aliases (support both string and list format)
                aliases = symbol.get("alias", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                for alias in aliases:
                    func_lib_map[alias] = module_name

    return func_lib_map


def build_alias_to_name_map(config):
    """
    Build a mapping from aliases to function names.

    Args:
        config: Parsed analysis config data

    Returns:
        Dictionary mapping aliases to function names
    """
    alias_to_name = {}

    for module in config.get("modules", []):
        for symbol in module.get("symbols", []):
            func_name = symbol.get("name")
            if func_name:
                # Support both string and list format for alias
                aliases = symbol.get("alias", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                for alias in aliases:
                    alias_to_name[alias] = func_name

    return alias_to_name


def _canonical_key(module_name, filename):
    return f"{module_name}/{filename}"


def _target_platforms(symbol, platforms):
    symbol_platform = symbol.get("platform")
    if not symbol_platform:
        return platforms
    return [platform for platform in platforms if platform == symbol_platform]


def _diagnostic(
    reason,
    *,
    module_name,
    func_name,
    category,
    platform,
    attempted_paths,
    detail=None,
):
    return GamedataDiagnostic(
        reason=reason,
        severity="warning",
        module=module_name,
        symbol=func_name,
        category=category,
        platform=platform,
        canonical_path=attempted_paths[0],
        attempted_paths=tuple(attempted_paths),
        detail=detail,
    )


def _load_legacy_struct(store, cache, *, module_name, struct_name, platform):
    cache_key = (module_name, struct_name, platform)
    filename = f"{struct_name}.{platform}.yaml"
    if cache_key not in cache:
        payload = store.get(module_name, filename)
        cache[cache_key] = None if payload is None else parse_struct_yaml(payload)
    return cache[cache_key], filename


def _load_structmember_platform(
    store,
    cache,
    *,
    symbol_data,
    symbol,
    module_name,
    func_name,
    platform,
    diagnostics,
):
    member_name = symbol["member"]
    attempted_paths = []
    primary_found = False
    for candidate_name in source_candidate_names(func_name, symbol):
        primary_filename = f"{candidate_name}.{platform}.yaml"
        attempted_paths.append(_canonical_key(module_name, primary_filename))
        primary = store.get(module_name, primary_filename)
        primary_found = primary_found or primary is not None
        parsed = parse_struct_yaml(primary)
        if member_name in parsed:
            symbol_data[platform] = {"struct_member_offset": parsed[member_name]}
            return
    legacy, legacy_filename = _load_legacy_struct(
        store,
        cache,
        module_name=module_name,
        struct_name=symbol["struct"],
        platform=platform,
    )
    legacy_key = _canonical_key(module_name, legacy_filename)
    if legacy_key not in attempted_paths:
        attempted_paths.append(legacy_key)
    if legacy is not None and member_name in legacy:
        symbol_data[platform] = {"struct_member_offset": legacy[member_name]}
        return
    found_artifact = primary_found or legacy is not None
    diagnostics.append(
        _diagnostic(
            "structmember_member_missing" if found_artifact else "structmember_yaml_missing",
            module_name=module_name,
            func_name=func_name,
            category="structmember",
            platform=platform,
            attempted_paths=attempted_paths,
            detail=(f"member {member_name!r} was not present in available artifacts" if found_artifact else None),
        )
    )


def _load_standard_platform(store, symbol_data, *, symbol, category, module_name, func_name, platform, diagnostics):
    attempted_paths = []
    for candidate_name in source_candidate_names(func_name, symbol):
        filename = f"{candidate_name}.{platform}.yaml"
        attempted_paths.append(_canonical_key(module_name, filename))
        payload = store.get(module_name, filename)
        if not payload or (category == "patch" and "patch_bytes" not in payload):
            continue
        symbol_data[platform] = payload
        return
    diagnostics.append(
        _diagnostic(
            "patch_yaml_missing_or_invalid" if category == "patch" else "missing_yaml",
            module_name=module_name,
            func_name=func_name,
            category=category,
            platform=platform,
            attempted_paths=attempted_paths,
        )
    )


def _load_symbol(store, cache, *, symbol, module_name, platforms, diagnostics):
    func_name = symbol.get("name")
    if not func_name:
        return None
    category = symbol.get("category")
    if category == "struct":
        return None
    aliases = list(downstream_aliases(func_name, symbol))
    symbol_data = {"library": module_name, "category": category, "aliases": aliases}
    target_platforms = _target_platforms(symbol, platforms)
    if not target_platforms:
        return None
    if category == "structmember":
        if not symbol.get("struct") or not symbol.get("member"):
            for platform in target_platforms:
                path = _canonical_key(module_name, f"{func_name}.{platform}.yaml")
                diagnostics.append(
                    _diagnostic(
                        "structmember_config_invalid",
                        module_name=module_name,
                        func_name=func_name,
                        category=category,
                        platform=platform,
                        attempted_paths=(path,),
                        detail="structmember requires non-empty struct and member fields",
                    )
                )
            return symbol_data
        for platform in target_platforms:
            _load_structmember_platform(
                store,
                cache,
                symbol_data=symbol_data,
                symbol=symbol,
                module_name=module_name,
                func_name=func_name,
                platform=platform,
                diagnostics=diagnostics,
            )
        return symbol_data
    for platform in target_platforms:
        _load_standard_platform(
            store,
            symbol_data,
            symbol=symbol,
            category=category,
            module_name=module_name,
            func_name=func_name,
            platform=platform,
            diagnostics=diagnostics,
        )
    return symbol_data


def load_all_yaml_data(config, symbol_store: SymbolStore, platforms, *, debug=False):
    """
    Load all YAML signature data for the specified game version.

    Args:
        config: Parsed analysis config data
        symbol_store: Read-only symbol source
        platforms: List of platforms to load
        debug: Compatibility argument; diagnostics are always collected

    Returns:
        Tuple: (yaml_data dict, diagnostics list)
        yaml_data: {
            func_name: {
                "library": str,
                "category": str,
                "aliases": list[str],
                platform: yaml_data
            }
        }
        diagnostics: List of structured artifact-resolution diagnostics
    """
    yaml_data = {}
    diagnostics = []

    legacy_struct_cache = {}
    for module in config.get("modules", []):
        module_name = module.get("name")
        if not module_name:
            continue
        for symbol in module.get("symbols", []):
            symbol_data = _load_symbol(
                symbol_store,
                legacy_struct_cache,
                symbol=symbol,
                module_name=module_name,
                platforms=platforms,
                diagnostics=diagnostics,
            )
            if symbol_data is not None:
                yaml_data[symbol["name"]] = symbol_data

    return yaml_data, diagnostics
