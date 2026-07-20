#!/usr/bin/env python3
"""
Gamedata Update Script for CS2_VibeSignatures

Updates gamedata files for various CS2 plugin frameworks from a canonical
game-symbol snapshot. Generator source and overlays are discovered below
gamedata-generators/, while final payloads are written to a separate
versioned output root.

Usage:
    python update_gamedata.py -gamever=<version> -snapshot=<candidate.yaml> [-configyaml=<path>] [-modulesdir=gamedata-generators] [-outputdir=gamedata/<version>] [-platform=windows,linux] [-debug] [-download_latest] [-strict]

    -gamever: Game version for YAML path (required)
    -configyaml: Analysis config path (default: configs/<GAMEVER>.yaml)
    -snapshot: Canonical candidate or published snapshot (required)
    -modulesdir: Directory containing trusted generator modules
    -outputdir: Exact versioned output directory
    -platform: Comma-separated platforms (default: windows,linux)
    -debug: Print detailed information about missing, updated, and skipped symbols
    -download_latest: Download latest gamedata files from upstream repos before updating

Requirements:
    uv sync
"""

import argparse
import os
import sys
from urllib.parse import urlparse
import shutil

from analysis_config import AnalysisConfigError, resolve_analysis_config
from gamedata_contract import (
    GamedataContractError,
    canonicalize_output_text,
    discover_generator_modules,
    gamedata_manifest_sha256,
    generator_contract_sha256,
    validate_output_tree,
)

from gamedata_symbol_data import (
    build_alias_to_name_map,
    build_function_library_map,
    load_all_yaml_data,
    load_config,
    merge_configs,
)
from gamesymbol_store import SymbolStoreError, open_snapshot_store

try:
    import httpx
except ImportError:
    httpx = None

# Load .env so GITHUB_TOKEN (for the private fork gamedata source) and other settings are
# picked up without a manual export. Matches the load_dotenv() pattern used elsewhere in the
# repo. Guarded so a missing python-dotenv never breaks the plain (no-download) path.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# Default values
DEFAULT_MODULES_DIR = "gamedata-generators"
DEFAULT_PLATFORMS = "windows,linux"


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
    parser.add_argument("-modulesdir", default=DEFAULT_MODULES_DIR, help="Directory containing generator modules")
    parser.add_argument("-outputdir", default=None, help="Versioned output root; defaults to gamedata/<GAMEVER>")
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
    parser.add_argument("-strict", action="store_true", help="Fail on any generator, download, or output error")

    return parser.parse_args()


def discover_gamedata_modules(modules_dir):
    """Compatibility wrapper returning the strict generator contracts."""
    return discover_generator_modules(modules_dir)


def download_latest_gamedata(modules, output_root, *, strict=False):
    """Download declared upstream payloads into a separate output root."""
    if httpx is None:
        raise GamedataContractError("httpx is required for -download_latest; install dependencies with uv sync")
    output_root = os.path.abspath(output_root)
    success_count = 0
    failures: list[str] = []
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(10.0, read=30.0)) as client:
        for contract in modules:
            if not contract.download_sources:
                continue

            print(f"  {module_name}:")

            for url, relative_path in sources:
                abs_path = os.path.join(dist_dir, subdir, relative_path)

                # Attach a PAT ONLY for GitHub hosts (needed for private forks e.g.
                # mrc4tt/CounterStrikeSharp via the contents API). The token is read from the
                # environment, never hardcoded, and never sent to non-github download sources.
                headers = {}
                host = (urlparse(url).hostname or "").lower()
                if host in ("api.github.com", "raw.githubusercontent.com"):
                    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    if host == "api.github.com":
                        # Return the raw file bytes instead of the base64 JSON envelope.
                        headers["Accept"] = "application/vnd.github.raw"
                        headers["X-GitHub-Api-Version"] = "2022-11-28"

            print(f"  {contract.name}:")
            for url, relative_path in contract.download_sources:
                destination = os.path.join(output_root, contract.directory, *relative_path.split("/"))
                temporary = destination + ".download"

                try:
                    response = client.get(url, headers=headers)
                    response.raise_for_status()
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    with open(temporary, "wb") as file:
                        file.write(response.content)
                    os.replace(temporary, destination)
                    print(f"    Downloaded: {relative_path}")
                    success_count += 1
                except (httpx.HTTPError, OSError) as exc:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                    failures.append(f"{contract.directory}/{relative_path}: {exc}")
    if failures and strict:
        raise GamedataContractError("gamedata download failed: " + "; ".join(failures))
    for failure in failures:
        print(f"    Warning: {failure}")
    return success_count, len(failures)


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


def _module_data(contract, base_config, base_data, base_maps, symbol_store, platforms, debug, strict):
    extra_config_path = contract.source_dir / "config.yaml"
    if not extra_config_path.is_file():
        return base_data, *base_maps, []
    try:
        extra_config = load_config(extra_config_path)
        if not isinstance(extra_config, dict):
            raise ValueError("top-level YAML value must be a mapping")
        merged_config = merge_configs(base_config, extra_config)
        func_lib_map = build_function_library_map(merged_config)
        alias_map = build_alias_to_name_map(merged_config)
        yaml_data, missing = load_all_yaml_data(merged_config, symbol_store, platforms, debug=debug)
        print(f"  Using merged config with {len(func_lib_map)} function mappings")
        return yaml_data, func_lib_map, alias_map, missing
    except Exception as exc:
        if strict:
            raise GamedataContractError(f"failed to load extra config for {contract.directory}: {exc}") from exc
        print(f"  Warning: Failed to load extra config for {contract.name}: {exc}")
        print("  Falling back to base config")
        return base_data, *base_maps, []


