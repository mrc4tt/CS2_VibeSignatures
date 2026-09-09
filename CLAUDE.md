# CLAUDE.md — CS2_VibeSignatures fork

Learning-based rules from hands-on experience. Violating these causes broken configs, lost data, or wasted hours.

## NEVER DO

### 1. NEVER run `fix_duplicate_symbols.py -all`
It removes cross-stage symbol declarations that upstream uses intentionally (module stages re-declare symbols for different processing passes). Only use `-config configs/<specific>.yaml` on configs with actual validation errors. The surgical approach (remove only the validator-named duplicates, keep alias-bearing entries) is the only safe method.

### 2. NEVER blanket-remove merge conflict markers without checking both sides
`<<<<<<< HEAD` / `=======` / `>>>>>>> theirs` blocks: check which side has the richer data (func_size, vtable_name, aliases) before choosing. In add/add conflicts on artifacts, HEAD (server-agent) usually has fuller analysis data. In config conflicts, theirs (injected tasks) may be correct. Always verify the result parses as valid YAML.

### 3. NEVER use `git add -A` on the server without checking what's untracked
Dot-commits (`commit -m "."`) have deleted tracked files (missing_report.py incident) and swept in unwanted files (log files, alias_candidates). The pre-commit guard catches skill-deletions but not everything. Always `git status --short` first.

### 4. NEVER trust a unique byte-pattern match as function identification without boundary verification
A sig can match exactly one address and still be the wrong function. Always check:
- Padding before the match (cc/90/ud2 = function boundary)
- The prologue looks like a function head (push rbp / sub rsp / etc.)
- For POD twins (HUD family, OnTakeDamage family): check sibling-cluster VAs for disambiguation

### 5. NEVER assume vtable layouts are identical across platforms
Linux vtable slot 0 ≠ windows vtable slot 0. MSVC adds deleting-dtor pairs (+2 shift). Always verify slot index per platform independently (e.g., DropWeapon linux 29 / windows 28, AddResource linux 0 / windows 2).

### 6. NEVER trust a community/plugin sig blindly — verify it against the binary
Plugin sigs are often stale or wildcard-differently than what the pipeline expects. Always regex-scan the target binary and check: unique match + boundary padding + prologue shape. A 2-match result means twins (sibling disambiguation needed).

### 7. NEVER move the large JSON parses to the main thread in the WeaponPaints plugin
(`data/skins_*.json` ~0.6MB, `stickers_*.json` ~2.1MB) — these must stay in `Task.Run`. Only the small catalogs (gloves/agents/music/pins) are parsed synchronously. Moving them back causes `UNEXPECTED LONG FRAME DETECTED` on live servers.

### 8. NEVER simplify the `AddTimer(0.15f, ...)` deferred cosmetic application in `OnPlayerSpawn`
Applying on spawn or `NextFrame` crashes in native `SetModel`/`SetBodygroup` (pawn scene nodes not initialized). This is a deliberate safety delay.

### 9. NEVER forget to bump `WeaponPaintsConfig.Version` on Config.cs changes
Without it, `MigrateConfigFile` never rewrites existing user configs and new fields never reach operators.

### 10. NEVER run `run_linux.sh` and `run_windows.sh` simultaneously
They share idalib-mcp infrastructure (ports, IDB locks). The reap-preflight in each script kills ALL idalib-mcp processes — running both at once means they kill each other's sessions.

## ALWAYS DO

- **Re-pack snapshot after config changes** — `update_gamedata` validates config-digest against snapshot; a config edit without re-pack causes "digest mismatch"
- **Hydrate `bin/` from `bin_artifacts/` after every `git pull`** — `bin/` is untracked and doesn't auto-sync: `cp -ru bin_artifacts/<VER>/. bin/<VER>/`
- **Run `audit_duplicate_va.py` after every hunt round** — catches batch-contamination (same VA under multiple names, the 0x20c2700 incident)
- **Check `git check-ignore` before committing working files** — missing lists, logs, and alias candidates are now in .gitignore but weren't always
- **Use `git push` immediately after committing on server** — unpushed commits cause divergent branches that produce messy add/add conflicts later
- **Commit inside plugin repos after `deploy_local_plugins.sh`** — deployed gamedata sits uncommitted in ~/customGIT/* until you commit and push to git.miksen.me

## TOOL QUICK-REFERENCE

| Tool | When | Notes |
|------|------|-------|
| `missing_report.py` | After runs / before hunts | Writes `missing_<plat>_<ver>.txt` |
| `audit_duplicate_va.py` | After every hunt round | 0 suspect clusters = clean |
| `detect_aliases.py` | After snapshot pack | Catches renames (JoinTeam pattern) |
| `gen_references.sh` | After analysis complete | Resume-safe, auto-reap port 13337 |
| `add_gamever.sh` | New gamever release | Probes Steam for manifest IDs |
| `fix_duplicate_symbols.py` | Only on configs with validator errors | NEVER use `-all` |
| `enrich_vfunc_sigs.py` | After analysis | Adds func_sig to vfunc artifacts offline |
| `deploy_local_plugins.sh` | After gamedata generation | → ~/customGIT/weaponpaints + matchzy |
| `update_css_gamedata.sh` | After gamedata generation | → ~/CounterStrikeSharp install |

## IDA PLUGIN HOTKEYS (local PC)

| Hotkey | Tool | Strategy |
|--------|------|----------|
| Ctrl-Alt-H | auto-hunt v2 | 5 strategies: reloc, vtable, seed-sig, sibling, string-anchor |
| Ctrl-Alt-D | sig maker batch | Cursor-driven (renamed from S — Fusion conflict) |
| Ctrl-Alt-V | vtable finder | Interactive: class + slot + symbol |
| Ctrl-Alt-M | struct member emitter | Cursor on member-access instruction |

## AGENT SETUP

- **Local PC**: `CS2VIBE_AGENT=claude` (Max 5x, Sonnet default)
- **Server**: `CS2VIBE_AGENT=opencode` (z.ai coding plan, glm-5.3-flash)
- **LLM_DECOMPILE**: requires `LLM_APIKEY` (OpenAI /responses API — z.ai does NOT support this endpoint)
- Agent auto-select: if CS2VIBE_AGENT unset, scripts pick first installed CLI
