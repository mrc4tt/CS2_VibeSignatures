# CLAUDE.md — CS2_VibeSignatures fork

Learning-based rules from hands-on experience. Violating these causes broken configs, lost data, or wasted hours.

## HOW THE PIPELINE WORKS

Five stages. Each one reads only the stage before it, so a repair upstream is invisible
downstream until that stage is re-run.

```
configs/<gamever>.yaml          analysis config: symbols + find-tasks (the declared set)
        |  run_linux.sh / run_windows.sh   (IDA + agents, per module)
        v
bin_artifacts/<gamever>/<module>/<Symbol>.<platform>.yaml
        |                       one file per symbol per platform, the ground truth
        |  gamesymbol_snapshot.py pack
        v
gamesymbols/<gamever>.yaml      packed snapshot, stamped with the config digest
        |  update_gamedata.py
        v
gamedata/<gamever>/<plugin>/    one dir per plugin, from gamedata-generators/<plugin>/ (14 of them)
        |  deploy_local_plugins.sh + update_css_gamedata.sh
        v
~/customGIT/*  and  ~/CounterStrikeSharp     (still needs a commit inside each plugin repo)

One generator module per plugin lives in `gamedata-generators/<plugin>/`; it decides which keys
that plugin ships and in what format. Adding a plugin means adding a generator there, not touching
the snapshot.
```

`bin/<gamever>/` is an untracked working copy hydrated from `bin_artifacts/` — it is not a
pipeline stage, and it does not auto-sync after a `git pull`.

**Where a symbol comes from.** A config entry names a symbol; a `find-<Symbol>` task declares
that it should exist. Recovery is attempted in this order, cheapest first:
1. `ida_preprocessor_scripts/find-<task>.py` — a deterministic relocation from the previous
   gamever's baseline (no LLM, no agent). One file per config **task** name.
2. `auto_hunt_headless.py` — five strategies in pure Python (reloc, vtable, seed-sig, sibling,
   string-anchor); runs on the server with no IDA.
3. The IDA-side auto-hunt (Ctrl-Alt-H) and the agent-driven finder skills in `.claude/skills/`.
4. Hand analysis, with `idat` (headless IDA, `/root/ida-pro-9.1/idat -A -S"<script>" -L"<log>" <binary>`;
   the IDB is `<binary>.i64`, e.g. `client.dll.i64`).

**What an artifact holds.** `func_sig` + `func_va` for a function; `gv_va` for a global (the data
address the RIP-relative operand points at, NOT the match address); `vfunc_index` +
`vfunc_offset` (= 8 × index) for a virtual; `offset` for a struct member. `func_size` is internal
metadata only — it never reaches a plugin. The filename is always `<Symbol>.<platform>.yaml` with
no role suffix.

## INVARIANTS ("iorden" means all of these hold)

- **Declared set comes from find-tasks, not from `symbols:`.** An artifact with no declaring task
  is dropped at pack time with "Ignoring undeclared symbol YAML". A task's `expected_output`
  makes it required (pack dies on a missing file); `optional_output` declares it without
  requiring it.
- **Snapshot digest matches the config.** The snapshot stores `config_sha256`; any config edit
  without a re-pack makes it untrusted — "snapshot config digest mismatch".
- **`alias` vs `source_alias`.** `alias` = extra downstream gamedata keys this symbol writes;
  `source_alias` = alternative artifact filenames this symbol may read. Two symbols must not read
  one artifact — `gamedata_config_validation` rejects it as
  "<module>.<symbol>.source_alias: collision for <category>/<platform>" — and two symbols should
  not write one key (see rule 15).
- **`platform:` pins the lookup.** A symbol that only exists on one platform gets
  `platform: windows` (or `linux`). This is the only correct lever — it drives `_target_platforms`
  in `gamedata_symbol_data.py`, and `gen_references.sh` now expands only the pinned platform, so a
  pinned symbol stops being reported as a missing reference.
- **Names must line up exactly.** A preprocessor's filename equals the config **task** name; a
  skill's frontmatter `name:` equals its directory name (a mismatch means the skill never loads);
  an artifact's filename equals `<symbol>.<platform>`.
