#!/usr/bin/env python3
"""
Gamedata Update Script for CS2_VibeSignatures

Updates gamedata files for various CS2 plugin frameworks from a canonical
game-symbol snapshot. Automatically discovers and loads gamedata
modules from dist/*/gamedata.py and applies optional per-module config
overlays from dist/*/config.yaml.

Usage:
    python update_gamedata.py -gamever=<version> -snapshot=<candidate.yaml> [-configyaml=<path>] [-distdir=dist] [-platform=windows,linux] [-debug] [-download_latest]

    -gamever: Game version for YAML path (required)
    -configyaml: Analysis config path (default: configs/<GAMEVER>.yaml)
    -snapshot: Canonical candidate or published snapshot (required)
    -distdir: Directory containing gamedata modules (default: dist)
    -platform: Comma-separated platforms (default: windows,linux)
    -debug: Print detailed information about missing, updated, and skipped symbols
    -download_latest: Download latest gamedata files from upstream repos before updating

Requirements:
    uv sync
"""

import argparse
import copy
import importlib.util
import os
import sys

from analysis_config import AnalysisConfigError, resolve_analysis_config
from gamesymbol_store import SymbolStore, SymbolStoreError, open_snapshot_store

try:
    import yaml
except ImportError:
    print("Error: Missing required dependency: yaml")
    print("Please install required dependencies with: uv sync")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None


# Default values
DEFAULT_DIST_DIR = "dist"
DEFAULT_PLATFORMS = "windows,linux"

PATCH_COMPAT_ALIASES = {
    "CCSPlayer_MovementServices_FullWalkMove_SpeedClamp": [
        "ServerMovementUnlock",
    ],
    "CCSPlayer_MovementServices_CheckJumpButton_WaterPatch": [
        "CheckJumpButtonWater",
        "FixWaterFloorJump",
    ],
    "CCSBotManager_AddBot_BotNavIgnore": [
        "BotNavIgnore",
    ],
}


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Update gamedata files from YAML signatures")
    parser.add_argument("-gamever", required=True, help="Game version for YAML path (required)")
    parser.add_argument(
        "-configyaml",
        default=None,
        help="Analysis config path; defaults to configs/<GAMEVER>.yaml",
    )
    parser.add_argument("-snapshot", required=True, help="Canonical candidate or published game-symbol snapshot")
    parser.add_argument(
        "-distdir",
        default=DEFAULT_DIST_DIR,
        help=f"Directory containing gamedata modules (default: {DEFAULT_DIST_DIR})",
    )
    parser.add_argument(
        "-platform", default=DEFAULT_PLATFORMS, help=f"Comma-separated platforms (default: {DEFAULT_PLATFORMS})"
    )
    parser.add_argument(
        "-debug", action="store_true", help="Print detailed information about missing and updated symbols"
    )
    parser.add_argument(
        "-download_latest",
        action="store_true",
        help="Download latest gamedata files from upstream repos before updating",
    )

    return parser.parse_args()


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


def _symbol_aliases(func_name, symbol):
    aliases = symbol.get("alias", [])
    aliases = [aliases] if isinstance(aliases, str) else list(aliases)
    if symbol.get("category") == "patch":
        aliases = list(dict.fromkeys([*aliases, *PATCH_COMPAT_ALIASES.get(func_name, [])]))
    return aliases


def _missing_item(func_name, module_name, platform, *, filename):
    return {
        "name": func_name,
        "library": module_name,
        "platform": platform,
        "path": _canonical_key(module_name, filename),
    }


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
    missing_symbols,
    debug,
):
    member_name = symbol["member"]
    primary_filename = f"{func_name}.{platform}.yaml"
    primary = store.get(module_name, primary_filename)
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
    if legacy is not None and member_name in legacy:
        symbol_data[platform] = {"struct_member_offset": legacy[member_name]}
        return
    if debug:
        missing_symbols.append(_missing_item(func_name, module_name, platform, filename=primary_filename))
    primary_key = _canonical_key(module_name, primary_filename)
    legacy_key = _canonical_key(module_name, legacy_filename)
    if primary is not None:
        print(f"  Warning: Member {member_name} not found in {primary_key}")
    elif legacy is not None:
        print(f"  Warning: Member {member_name} not found in {legacy_key}")
    else:
        print(f"  Warning: Struct member YAML not found: {primary_key}")