def generate_gamedata(
    *,
    gamever,
    snapshot_path,
    config_path,
    modules_dir,
    output_root,
    platforms,
    debug=False,
    download_latest=False,
    strict=False,
):
    """Generate one version's declared final payloads below a separate output root."""
    modules_dir = os.path.abspath(modules_dir)
    output_root = os.path.abspath(output_root)
    print(f"Config file: {config_path}")
    symbol_store = open_snapshot_store(
        snapshot_path=snapshot_path,
        config_path=config_path,
        expected_game_version=gamever,
    )
    print("Symbol source: snapshot")
    print(f"Candidate SHA-256: {symbol_store.candidate_sha256}")
    print(f"Generator directory: {modules_dir}")
    print(f"Versioned output directory: {output_root}")
    print(f"Platforms: {', '.join(platforms)}")
    base_config = load_config(config_path)
    if not isinstance(base_config, dict):
        raise GamedataContractError(f"invalid analysis config mapping: {config_path}")
    base_func_lib_map = build_function_library_map(base_config)
    base_alias_map = build_alias_to_name_map(base_config)
    base_data, base_missing = load_all_yaml_data(base_config, symbol_store, platforms, debug=debug)
    modules = discover_generator_modules(modules_dir)
    print(f"Found {len(modules)} enabled generators")
    os.makedirs(output_root, exist_ok=True)
    for contract in modules:
        for source, target in contract.static_sources:
            destination = os.path.join(output_root, contract.directory, *target.split("/"))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(contract.source_dir / source, destination)
            print(f"  Seeded static template: {contract.directory}/{target}")
    if download_latest:
        downloaded, failed = download_latest_gamedata(modules, output_root, strict=strict)
        print(f"Downloads complete: {downloaded} succeeded, {failed} failed")

    total_updated = 0
    total_skipped = 0
    all_updated_symbols = {}
    all_skipped_symbols = {}
    all_missing_symbols = list(base_missing) if debug else []
    for contract in modules:
        print(f"\n{'=' * 50}\nUpdating {contract.name}...")
        yaml_data, func_lib_map, alias_map, missing = _module_data(
            contract,
            base_config,
            base_data,
            (base_func_lib_map, base_alias_map),
            symbol_store,
            platforms,
            debug,
            strict,
        )
        if debug:
            all_missing_symbols.extend(missing)
        module_output_root = os.path.join(output_root, contract.directory)
        try:
            updated, skipped, updated_symbols, skipped_symbols = contract.module.update(
                yaml_data, func_lib_map, platforms, module_output_root, alias_map, debug
            )
        except Exception as exc:
            if strict:
                raise GamedataContractError(f"generator {contract.directory} failed: {exc}") from exc
            print(f"  Error updating {contract.name}: {exc}")
            updated, skipped, updated_symbols, skipped_symbols = 0, 0, [], []
        print(f"  Updated: {updated}, Skipped: {skipped}")
        total_updated += updated
        total_skipped += skipped
        all_updated_symbols[contract.name] = updated_symbols
        all_skipped_symbols[contract.name] = skipped_symbols

    canonicalize_output_text(output_root)
    files = validate_output_tree(output_root, gamever, modules) if strict else []
    if debug:
        print_debug_info("Summary", all_missing_symbols, all_updated_symbols, all_skipped_symbols)
    print(f"\n{'=' * 50}\nTotal: {total_updated} updates, {total_skipped} skipped")
    return {
        "updated": total_updated,
        "skipped": total_skipped,
        "generator_contract_sha256": generator_contract_sha256(modules),
        "gamedata_manifest_sha256": gamedata_manifest_sha256(files) if strict else None,
        "files": files,
    }


def main():
    args = parse_args()
    gamever = args.gamever
    try:
        config_path = str(resolve_analysis_config(gamever, args.configyaml))
        script_dir = os.path.dirname(os.path.abspath(__file__))
        modules_dir = args.modulesdir if os.path.isabs(args.modulesdir) else os.path.join(script_dir, args.modulesdir)
        output_dir = args.outputdir or os.path.join("gamedata", gamever)
        output_dir = output_dir if os.path.isabs(output_dir) else os.path.join(script_dir, output_dir)
        generate_gamedata(
            gamever=gamever,
            snapshot_path=args.snapshot,
            config_path=config_path,
            modules_dir=modules_dir,
            output_root=output_dir,
            platforms=[item.strip() for item in args.platform.split(",") if item.strip()],
            debug=args.debug,
            download_latest=args.download_latest,
            strict=args.strict,
        )
    except (AnalysisConfigError, SymbolStoreError, GamedataContractError, OSError, ValueError) as exc:
        print(f"Error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