- **Config YAML has no duplicate mapping keys.** Enforced by `_StrictLoader` in `load_config`.
- **Every artifact is verifiable against its binary.** `validate_artifacts.py` re-reads the
  binary and checks the stored signature still matches at the stored VA, the match is unique, the
  boundary looks like a function head, `gv_va` equals the RIP target, `vfunc_offset` equals
  8 × index, and the class vtable (resolved via RTTI) really holds `func_va` in that slot.

## VERIFICATION BATTERY

Run in this order after any change. Anything but the stated result is a defect, not noise.

```bash
VER=14181
# 1. artifacts -> snapshot (every artifact or config change needs this)
uv run gamesymbol_snapshot.py pack -gamever $VER -snapshot gamesymbols/$VER.yaml
uv run gamesymbol_snapshot.py check-contract -gamever $VER -snapshot gamesymbols/$VER.yaml
# 2. snapshot -> gamedata; target is 0 warnings, 0 errors
uv run update_gamedata.py -gamever $VER -snapshot gamesymbols/$VER.yaml -outputdir gamedata/$VER
# 3. artifacts vs the actual binaries (-strict fails on warnings)
uv run validate_artifacts.py -gamever $VER
# 4. batch contamination, in artifacts AND in the packed snapshot
uv run audit_duplicate_va.py -gamever $VER
# 5. upstream renames, and what is still missing
uv run detect_aliases.py -gamever $VER -platform linux
uv run detect_aliases.py -gamever $VER -platform windows
uv run missing_report.py -gamever $VER -all
# 6. preprocessor/reference coverage, then the test suite
./gen_references.sh
uv run --with pytest --with pyyaml --with capstone python -m pytest tests/ -q
```

`-snapshot` and `-outputdir` are **required** on the snapshot and gamedata tools — there is no
implicit default, by design, so a run can never write to the wrong gamever.

**Current clean baseline** (measured 2026-09-10 — keep it). All three gamevers generate gamedata
with **0 warning diagnostics** and **0 errors**, and `validate_artifacts.py` reports **0 errors** on
all three:

| gamever | gamedata updates | artifacts | validator | vfunc indices RTTI-confirmed |
|---------|------------------|-----------|-----------|------------------------------|
| 14181   | 775 | 3751 | 0 errors, 25 warnings | 696 |
| 14180   | 767 | 3751 | 0 errors, 42 warnings | 694 |
| 14178b  | 778 | 3779 | 0 errors, 42 warnings | 703 |

Every remaining warning is `func_size` — either an advisory "does not end on padding" on tightly
packed GCC code, or an explicit `0x0` (unknown, see rule 14) — plus one `func_va` alignment
advisory on 14180. None of them reach a plugin. **A new error, or a warning of any other kind, is
a real defect.** `validate_artifacts.py` also takes `-module`, `-platform`, `-json`, `-quiet` and
`-pedantic` (the last promotes advisory size checks, so expect more of the same noise).

## AFTER AN UPSTREAM MERGE (the fork's own state is re-asserted, not merged)

`sync_upstream.sh` resolves every content conflict in **upstream's** favour (`-X theirs`, and
structural conflicts forced to upstream state). That means upstream's config overwrites this
fork's local decisions every time. Those decisions therefore live in code, as declarative tables in
`ensure_local_gamedata_symbols.py`, and are replayed after each merge:

| Table | What it re-asserts |
|-------|--------------------|
| `FORK_OWNED_SYMBOLS` | symbols upstream does not carry |
| `FORK_OWNED_TASKS` | the find-tasks that declare them (as `optional_output` — see rule 11) |
| `FORK_OWNED_OPTIONAL_TASKS` | upstream tasks downgraded to optional here |
| `FORK_OWNED_REMOVALS` | declarations this fork has deliberately retired |
| `FORK_OWNED_MOVES` | symbols that belong in a different module than upstream says |
| `FORK_OWNED_PLATFORM_PINS` | single-platform symbols (`platform:`) |
| `FORK_OWNED_OBSOLETE_TASKS` | tasks whose target no longer exists |
| `ALIAS_OVERRIDES` | downstream key renames |