def _load_standard_platform(store, symbol_data, *, category, aliases, module_name, func_name, platform):
    candidate_names = [func_name, *aliases] if category == "patch" else [func_name]
    alias_keys = []
    for candidate_name in candidate_names:
        filename = f"{candidate_name}.{platform}.yaml"
        payload = store.get(module_name, filename)
        if not payload or (category == "patch" and "patch_bytes" not in payload):
            if candidate_name != func_name:
                alias_keys.append(_canonical_key(module_name, filename))
            continue
        symbol_data[platform] = payload
        return True, alias_keys
    return False, alias_keys


def _warn_standard_missing(category, missing_key, alias_keys):
    if category == "patch" and alias_keys:
        print(
            f"  Warning: Patch YAML not found or missing patch_bytes: "
            f"{missing_key} (tried aliases: {', '.join(alias_keys)})"
        )
    elif category == "patch":
        print(f"  Warning: Patch YAML not found or missing patch_bytes: {missing_key}")
    else:
        print(f"  Warning: YAML not found: {missing_key}")


def _load_symbol(store, cache, *, symbol, module_name, platforms, missing_symbols, debug):
    func_name = symbol.get("name")
    if not func_name:
        return None
    category = symbol.get("category")
    aliases = _symbol_aliases(func_name, symbol)
    symbol_data = {"library": module_name, "category": category, "aliases": aliases}
    target_platforms = _target_platforms(symbol, platforms)
    if not target_platforms:
        return None
    if category == "structmember":
        if not symbol.get("struct") or not symbol.get("member"):
            print(f"  Warning: structmember {func_name} missing struct or member field")
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
                missing_symbols=missing_symbols,
                debug=debug,
            )
        return symbol_data
    for platform in target_platforms:
        loaded, alias_keys = _load_standard_platform(
            store,
            symbol_data,
            category=category,
            aliases=aliases,
            module_name=module_name,
            func_name=func_name,
            platform=platform,
        )
        if loaded:
            continue
        filename = f"{func_name}.{platform}.yaml"
        if debug:
            missing_symbols.append(_missing_item(func_name, module_name, platform, filename=filename))
        _warn_standard_missing(category, _canonical_key(module_name, filename), alias_keys)
    return symbol_data


def load_all_yaml_data(config, symbol_store: SymbolStore, platforms, *, debug=False):
    """
    Load all YAML signature data for the specified game version.

    Args:
        config: Parsed analysis config data
        symbol_store: Read-only symbol source
        platforms: List of platforms to load
        debug: If True, collect missing symbols info

    Returns:
        Tuple: (yaml_data dict, missing_symbols list)
        yaml_data: {
            func_name: {
                "library": str,
                "category": str,
                "aliases": list[str],
                platform: yaml_data
            }
        }
        missing_symbols: List of {"name": str, "library": str, "platform": str, "path": str}
    """
    yaml_data = {}
    missing_symbols = []

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
                missing_symbols=missing_symbols,
                debug=debug,
            )
            if symbol_data is not None:
                yaml_data[symbol["name"]] = symbol_data

    return yaml_data, missing_symbols


