# update_gamedata

## Overview
Generate and update gamedata (JSON/VDF/JSONC, etc.) for multiple plugins/frameworks from an immutable game-symbol snapshot.

## Responsibilities
- Parse command-line arguments and read `configs/<GAMEVER>.yaml`.
- Require `-snapshot`, open it through `SnapshotSymbolStore`, and validate game version, config digest, schema, and canonical bytes.
- Query symbol payloads from the in-memory read-only store without a directory or `bin` fallback.
- Build mappings from function names to library/category/alias.
- Convert YAML signatures into target formats and write back to corresponding gamedata files.
- Output update/skip statistics.

## Files Involved (no line numbers)
- update_gamedata.py
- configs/<GAMEVER>.yaml
- gamesymbol_store.py
- gamesymbols/<gamever>.yaml or an untracked actual candidate snapshot
- CounterStrikeSharp/gamedata/gamedata.json
- cs2fixes/gamedata/cs2fixes.games.txt
- cs2kz/gamedata/cs2kz-core.games.txt
- SwiftlyS2/gamedata/signatures.jsonc
- SwiftlyS2/gamedata/offsets.jsonc
- plugify/gamedata/gamedata.jsonc

## Architecture
Core flow is a serial pipeline of "open validated snapshot -> load config -> aggregate symbols -> update by format":
```
parse_args
  -> open_snapshot_store
  -> load_config
  -> build_function_library_map / build_alias_to_name_map
  -> load_all_yaml_data (query the immutable SymbolStore)
  -> update_counterstrikesharp (JSON)
  -> update_cs2fixes (VDF)
  -> update_cs2kz (VDF)
  -> update_swiftlys2 (JSONC: signatures/offsets)
  -> update_plugify (JSONC)
```
Format conversion is handled by `convert_sig_to_css` / `convert_sig_to_cs2fixes` / `convert_sig_to_swiftly`; names containing `::` are mapped through `normalize_func_name_colons_to_underscore` and `alias_to_name_map`. VDF output handles backslash escaping to satisfy target plugin format requirements.

## Dependencies
- PyYAML (read `configs/<GAMEVER>.yaml` and YAML signatures)
- requests (unused)
- vdf (parse/generate VDF)
- JSON/JSONC read-write (builtin `json` + JSONC comment stripping)
- Canonical game-symbol snapshot and target gamedata paths for each plugin

## Notes
- JSONC write-back does not preserve comments (`save_jsonc` writes plain JSON directly).
- Missing snapshot entries trigger a warning and are skipped.
- Incomplete `::` name or alias mapping causes skips.
- VDF output must replace `\\x` with `\x`; otherwise CS2Fixes/CS2KZ parsing will not match.

## Callers (optional)
- Direct CLI invocation: `python update_gamedata.py -gamever 14168 -snapshot gamesymbols/14168.yaml [-debug]`