The other three re-generators, also run from `sync_upstream.sh` or by hand:
`ensure_agent_fallback_skills.py` (agent finder skills; `-force` rewrites only AUTO-GENERATED
ones, never hand-written), `ensure_seed_preprocessors.py` (relocation preprocessors for every
symbol that has a baseline in the previous gamever), and `ensure_reference_base_tasks.py`
(`-config configs/<VER>.yaml` — creates the base find-task for reference targets upstream only
gave a `-decompiles` task, so their artifact can actually materialize).

**A local fix that is not in one of these tables will be silently lost on the next merge.** When
you change a config by hand, put the same change in the matching table.

## TAKING A NEW GAMEVER THROUGH

```bash
./add_gamever.sh <VER>                       # probes Steam for manifest IDs, pins them
uv run ensure_local_gamedata_symbols.py      # re-assert the fork's tables onto the new config
uv run ensure_seed_preprocessors.py          # free deterministic relocations from the last gamever
./run_linux.sh                               # then, separately, ./run_windows.sh  (rule 10)
# ... then the full VERIFICATION BATTERY above, and only then:
./deploy_local_plugins.sh && ./update_css_gamedata.sh
```

Order matters: everything cheap and deterministic runs before any agent or LLM work, so a symbol
that simply moved costs nothing.

## NEVER DO

### 1. NEVER run `fix_duplicate_symbols.py -all`
It removes cross-stage symbol declarations that upstream uses intentionally (module stages re-declare symbols for different processing passes). Only use `-config configs/<specific>.yaml` on configs with actual validation errors. The surgical approach (remove only the validator-named duplicates, keep alias-bearing entries) is the only safe method.

### 2. NEVER blanket-remove merge conflict markers without checking both sides
`<<<<<<< HEAD` / `=======` / `>>>>>>> theirs` blocks: check which side has the richer data (func_size, vtable_name, aliases) before choosing. In add/add conflicts on artifacts, HEAD (server-agent) usually has fuller analysis data. In config conflicts, theirs (injected tasks) may be correct. Always verify the result parses as valid YAML.

### 3. NEVER use `git add -A` on the server without checking what's untracked
Dot-commits (`commit -m "."`) have deleted tracked files (missing_report.py incident) and swept in unwanted files (log files, alias_candidates). The pre-commit guard catches skill-deletions but not everything. Always `git status --short` first.

### 4. NEVER trust a unique byte-pattern match as function identification without boundary verification
A sig can match exactly one address and still be the wrong function. Boundary checks (this rule);
semantic checks in rule 12. Always check:
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

### 11. NEVER use `expected_output` for a symbol you have not recovered on every gamever
`expected_output` makes the artifact **required**: pack aborts with "Missing required symbol YAML"
the moment one gamever lacks it. `optional_output` still declares the artifact — so the snapshot
packs it wherever it exists — without failing where it does not. Re-asserting fork-owned
`expected_output` tasks onto 14180/14178b killed pack outright until they were switched.

### 12. NEVER stop at the boundary check — confirm the function is the one you named
A clean boundary only proves you found *a* function head. Two real cases: `0x4ac3e0` was
labelled `ParseNetadrList` because it carried that function's string literals — GCC had inlined it
into `ConnectSocketToAddressList`; and `WalkMove`'s work turned out to be inline in `FullWalkMove`.
Confirm with a second, independent signal: the full string SET (not one string), the call graph, the
size, or a decompile. Size similarity alone is a red herring — it picked the wrong candidate for
`ParseNetadrList` while the string set picked the right one.

### 13. NEVER copy a `vfunc_index` across platforms, and never across classes without proof
Linux and Windows slot numbering differ (MSVC dtor pairs). Within one platform the same interface
has one layout per build, so a cross-module copy is fine — but verify it: `validate_artifacts.py`
resolves the class vtable via RTTI and checks the slot actually holds `func_va`. That check found
`CNetChan_ProcessMessages` copied with index 72 when 72 is `ParseMessagesDemo`.