def discover_gamedata_modules(dist_dir):
    """
    Discover and load gamedata modules from dist/*/gamedata.py.

    Args:
        dist_dir: Path to the dist directory

    Returns:
        List of tuples: [(subdir_name, module), ...]
    """
    modules = []

    if not os.path.isdir(dist_dir):
        print(f"Warning: dist directory not found: {dist_dir}")
        return modules

    for subdir in sorted(os.listdir(dist_dir)):
        subdir_path = os.path.join(dist_dir, subdir)
        if not os.path.isdir(subdir_path):
            continue

        module_path = os.path.join(subdir_path, "gamedata.py")
        if not os.path.isfile(module_path):
            continue

        try:
            # Dynamically load the module
            spec = importlib.util.spec_from_file_location(f"gamedata_{subdir}", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Check if module is enabled
            if getattr(module, "MODULE_ENABLED", True):
                modules.append((subdir, module))
            else:
                print(f"  Skipping disabled module: {subdir}")
        except Exception as e:
            print(f"  Warning: Failed to load module {subdir}: {e}")

    return modules


def download_latest_gamedata(modules, dist_dir):
    """
    Download latest gamedata files from upstream GitHub repos.

    For each module that exports DOWNLOAD_SOURCES, downloads each file
    and saves it to the appropriate path under dist_dir.

    Args:
        modules: List of (subdir, module) tuples from discover_gamedata_modules()
        dist_dir: Base dist directory path

    Returns:
        Tuple of (success_count, failure_count)
    """
    if httpx is None:
        print("Error: httpx is required for -download_latest. Install with: uv sync")
        return 0, 0

    success_count = 0
    failure_count = 0

    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(10.0, read=30.0),
    ) as client:
        for subdir, module in modules:
            module_name = getattr(module, "MODULE_NAME", subdir)
            sources = getattr(module, "DOWNLOAD_SOURCES", None)

            if not sources:
                continue

            print(f"  {module_name}:")

            for url, relative_path in sources:
                abs_path = os.path.join(dist_dir, subdir, relative_path)

                try:
                    response = client.get(url)
                    response.raise_for_status()

                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

                    with open(abs_path, "wb") as f:
                        f.write(response.content)

                    print(f"    Downloaded: {relative_path}")
                    success_count += 1

                except httpx.HTTPStatusError as e:
                    print(f"    Warning: HTTP {e.response.status_code} for {url}")
                    failure_count += 1

                except (httpx.RequestError, OSError) as e:
                    print(f"    Warning: Failed to download {relative_path}: {e}")
                    failure_count += 1

    return success_count, failure_count


def print_debug_info(title, missing_symbols, updated_symbols, skipped_symbols):
    """
    Print detailed debug information.

    Args:
        title: Section title
        missing_symbols: List of missing symbols from YAML loading
        updated_symbols: Dict of {target_name: list of updated symbols}
        skipped_symbols: Dict of {target_name: list of skipped symbols}
    """
    print(f"\n{'=' * 60}")
    print(f"DEBUG INFO: {title}")
    print("=" * 60)

    if missing_symbols:
        print(f"\n[Missing YAML Files] ({len(missing_symbols)} items)")
        for item in missing_symbols:
            print(f"  - {item['name']} ({item['library']}/{item['platform']})")

    for target_name, symbols in updated_symbols.items():
        if symbols:
            print(f"\n[{target_name}] Updated Symbols ({len(symbols)} items)")
            for item in symbols:
                print(f"  + {item['name']} ({item['type']}/{item['platform']})")

    for target_name, symbols in skipped_symbols.items():
        if symbols:
            print(f"\n[{target_name}] Skipped Symbols ({len(symbols)} items)")
            for item in symbols:
                print(f"  - {item['name']}: {item['reason']}")