### 14. NEVER write a `func_size` you cannot verify — `0x0` means "unknown" and is safer
Four different automatic measurements each failed differently: stopping at the first `ret`+padding
truncated a tail block reached only by a forward jump; requiring padding after the end flagged 25
correct sizes because GCC packs functions tightly; a fatal path may legitimately end on a `call` to
a noreturn helper; and taking the smallest validated candidate under-measured
`BuyState_OnUpdate.windows` as `0x1a0` where the real size is `0xf6c`. `func_size` is internal
metadata — only signatures and offsets reach plugins — so an unknown size costs nothing and a wrong
one is a live defect.

### 15. NEVER let two symbols claim one downstream key without deciding which wins
A symbol's own `name` and every entry in its `alias` list are downstream gamedata keys. When two
symbols claim the same key the later one silently wins: `ClientPrintToController` carries
`alias: [ClientPrint]` while a symbol named `ClientPrint` also exists, so the `ClientPrint` key
ships the controller variant. `alias` = the key written downstream; `source_alias` = which artifact
a symbol reads (and the validator rejects two symbols reading one artifact).

### 16. NEVER repair an artifact and stop there — the snapshot is what generation reads
`bin_artifacts/` is the source, `gamesymbols/<gamever>.yaml` is what `update_gamedata` consumes.
14178b's artifacts were clean while its packed snapshot still held a contaminated batch: eleven
Windows symbols sharing `func_va 0x1815575bc`, which made WeaponPaints ship ONE signature for five
different symbols. `audit_duplicate_va.py` missed it for the same reason — it read only the
artifacts. Re-pack after every artifact change, and remember the audit now reads the snapshot too.

### 17. NEVER edit a config by hand without re-reading it through `load_config`
Duplicate YAML mapping keys keep only the LAST value and warn about nothing. 14178b had 62 of them:
48 harmless `member:` repeats, and 14 `alias:` repeats that had stacked fourteen
`CServerSideClient::m_*` keys onto one unrelated symbol and thrown thirteen away. `load_config` now
refuses duplicate keys — do not work around it.

## ALWAYS DO

- **Re-pack snapshot after config changes** — the snapshot stores the config's `config_sha256`; a config edit without a re-pack makes it untrusted ("snapshot config digest mismatch")
- **Hydrate `bin/` from `bin_artifacts/` after every `git pull`** — `bin/` is untracked and doesn't auto-sync: `cp -ru bin_artifacts/<VER>/. bin/<VER>/`
- **Run `audit_duplicate_va.py` after every hunt round** — catches batch-contamination (same VA under multiple names, the 0x20c2700 incident)
- **Check `git check-ignore` before committing working files** — missing lists, logs, and alias candidates are now in .gitignore but weren't always
- **Use `git push` immediately after committing on server** — unpushed commits cause divergent branches that produce messy add/add conflicts later
- **Verify a find before you write it** — unique sig match plus boundary plus one semantic signal (string set, call graph, decompile). See rules 12 and 13
- **Leave `func_size: 0x0` when unsure** — unknown is safe, wrong is a defect
- **Commit inside plugin repos after `deploy_local_plugins.sh`** — deployed gamedata sits uncommitted in ~/customGIT/* until you commit and push to git.miksen.me

## TOOL QUICK-REFERENCE

| Tool | When | Notes |
|------|------|-------|
| `validate_artifacts.py` | After every artifact change | Re-checks every artifact against the binary; `-strict` fails on warnings |
| `gamesymbol_snapshot.py` | `pack` after changes, `check-contract` to verify | Pack is what generation reads, not `bin_artifacts/` |
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
- **LLM_DECOMPILE**: needs `CS2VIBE_LLM_APIKEY`. The default path is OpenAI-compatible
  `chat.completions` (`ida_llm_utils.call_llm_text`), so z.ai and similar providers work.
  The `/responses` endpoint is only used by the opt-in `fake_as="codex"` path
- Agent auto-select: if CS2VIBE_AGENT unset, scripts pick first installed CLI