def main():
    """Main entry point."""
    args = parse_args()

    snapshot_path = args.snapshot
    dist_dir = args.distdir
    gamever = args.gamever
    platforms = [p.strip() for p in args.platform.split(",")]
    debug = args.debug
    try:
        config_path = str(resolve_analysis_config(gamever, args.configyaml))
    except AnalysisConfigError as exc:
        print(f"Error: {exc}")
        return 2

    # Get script directory for resolving relative paths
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Resolve dist_dir to absolute path
    if not os.path.isabs(dist_dir):
        dist_dir = os.path.join(script_dir, dist_dir)

    print(f"Config file: {config_path}")
    try:
        symbol_store = open_snapshot_store(
            snapshot_path=snapshot_path,
            config_path=config_path,
            expected_game_version=gamever,
        )
    except SymbolStoreError as exc:
        print(f"Error: {exc}")
        return 2

    print("Symbol source: snapshot")
    print(f"Candidate SHA-256: {symbol_store.candidate_sha256}")
    print(f"Game version: {symbol_store.game_version}")
    print(f"File count: {symbol_store.file_count}")
    print(f"Config digest: {symbol_store.config_sha256}")
    print(f"Dist directory: {dist_dir}")
    print(f"Game version: {gamever}")
    print(f"Platforms: {', '.join(platforms)}")
    if debug:
        print("Debug mode: enabled")

    # Load base config
    print("\nLoading base config...")
    base_config = load_config(config_path)
    if not isinstance(base_config, dict):
        print(f"Error: Invalid config format (expected mapping): {config_path}")
        sys.exit(1)

    # Build base function mappings
    base_func_lib_map = build_function_library_map(base_config)
    print(f"Found {len(base_func_lib_map)} base function mappings")

    # Build base alias mapping for :: to _ conversion
    base_alias_to_name_map = build_alias_to_name_map(base_config)

    # Load base YAML data
    print("\nLoading base YAML data...")
    base_yaml_data, base_missing_symbols = load_all_yaml_data(base_config, symbol_store, platforms, debug=debug)
    print(f"Loaded base data for {len(base_yaml_data)} functions")

    # Discover gamedata modules
    print("\nDiscovering gamedata modules...")
    modules = discover_gamedata_modules(dist_dir)
    print(f"Found {len(modules)} enabled modules")

    # Download latest gamedata files if requested
    if args.download_latest:
        print("\nDownloading latest gamedata files...")
        dl_ok, dl_fail = download_latest_gamedata(modules, dist_dir)
        print(f"Downloads complete: {dl_ok} succeeded, {dl_fail} failed")

    # Collect debug info
    all_updated_symbols = {}
    all_skipped_symbols = {}
    all_missing_symbols = list(base_missing_symbols) if debug else []

    # Update each discovered module
    total_updated = 0
    total_skipped = 0

    for subdir, module in modules:
        module_name = getattr(module, "MODULE_NAME", subdir)
        module_dist_dir = os.path.join(dist_dir, subdir)

        # Default to base config-derived data.
        module_func_lib_map = base_func_lib_map
        module_alias_to_name_map = base_alias_to_name_map
        module_yaml_data = base_yaml_data

        extra_config_path = os.path.join(module_dist_dir, "config.yaml")
        if os.path.isfile(extra_config_path):
            print(f"\n{'=' * 50}")
            print(f"Updating {module_name}...")
            print(f"  Loading extra config: {extra_config_path}")

            try:
                extra_config = load_config(extra_config_path)
                if not isinstance(extra_config, dict):
                    raise ValueError("top-level YAML value must be a mapping")

                merged_config = merge_configs(base_config, extra_config)
                module_func_lib_map = build_function_library_map(merged_config)
                module_alias_to_name_map = build_alias_to_name_map(merged_config)
                module_yaml_data, module_missing_symbols = load_all_yaml_data(
                    merged_config, symbol_store, platforms, debug=debug
                )
                print(f"  Using merged config with {len(module_func_lib_map)} function mappings")
                if debug:
                    all_missing_symbols.extend(module_missing_symbols)
            except Exception as e:
                print(f"  Warning: Failed to load extra config for {module_name}: {e}")
                print("  Falling back to base config")
        else:
            print(f"\n{'=' * 50}")
            print(f"Updating {module_name}...")

        try:
            updated, skipped, updated_syms, skipped_syms = module.update(
                module_yaml_data, module_func_lib_map, platforms, module_dist_dir, module_alias_to_name_map, debug
            )
            print(f"  Updated: {updated}, Skipped: {skipped}")
            total_updated += updated
            total_skipped += skipped
            all_updated_symbols[module_name] = updated_syms
            all_skipped_symbols[module_name] = skipped_syms
        except Exception as e:
            print(f"  Error updating {module_name}: {e}")
            all_updated_symbols[module_name] = []
            all_skipped_symbols[module_name] = []

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Total: {total_updated} updates, {total_skipped} skipped")

    # Print debug info if enabled
    if debug:
        print_debug_info("Summary", all_missing_symbols, all_updated_symbols, all_skipped_symbols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
