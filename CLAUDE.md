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
gamedata/<gamever>/<plugin>/    one dir per plugin, from gamedata-generators/<plugin>/ (15, 8 enabled)
        |  deploy_local_plugins.sh + update_css_gamedata.sh
        v
~/customGIT/*  and  ~/CounterStrikeSharp     (deploy_local_plugins.sh commits and pushes each repo)

One generator module per plugin lives in `gamedata-generators/<plugin>/`; it decides which keys
that plugin ships and in what format. Adding a plugin means adding a generator there, not touching
the snapshot.
```

`bin/<gamever>/` is an untracked working copy hydrated from `bin_artifacts/` — it is not a
pipeline stage, and it does not auto-sync after a `git pull`.

**Where a symbol comes from.** A config entry names a symbol; a `find-<Symbol>` task declares
that it should exist. Recovery is attempted in this order, cheapest first:
1. `ida_preprocessor_scripts/find-<task>.py` — one file per config **task** name. Two kinds:
   the majority are pure deterministic relocation from the previous gamever's baseline (free —
   no LLM, no agent), while 283 of them also declare an `LLM_DECOMPILE` list (462 specs total).
   Those specs are a **fallback**: they only fire when the deterministic part cannot resolve the
   symbol, and they need an API key (see AGENT SETUP). With no key the call fails soft and the
   symbol drops to step 3.
2. `auto_hunt_headless.py` — five strategies in pure Python (reloc, vtable, seed-sig, sibling,
   string-anchor); runs on the server with no IDA.
3. The IDA-side auto-hunt (Ctrl-Alt-H) and the agent-driven finder skills in `.claude/skills/`.
   The run does the first of these itself: when a preprocessor fails, `pipeline_hunt.py`
   runs Ctrl-Alt-H's hunter (`hunt_core` + `ida_backend`, same evidence rule, no UI) inside
   the run's own idalib session, and an agent is started only for what it cannot prove.
   Its artifacts go through the same finalize/validator as an agent's. It needs
   `baseline_facts/<prev>/<module>.<platform>.json` (gitignored) and builds it once from the
   previous gamever's warm IDB when missing (`CS2VIBE_PIPELINE_HUNT_FACTS=0` stops that;
   `CS2VIBE_PIPELINE_HUNT=0` turns the pass off). What neither the hunter nor the agent
   resolves lands in `manual_todo/<gamever>/<module>.<platform>.txt` with the hunter's best
   candidate and why it stopped; Ctrl-Alt-D pre-fills its list from that file, and an entry
   drops out as soon as its artifact exists. `CS2VIBE_AGENT=none` skips agents entirely:
   free work only, the rest goes to the list.
   Review by people without IDA: `review_issue.py publish -gamever <VER> -platform <p>` mirrors
   that list into one GitHub issue per gamever and platform on **origin** (each run publishes
   its own) (pinned explicitly - `gh`'s default in this
   checkout is the upstream remote); `review_issue.py apply -gamever <VER> -commit` reads
   `/confirm <Symbol> 0x<addr>` (or `vfunc <Class> <index>`, `gv 0x<insn>`) and
   `/reject` comments from collaborators only, rebuilds each confirmed artifact from the warm
   IDB with `emit_artifact.py`, and writes it only when `validate_artifacts` and the
   one-address-one-name check pass. It replies on the issue and reacts to each processed
   comment, which is also how a later apply skips it.
   Beyond relocation the hunter has three answers for what used to reach an agent:
   **sibling-callees** (template twins such as the `CCSCustomHudLayout_*ForPlayer` setters:
   the candidate calling the helpers a found sibling calls), **consts** (the function's
   struct offsets and immediates, a layout fingerprint that only votes for a clear unique
   winner, so twins tie and stay undecided - needs facts built after this change), and for
   a symbol with **no baseline** on windows, the same build's linux facts by string set
   (built once from the linux IDB). A symbol whose strings or callees now sit inside
   another function is reported `inlined into X` and costs no agent run.
   Two more, borrowed from K4ryuu's GameDataTracker (MIT): **data-ptr** (the function's
   address sat in a data table - a callback list, a factory's vtable - between known
   functions; two of them found again say where to read it, table-relative) and
   **callchain** (down from a known grand-caller through unnamed callers by call ordinal,
   when no direct caller is known). Both need facts built after this change.
   **Template classes resolve through RTTI now.** The binary spells
   `CGameSystemReallocatingFactory<X>` as `...I1XS0_E` / `?$...@VX@@V1@@@` (every
   argument, back-references), never `<len><name>`, so hunter, emitter and validator all
   missed it: `validate_artifacts` skipped 258 slots on 14190 (708 -> 966 verified) and
   CreateGameSystem/DestroyGameSystem went to an agent on every build. Names are matched by
   their identifiers (`hunt_core.itanium_tokens`/`msvc_tokens`), and `<...>` names also
   find the `_`-spelled vtable artifact.
   **Facts must be the previous gamever's.** `load_baseline_facts` takes the newest facts
   that exist, and they were built only when none did, so 14190 was hunted against 14185's
   server and 14181's engine/client facts. The run now asks for exactly the gamever it
   relocates from and builds them when they are missing or older.
4. Hand analysis, with `idat` (headless IDA, `/root/ida-pro-9.4/idat -A -S"<script>" -L"<log>" <binary>`;
   the IDB is `<binary>.i64`, e.g. `client.dll.i64`).

**What an artifact holds.** `func_sig` + `func_va` for a function; `gv_va` for a global (the data
address the RIP-relative operand points at, NOT the match address); `vfunc_index` +
`vfunc_offset` (= 8 × index) for a virtual; `offset` for a struct member. `func_size` is internal
metadata only — it never reaches a plugin. The filename is always `<Symbol>.<platform>.yaml` with
no role suffix.

## HOW A SYMBOL IS PRODUCED (upstream's task model — learn this before editing anything)

Three separate mistakes in one session came from guessing at these conventions
instead of reading upstream. The mechanism is declarative, and the declarations are
the only thing that survives a gamever bump.

**A task is named after its ANCHOR, not its outputs.** One task can emit several
symbols. `find-CBaseTrigger_vtable-decompiles` produces both
`CBaseTrigger_StartTouch` and `CBaseTrigger_EndTouch`, taking the base class's
anchored indices as input:

```yaml
- name: find-CBaseTrigger_vtable-decompiles
  expected_output:
    - CBaseTrigger_StartTouch.{platform}.yaml
    - CBaseTrigger_EndTouch.{platform}.yaml
  expected_input:
    - CBaseTrigger_vtable.{platform}.yaml
    - CBaseEntity_EndTouch.{platform}.yaml      # carries vfunc_sig -> the index
```

So `find-<Symbol>` not existing does NOT mean the symbol is unproduced. Search
`expected_output` for the artifact, never the task list for the name.

**`GENERATE_YAML_DESIRED_FIELDS` is the durability contract.** A task rewrites its
artifact with exactly the fields it lists. Editing an artifact by hand adds a field
that the next run silently drops — which is why a symbol can sit in the snapshot
for years carrying an index but no signature: no task ever asked for one. To add a
field permanently, add it to the producing task's list, then let the run regenerate
the artifact.

**Two shapes of task, and they are not interchangeable:**

| | real hunting task | bare declaration task (fork-owned) |
|---|---|---|
| name | `find-X-linux` | `find-X-linux` |
| platform | `platform: linux` key on the task | none |
| output path | `X.{platform}.yaml` (expanded at run time) | `X.linux.yaml` (literal) |
| preprocessor | required, filename == task name | none |
| purpose | find the symbol | stop pack dropping an artifact as undeclared |

A `{platform}` path in a declaration task is wrong: the name must state which
platform the artifact was produced for. One entry per platform.

**Discovery patterns, cheapest first** — a symbol usually needs only one:
- plain relocation: symbol in `TARGET_FUNCTION_NAMES`, previous gamever's
  `func_sig` locates it in the new binary. `find-ClientPrint.py` is nothing but this.
- `INHERIT_VFUNCS`: `(target, inherit_vtable_class, base_vfunc_name, generate_func_sig)`
  — take the slot index from one record, look it up in a class's vtable, generate the
  signature. The lever for a virtual whose address moves but whose slot does not.
  **The fourth element and the field list must agree.** Listing `"func_sig"` asks for
  the field; `generate_func_sig=True` is what produces it, and with the flag left
  `False` the field stays empty and the preprocessor fails. Audited on 14181: all 69
  specs are consistent (25 True / 44 False), so a `False` is a decision, not an
  oversight — and upstream writes the reason next to it, e.g.
  `CBaseEntity_GetChangeAccessorPathInfo_2` is a two-instruction this-adjusting thunk
  that cannot be uniquely signatured because `_1` is identical. **A record with an
  index and no signature may be impossible to signature, not merely neglected: read
  the comment before adding one.**

  The generated signature is also better than one built by hand. For
  `CBaseTrigger_StartTouch` the pipeline emits
  `... 48 83 EC ?? 48 8B 07 FF 90 ?? ?? ?? ?? 84 C0`, wildcarding the stack
  displacement and the vfunc offset inside `call [rax+0x870]`, where
  `enrich_vfunc_sigs.py` pinned both — a pattern that breaks as soon as the class
  layout moves the offset. Prefer re-running the producing task over enriching.
- `FUNC_XREFS`: string/xref anchored search.
- `LLM_DECOMPILE`: match a predecessor's decompiled shape; the fragile one, hence
  the agent fallbacks.

**`func_sig_allow_across_function_boundary:true`** belongs in the field list for any
function too short to signature on its own. Below ~0x30 bytes a body-only pattern
cannot be unique, and the generator then un-wildcards RIP-relative or branch
displacement bytes — which move on every rebuild. Crossing into padding and the next
head keeps them wildcarded. `find-CFlashbangProjectile_Spawn-decompiles.py` carries
the precedent and the explanation.

**Before naming anything, ask what the IDB already calls it.** The server IDBs carry
names for much of the server module: `ClientPrint`, `UTIL_ClientPrintFilter`,
`CCSPlayer_ItemServices_GiveNamedItem`, and the repo already files the neighbouring
overload as `CCSPlayer_ItemServices_GiveNamedItemBool`. Those names are NOT in the
shipped file - 14182's `libserver.so` exports only libstdc++ and third-party functions
(`readelf --dyn-syms`), so every game name in IDA was given by an earlier analysis.
Use them to keep one name per function, never as evidence that a find is right: a wrong
find that was renamed would confirm itself.
Two records under one name, or one name on two addresses, is the defect class that
cost the most time this session.

## WHEN TO CREATE A NEW PREPROCESSOR (and when not to)

A plugin key is not a reason to create a file. Four questions, in this order — the
first "yes" decides, and only the last one ends in a new `.py`.

1. **Is the symbol already produced?** Search `expected_output` across the config for
   the artifact name, never the task list for `find-<Symbol>`. One task emits several
   symbols and is named after its anchor, so `CCSPlayer_ItemServices_GiveNamedItem`
   comes from `find-CCSPlayer_ItemServices_GiveDefaultItems-decompiles`.
   → Yes: nothing to create.
2. **Is it the same function under another name?** Ask the binary what it calls the
   address, and look at the neighbours: `GiveNamedItem2` was
   `CCSPlayer_ItemServices_GiveNamedItem`, and the sibling overload one address along
   was already filed as `...GiveNamedItemBool`.
   → Yes: add an alias (`ALIAS_OVERRIDES` here, or the tracker's `symbol_aliases.json`
   for a key only it sees). Never a second record.
3. **Is the record there but missing a field?** A symbol can carry an index for years
   with no signature because no task ever asked for one.
   → Yes: add the field to the producing task's `GENERATE_YAML_DESIRED_FIELDS` — and
   for an `INHERIT_VFUNCS` target, set `generate_func_sig=True` in the same breath.
   Editing the artifact instead lasts until the next run (rule 18).
4. **Does the artifact exist but no task declares it?** Pack drops it as undeclared.
   → Yes: a bare declaration task per platform, WITH a preprocessor — 58 of this
   fork's 61 declaration tasks have one.

Only if all four are "no" does a new symbol need a `find-<task>.py`, and then it needs
a consumer and an anchor:

- **a consumer**: a generator/plugin key, or another task's `expected_input`. A symbol
  nothing reads is work with no payer — that is what retired `GameEventManager` and
  the four `g_CCSPlayerController_*Think` declarations.
- **an anchor**, cheapest first: a debug string (Pattern A/B), a known callee
  (`xref_funcs`), a base-class slot (`INHERIT_VFUNCS`), a ConCommand name (G), or a
  predecessor to decompile (`LLM_DECOMPILE`, C/D/E — the fragile one, hence the agent
  fallbacks).

And two cases that look like gaps and are not: a function **inlined** on one platform
has no artifact there by design (`optional_output`, with an `-inlined` sibling task
covering it — `CNetworkGameServer_IsMapValid` documents this in its own docstring),
and a two-instruction thunk **cannot** be uniquely signatured, so slot-only output is
correct rather than lazy.

## INVARIANTS ("iorden" means all of these hold)

- **Declared set comes from find-tasks, not from `symbols:`.** An artifact with no declaring task
  is dropped at pack time with "Ignoring undeclared symbol YAML". A task's `expected_output`
  makes it required (pack dies on a missing file); `optional_output` declares it without
  requiring it.
- **Snapshot digest matches the config.** The snapshot stores `config_sha256`, computed by
  `_normalized_contract` over module names, `path_*` and the **`skills:` (find-tasks) only** — NOT
  the `symbols:` lists. So a task edit without a re-pack is caught ("snapshot config digest
  mismatch"), while a symbol edit is NOT: check-contract still says trusted while generation reads
  a stale snapshot. Re-pack after every config change regardless of which half you touched.
- **`alias` vs `source_alias`.** `alias` = extra downstream gamedata keys this symbol writes;
  `source_alias` = alternative artifact filenames this symbol may read. Two symbols must not read
  one artifact — `gamedata_config_validation` rejects it as
  "<module>.<symbol>.source_alias: collision for <category>/<platform>" — and two symbols should
  not write one key (see rule 15).
- **`platform:` pins the lookup.** A symbol that only exists on one platform gets
  `platform: windows` (or `linux`). This is the only correct lever — it drives `_target_platforms`
  in `gamedata_symbol_data.py`, and `gen_references.sh` now expands only the pinned platform, so a
  pinned symbol stops being reported as a missing reference.
- **A task produces only for the binary that is open.** `platform:` on a task was the only filter,
  so a bare declaration task naming its platform in the *filename* instead
  (`find-CEntityResourceManifest_AddResource-windows`, whose one output is a literal
  `.windows.yaml`) was walked by the linux run too: preprocessed against `libserver.so`, failed,
  and — once optional outputs became huntable — nearly hunted. `outputs_target_other_platform()`
  now skips a task whose every expanded output names the other platform, printing
  `declares only non-linux outputs`. On 14182 that is 2 tasks in the linux run and 7 in the windows
  run. A task with no outputs is left alone, since that is a different kind of task rather than a
  mismatch. Note one task states its platform in neither place:
  `server/find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem` emits
  `.windows.yaml` while its sibling is `-linux`; the filter handles it, but the name should say so.
- **Names must line up exactly.** A preprocessor's filename equals the config **task** name; a
  skill's frontmatter `name:` equals its directory name (a mismatch means the skill never loads);
  an artifact's filename equals `<symbol>.<platform>`.
- **Config YAML has no duplicate mapping keys.** Enforced by `_StrictLoader` in `load_config`.
- **Every artifact is verifiable against its binary.** `validate_artifacts.py` re-reads the
  binary and checks the stored signature still matches at the stored VA, the match is unique, the
  boundary looks like a function head, `gv_va` equals the RIP target, `vfunc_offset` equals
  8 × index, and the class vtable (resolved via RTTI) really holds `func_va` in that slot.
  A struct member whose class and field the game's schema knows must also sit at the schema's
  offset (`schema_structmember_check`): that is what caught linux `CEntityIdentity::m_designerName`
  shipping the neighbouring EHandle's 0x10 on 14182/14184/14185, and windows `m_iTeamNum` at 0xaf0
  on every build.

## VERIFICATION BATTERY

Run in this order after any change. Anything but the stated result is a defect, not noise.

```bash
VER=14181
# 00. the binaries every check below reads must be the ones the lock names. bin/14171
#     held 14170's files and bin/14167 + bin/14168 files no manifest matched, and every
#     audit then judged the wrong build. Fix: download_depot.py -tag $VER, copy_depot_bin.py
uv run write_binary_lock.py -gamever $VER -check
# 0. ABI identity, BEFORE the pack: relocation propagates a wrong identification
#    faithfully and nothing downstream notices (rule 21). Every gamever, not just
#    the newest - a stale baseline poisons re-runs on the ones after it.
uv run abi_guard.py -gamever $VER --fix
# 0b. every anchored function still holds its finder's string / byte pattern
#     (a sig that outlived its function matches uniquely in ANOTHER one). 0 bad.
#     The run itself discards such a relocation (CS2VIBE_RELOC_XREF_CHECK=0 off).
uv run audit_xref_identity.py -gamever $VER
# 0c. every function artifact (anchored or not) against the previous gamever with
#     binaries: its strings must carry over. 0 drift. The run discards a drifting
#     relocation itself (CS2VIBE_RELOC_DRIFT_CHECK=0 off).
uv run audit_identity_drift.py -gamever $VER
# 0d. every virtual's slot against the previous gamever: a slot moves only with its
#     neighbours, by at most the vtable's change in length, or the same way on both
#     platforms. 0 shifted. validate_artifacts cannot see this - the vtable really
#     does hold func_va at a wrong index when it names the NEXT virtual
#     (vtidx_FinishMove.windows 39 for 38 on 14184, 14186-14188, shipped by
#     bot-controller). The run discards such a relocation (CS2VIBE_RELOC_SLOT_CHECK=0 off).
uv run audit_vtable_slots.py -gamever $VER
# 0e. every artifact against its task's GENERATE_YAML_DESIRED_FIELDS: names its own
#     symbol, same class as the previous gamever, no undeclared field, no declared
#     field dropped. 0 bad. A wrong record resolves cleanly in the binary, so nothing
#     above sees it - 14190 shipped CBaseEntity_OnTakeDamage.windows filed as
#     CBasePlayerPawn_OnTakeDamage, from an agent. The run strips undeclared fields
#     from hunter/agent output and rejects the rest (artifact_contract.py).
uv run audit_artifact_contract.py -gamever $VER
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
# 5b. the plugin files themselves: does every shipped entry still hold?
#     EVERY shipped file, not just CounterStrikeSharp - checking one of them is
#     how CS2Fixes went four gamevers without being verified at all. Skip the
#     disabled generators: their directories survive from older builds and their
#     data is stale on purpose, so cs2kz's own 4 unhealthy entries would fail a
#     run over data this fork does not ship.
DISABLED=$(uv run python -c "import publish_site_data as P; print(' '.join(sorted(P.disabled_plugins())))")
for f in $(find gamedata/$VER -type f \( -name '*.json' -o -name '*.jsonc' -o -name '*.txt' \) ! -name '*.metadata.json'); do
  echo " $DISABLED " | grep -q " $(echo "${f#gamedata/$VER/}" | cut -d/ -f1) " && continue
  uv run verify_plugin_gamedata.py -gamever $VER -gamedata "$f" | tail -2
done
# 5c. did the last generation actually reach the plugins? verify_plugin_gamedata
#     cannot answer this: a stale value that still resolves uniquely is healthy by
#     that test and says nothing about its own age.
uv run check_deploy_drift.py -gamever $VER      # exit 1 = a target is behind, and it names the keys
# 6. preprocessor/reference coverage, then the test suite
./gen_references.sh
uv run --with pytest --with pyyaml --with capstone python -m pytest tests/ -q
# 7. the published site datasets: does gamedata/history.json still match gamedata/?
uv run publish_site_data.py -check          # exit 10 = stale, and it names the drift
uv run publish_site_data.py                 # regenerate, then commit gamedata/history.json
```

Step 5c exists because generation and deployment are separate steps, run by separate scripts, and
nothing else in the battery compares them. `gamedata/14181/CounterStrikeSharp/...` carried
regenerated `CCSCustomHudLayout` win64 signatures for a whole generation while the install still
held the previous ones — both resolved to the same address uniquely, so `verify_plugin_gamedata.py`
called the install healthy, correctly, while the deployed pattern still pinned a relative call
displacement (`E8 6B 1B FF FF`) that the next build would move. Note the two compare modes, which
mirror the two deploy scripts: `deploy_local_plugins.sh` **copies**, so the file must match byte for
byte (bar a trailing newline); `update_css_gamedata.sh` **merges by key**, so install-only symbols
are kept on purpose and only generated keys are compared. `tests/test_deploy_targets.py` asserts
`DEPLOY_TARGETS` against both scripts, so adding a plugin to one without the other fails the suite
rather than silently dropping it from the check. `.gitignore` excludes `*.sh` but tracks, by
name, the pipeline's own entry points: `autopilot.sh`,
`deploy_local_plugins.sh`, `update_css_gamedata.sh`, `run_linux.sh`, `run_windows.sh`,
`gen_references.sh`. `autopilot.sh` runs it after every deploy —
running the scripts is not evidence the files moved.

Step 7 exists because `gamedata/` and the site's datasets are separate commits. The Pages build
reads `gamedata/history.json` and `diagnostics/<build>.json`, so changing a gamedata file without
re-running `publish_site_data.py` leaves the site showing the previous numbers with no error
anywhere. `deploy-pages.yml` now regenerates the history dataset during the build and a separate
`check-datasets` job fails the run when the committed one is stale — but CI catching it after a
push is the backstop, not the workflow.

`AUTOPILOT_NOTIFY_URL` needs one thing to actually deliver to Discord: a **User-Agent**. The same
payload reaches the webhook through `curl` (HTTP 204) and is refused through `urllib` with its
default agent (HTTP 403), so `autopilot_notify.sh` sets one explicitly. Worth remembering because
the failure is silent by design — a dead webhook must not fail a green run, so it only prints
`notification not delivered` to the journal.

A finished message carries the two things that otherwise cost an SSH session: **which keys moved**
(`publish_site_data.build_key_changes`: each generated file against the builds before it, the
rule the site's `keyChanges` counts, skipping disabled plugins). **Not** the `*.metadata.json`
companions: their "before" is the plugin's template, not the previous build, so they called every
key the template spells differently "changed" on every build — 14192 reported 13 files where 5
changed, and 14191's matchzy file, byte-identical to 14190's, listed 8. The Discord bot (`bot/`)
reads the same rule from `gamedata/history.json`. And
**links to the site** for the files and the file check. Assemble that body with `printf`, never a
quoted `"\n\n"`: inside double quotes those are two literal characters, and the first version
reached Discord showing them.

A `failed` message carries **what to run next**, not just which step broke: `hint_for()` maps the
failure text to the two or three commands that move it forward, with the gamever and the log path
already filled in — `./run_linux.sh <VER>` resumes rather than restarting, a verify failure points
at `grep -B20 "^unhealthy: [1-9]" .autopilot/verify-<VER>.log`, a dirty tree points at
`git status --short`. Every hint ends with `systemctl start cs2vibe-autopilot.service`, and an
unrecognised failure falls back to the journal. The point is that a notification which only names
the step still costs an SSH session to work out the command.

A run announces itself twice: `started` the moment a build passes the preflight, and then the
outcome with `took Xh Ym` on the first line. The start notice is there because a run takes hours -
without it the first sign of life is the finished message, and there is no way to tell "still
working" from "never started". `AUTOPILOT_NOTIFY_START=0` turns it off. It is sent after the disk
check and the dirty-tree check, so a message never promises a run that is about to be refused.

`autopilot.sh` runs step 5b as a **gate**, not a report: a build whose shipped files do not all
verify is never committed, pushed or deployed. That is what makes `AUTOPILOT_DEPLOY=verified`
defensible — it deploys whenever generation is clean, every artifact holds against the binaries,
there are no duplicate-VA clusters and every shipped entry re-scans with `unhealthy: 0`, even when
values changed. `safe` is stricter and holds anything that is more than a pure relocation; `auto`
ignores the gate entirely.

**Linux and windows pack and generate independently.** `gamesymbol_snapshot.py pack
-platform linux` requires every linux YAML and packs the windows ones that exist, reporting
the rest instead of failing; `update_gamedata.py -platform linux` accepts such a snapshot and
starts each output from the file already in `-outputdir`, so the windows values a windows run
wrote stay exactly as they were (measured: 167 windows values untouched, 44 linux updated).
Without `-platform` both tools keep the full requirement, and `check-contract` stays red
until both platforms are complete - which is what the battery and autopilot gate on. A
task whose `expected_input` belongs to another module that has not run yet is **deferred**
and retried after every module ran, instead of failing (engine's `CEngineServer_*` read
server's `IVEngineServer2_*`).

`-snapshot` and `-outputdir` are **required** on the snapshot and gamedata tools — there is no
implicit default, by design, so a run can never write to the wrong gamever.

**Current clean baseline** (re-measured 2026-10-14 on the newest build, which is the only one this
fork maintains - older gamevers are history, not repaired). 14190 generates gamedata with **0 warning
diagnostics** and **0 errors**, `validate_artifacts.py` reports **0 errors**, and every value of the
9 enabled plugins' files verifies on both platforms (`verify_plugin_gamedata.py -require-verified`):

| gamever | gamedata updates | artifacts | validator | vfunc indices RTTI-confirmed | shipped values verified |
|---------|------------------|-----------|-----------|------------------------------|-------------------------|
| 14190   | 313 | 3744 | 0 errors, 10 warnings (9 `func_size 0x0`, 1 padding advisory) | 966 | 308 / 308, 0 contradicted |

For comparison, the two builds before it measured 3744 artifacts / 966 slots / 0 errors with 10 (14189)
and 12 (14188) warnings. The update count is not comparable with the 480-ish of 14178b-14181: five
generators were disabled since, and bot-improver was removed on 2026-10-15 (the table that held those
numbers was a month old).

**`capstone` must be installed for these numbers to mean anything.** It is a declared
dependency now, but `validate_artifacts.py`, `verify_plugin_gamedata.py` and
`enrich_vfunc_sigs.py` all degrade SILENTLY without it (`capstone = None` / `_MD = None`)
rather than failing. With it missing, `ends_clean` cannot disassemble and falls back to
`end % 16 == 0`, which reported 22 correct sizes as suspect on 14181 and — worse — never
reached the swallow check behind them, hiding both three real over-measurements and a
genuine vtable-slot error on 14180. `uv run python -c "import capstone"` before trusting a
run that looks unusually quiet.

The counts move whenever symbols are added or retired, so re-measure rather than trusting a stale
table: the numbers above replace an earlier set (775/767/778 updates, 25/42/42 warnings) that was
two sessions old and made new advisories look like regressions. The update counts dropped by roughly 320 when five generators were disabled
(`MODULE_ENABLED = False` for swiftlys2, plugify, modsharp, cs2surf, cs2kz — 620 of 871 keys), so
they are no longer comparable with the 800-ish numbers above them. swiftlys2 was re-enabled on
2026-10-23 (14192: 525 updates, its two files verify with `-require-verified`); its templates follow
swiftlys2 master through two `# Seed source: <url> template=<path> output=<path>` lines, and its
`KEY_SYMBOL_OVERRIDES` (DropWeapon is the non-virtual HandleDropWeapon there, plus its own
spellings GetWeaponCSDataFromKey and C*Projectile::EmitGrenade) is read by the verifier, the template
sync and the metadata coverage as well. A key only one plugin uses belongs in that plugin's
`KEY_SYMBOL_OVERRIDES`, not in the shared `ALIAS_OVERRIDES`, so it can reach no other plugin's file.
On 2026-10-24 swiftlys2 went from 57 to all 199 of its keys produced here: 107 new fork-owned
records (CServerSideClientBase members and slots, CNetChan's INetChannel(Info) slots, the movement
functions) plus overrides onto records that existed under other names. The binary disagreed with the
author on 14192 for every linux INetChannel slot (linux has two dtor slots), the
SuppressTransmit pair on both platforms and GetAvgData - ours ships. The last three are slot-only
records read off a **call site** (`vfunc_sig`, no `func_va`), the answer for a slot whose function
cannot be signatured or lives in a module we do not analyse:
- `CServerSideClient_ProcessRespondCvarValue` (40/38): linux's override is `return 1`, windows folds
  it into a shared `mov al,1; ret`. Read where CServerSideClientBase binds message 25's handler -
  windows' only `jmp [rax+0x130]` vcall thunk, and on linux an Itanium member pointer, which is
  offset **+ 1** (`mov qword ptr [rbp-0x38], 0x141`); `vfunc_sig_calls_offset` accepts that form
  on ELF only.
- `CSoundSystem_TakeGuid` (77/78) sits in **server**, where EmitSoundFilter's guid helper calls
  `g_pSoundSystem` (SoundSystem001). The slot points into `soundsystem`, a fork-owned module that
  carries only `CSoundSystem_vtable` (like schemasystem), so the binary is downloaded and locked
  every build: linux slot 77 (`0x391ee0` on 14192) and windows slot 78 (`0x18005b290`) both bump
  a counter at `[this+0x3c]` and wrap it to 0, windows writing it through the out pointer.
  soundsystem carries its own `CSoundSystem_TakeGuid` too (task
  `find-CSoundSystem_TakeGuid-soundsystem`), found by the function's body and placed by RTTI,
  so `cross_platform_vfunc_check` compares the server call site's slot with the real one every
  build and errors when they part. A `FORK_OWNED_MODULES` symbol may name its task (4th
  element) when another module already uses `find-<Symbol>`, and an existing module block is
  completed with entries added to the table later. `emit_artifact.py` now takes its binary
  names from `auto_hunt_headless`, so it covers every module the validator does.
- **`download_depot.py` passes `-validate`.** DepotDownloader otherwise diffs the manifest against
  the one it stored last time, so a file the previous filelist never fetched stays whatever build
  it came from: `cs2_depot/` held a May soundsystem through 14192 (slot 77 there is a void flag
  setter), and `binary_locks/14192.json` never pinned schemasystem or filesystem_stdio.
- **`download_depot.py` prunes `cs2_depot/game/` to the filelist** after every successful download
  (`-no-prune` keeps it, `-prune-only` prunes without downloading). A file outside the filelist is
  never read and never fetched again, so it stayed for ever: one full download on 2026-05-03 left
  2.6 GB of community maps and shader packs, and 139 May binaries no module lists (544 MB). Kept:
  `game/csgo/steam.inf` (`bump_download.py` reads it) and everything outside `game/`
  (`.DepotDownloader/`).
- `INetChannelInfo::GetAvgPacketBytes` routes to `CNetChan_GetAvgData` (15). SwiftlyS2 has no
  GetPeakJitter, so its names from slot 14 on are one early: 14 is a running `maxss` of 0.1 ms
  frame-time samples feeding the jitter histogram, 15 is bytes/sec. Both keys ship 15.
- `CCSPlayerInventory_GetItemInLoadout` was upstream's plain `func`: the metadata called the key
  covered while the offset was the author's 9/8. `CATEGORY_DECISIONS` makes it a vfunc, its task
  asks for the slot (RTTI-confirmed 9/8). Coverage in `*.metadata.json` means "a record exists",
  not "the field this key needs exists" - `verify_plugin_gamedata`'s `upstream:` list is the test.
  Its one remaining entry, `CSource2Server::g_GameEventManager`, is a false alarm: the alias sits
  in the generator's own `config.yaml`, which the verifier does not read, and the shipped
  signature is `CSource2Server_Init`'s byte for byte.
bot-hider, bot-controller and CS2FOW were disabled the same day.
bot-controller (GetSlot, vtidx::DropWeapon), bot-hider (EndMatchState), cs2-retakes-allocator
(GiveNamedItem2) and CounterStrikeSharp (CBaseEntity_TakeDamage) moved there on 2026-10-23 with
byte-identical output. `gamedata_utils.generator_key_overrides` is the one reader; the seed
injector, the payer rule (`generator_consumed_names`), metadata coverage, the site's key index,
the verifier, the template sync and `audit_plugin_declarations` all go through it - miss one and
the seed injector, for one, invents a symbol for the moved key (it did, until it learned).
`tests/test_generator_key_overrides.py` fails if a key is both shared and plugin-owned. Re-enabling it surfaced `CCSPlayer_MovementServices_WaterMove.windows`
sitting on `CCSCustomHudLayout_SetDialogVariableStringForPlayer`'s address since 14182 - relocated
faithfully every build, and `audit_duplicate_va.py` calls a two-name cluster with one copied signature an
alias pair (and only audits linux unless given `-platform windows`). Artifacts and slots fell when
`CCSPlayer_MovementServices_Pawn` and `vtidx_DropWeapon` were retired (see FORK_OWNED_REMOVALS), and
14181 gained two when the `worldrenderer` module was added (3761 -> 3763; the warning count did not
move, and no gamedata update did either — nothing ships that key yet). Re-measure with the VERIFICATION BATTERY and
`validate_artifacts.py -gamever <VER> -json`, which prints `artifacts`, `slot_verified`, `errors`
and `warnings` in one object.

**Generation warns only about keys a plugin actually ships.** A `missing_yaml` (or
`structmember_yaml_missing`) for a symbol whose name and aliases appear in no ENABLED
generator's file is printed as `info` with "no enabled plugin ships this key", the same
payer rule pack and the run apply. Without it the autopilot gate failed 14183 (17),
14184 (24) and 14185 (23) on symbols only CS2Fixes/modsharp/cs2kz (disabled) or nobody
read, and nothing deployed after 14182. A missing key an enabled plugin ships is still
a warning and still blocks - that is the case where a plugin keeps its template text.

Every remaining warning is `func_size`. On 14181 all 19 are now the explicit `0x0`
(unknown, see rule 14). 14180 and 14178b add two "does not end on padding" advisories each
on tightly packed GCC code (`BuyState_OnUpdate.windows`, `CCSGameRules_SameMapTeardown.windows`),
and 14180 one `func_va` alignment advisory. None of them reach a plugin. **A new
error, or a warning of any other kind, is a real defect.**

The unknown counts went UP (12/25/20 -> 19/31/26) because `abi_guard.guess_func_size` stopped
guessing past a function boundary. It used to scan forward for the first `ret; int3; int3`,
which a function ending on a tail `jmp` does not have — so the scan ran through the functions
after it. It measured `NetworkStateChanged.linux` as `0xca5` where IDA says `0x55`, and
`CCSPlayer_MovementServices_FullWalkMove.linux` as `0xd23` against `0x170`. Those are the
warnings that turned into `0x0`: a larger unknown count here is the fix, not a regression.

`validate_artifacts.py` also takes `-module`, `-platform`, `-json`, `-quiet` and `-pedantic`
(the last promotes advisory size checks, so expect more of the same noise).

## THE FORK'S CONFIG TABLES

This fork no longer merges from upstream (`sync_upstream.sh` is left in place but unused).
Upstream's code is still the reference for the task model and its conventions; nothing of it
arrives any more.

A new gamever's config is a copy of the newest one (`run_linux.sh` scaffolds
`configs/<VER>.yaml` from it), so a hand edit carries forward. The fork's decisions are still
kept as declarative tables in `ensure_local_gamedata_symbols.py`, which `run_linux.sh` and
autopilot replay onto every new config. They are idempotent, and they are the one place that
says what this fork decided and why:

| Table | What it asserts |
|-------|-----------------|
| `FORK_OWNED_SYMBOLS` | symbols upstream never carried |
| `FORK_OWNED_TASKS` | the find-tasks that declare them (as `optional_output` — see rule 11) |
| `FORK_OWNED_OPTIONAL_TASKS` | upstream tasks downgraded to optional here |
| `FORK_OWNED_REMOVALS` | declarations this fork has deliberately retired |
| `FORK_OWNED_MOVES` | symbols that belong in a different module than upstream said |
| `FORK_OWNED_PLATFORM_PINS` | single-platform symbols (`platform:`) |
| `FORK_OWNED_OBSOLETE_TASKS` | tasks whose target no longer exists |
| `ALIAS_OVERRIDES` | downstream key renames |
| `FORK_OWNED_MODULES` | whole analysis modules upstream does not have |

When you change a config by hand, put the same change in the matching table, so the decision is
recorded and re-asserted rather than surviving only by being copied.

The other three re-generators, run by the run scripts or by hand:
`ensure_agent_fallback_skills.py` (agent finder skills; `-force` rewrites only AUTO-GENERATED
ones, never hand-written), `ensure_seed_preprocessors.py` (relocation preprocessors for every
symbol that has a baseline in the previous gamever), and `ensure_reference_base_tasks.py`
(`-config configs/<VER>.yaml` — creates the base find-task for reference targets that only
had a `-decompiles` task, so their artifact can actually materialize).

`FORK_OWNED_MODULES` is the odd one out: every other table patches a module upstream already has,
this one creates the module. It has to run FIRST, before `inject()` and the other enforcers, because
`inject()` resolves a symbol's module with `next(name == module)` and raises `StopIteration` on a
module the config does not contain — so a fork-owned symbol in a fork-owned module cannot be
declared at all until the block exists. The block is appended at the END of `modules:` (immediately
before the next top-level key, `cpp_tests:`), so the insert does not depend on the module order,
which carries staging meaning of its own.

Adding a module means **four** places, not one: the table here, plus `LIB_MODULE` so `module_for()`
routes the library to it, plus the two hand-maintained module→filename maps — `auto_hunt_headless.py`
(which `validate_artifacts.py` imports) and `verify_plugin_gamedata.py`'s own copy. Miss either map
and the artifact is simply never checked against its binary. `tests/test_fork_owned_modules.py`
asserts all four for every entry in the table.

Nothing else needs teaching: `copy_depot_bin.py` reads each module's `path_windows`/`path_linux`
straight out of the config (`run_linux.sh`/`run_windows.sh` already pass `-platform all-platform`,
which is the flat `cs2_depot/game/...` layout `download_depot.py` produces; only a by-hand call
without that flag looks for `cs2_depot/<platform>/game/...` and fails), `run_linux.sh` iterates
`bin/<VER>/*/`, and
`missing_report.py` picks the module up from the config too.

`worldrenderer` is the first entry: it carries `CWorldRendererMgr::CreateWorld_Internal`, the
function StripperCS2 hooks to rewrite a map's entity lump, and it is in none of upstream's nine
modules. Its preprocessor is **string-anchored, not relocation-only**, because a fork-owned symbol
has no baseline in any earlier gamever — a relocation preprocessor would fail on its first run and
on every re-run of that same gamever. The anchor is the function's own name, which it prints in its
bail-out path and which both binaries carry verbatim:
`CWorldRendererMgr::CreateWorld_Internal( %s ):  Blocking load because marked for deletion during
load`. That is also the rule-12 confirmation: linux `0x2b1180` loads it at `0x2b1622`, windows
`0x18002b1a0` at `0x18002b2ad` (a `4C 8D` lea — scanning only for `48 8D` finds nothing and looks
like a failed identification). `ensure_seed_preprocessors.py` leaves the file alone even under
`-force`, because a preprocessor without the AUTO-GENERATED marker counts as hand-written.

Its consumer is the `stripper` generator, and that one is deliberately **a reference file, not a
drop-in**: StripperCS2 reads no gamedata at all, both signatures are string literals in
`src/hook.cpp` behind an `#ifdef WIN32`, resolved with `KHook::LookupSignature`. So the emitted
`stripper.json` cannot be copied into the plugin — the value has to be pasted into `hook.cpp` and
the plugin rebuilt. Generating it is still what makes the symbol worth carrying: the value is
published with every build, so the site shows when it last moved and "Check my file" can tell
someone whether the literal their build carries is current. Which is the actual problem — the linux
literal in the plugin's own source is stale for 14181 (`48 83 EC ?` where the function now does
`48 81 EC ? ? ? ?`), so the hook would simply not be found. `convert_sig_to_css` is the right
converter for it: `KHook` wants space-separated hex with one `?` per wildcard, which is exactly the
`??` -> `?` that function does.

`tier0` is the second entry: it carries `CLoggingSystem::LogDirect`, the unexported funnel every
console line passes through, which CleanerCS2 hooks to drop lines by regex. Hooking the exported
`LoggingSystem_LogDirect` instead would miss most output: `Msg`/`Warning`/`ConMsg`/`DevMsg` format
first and call the internal function directly. The anchor is `Exiting due to logging LR_ABORT
request.`, referenced by that function alone on both platforms (14191: linux `0x20ca60`, windows
`0x180127e10`; the exported wrapper calls each). Unlike `stripper`, the `cleanercs2` generator's
file is **a drop-in**: the plugin (from v2.1) reads `addons/cleanercs2/gamedata.json` and falls back
to its compiled-in signature, and `deploy_local_plugins.sh` commits it to `package/gamedata.json`
in `~/customGIT/CleanerCS2` (mrc4tt/CleanerCS2), which xmake packs to that path. The generator has
no `# Seed source:` line on purpose - that file is our own output, so syncing from it is circular.

`multiaddonmanager` is like `stripper` in that the plugin reads no gamedata: MultiAddonManager
(mrc4tt fork) keeps three signatures and two offsets as `constexpr` literals in
`src/multiaddonmanager.cpp`. Unlike stripper it is deployed anyway: `deploy_local_plugins.sh` runs
`patch_mam_source.py`, which rewrites only those literals in `~/customGIT/MultiAddonManager` from
the generated file, then commits and pushes that one path; `check_deploy_drift.py` compares it in
`source` mode, literal by literal. An offset that differs per platform is refused (it is one
`constexpr int` for both), and fails the deploy. The plugin still has to be rebuilt for a new value
to reach a server. Its symbols are fork-owned:
`CHostStateMgr_StartNewRequest` and `CNetworkGameServerBase_ReplyConnection` (engine,
string-anchored), `ScriptGetAddon` (server, relocation only - no string of its own; the agent
anchor is the first call in the function printing `Saving existing workshop save file from %s`),
`CNetworkGameServer_ServerAddons` (engine struct member 0x178, read in ReplyConnection; in
`FORK_OWNED_STRUCTMEMBERS`, since `FORK_OWNED_SYMBOLS` has no struct/member slot) and the existing
`CNetworkGameServer_ClientList`. The 14192 baselines came from `emit_artifact.py`. The plugin's
linux ReplyConnection literal `55 B9 ? ? ? ? 41 B8` matched twice on 14192; the generated one is
unique.

## TAKING A NEW GAMEVER THROUGH

```bash
./add_gamever.sh <VER>                       # probes Steam for manifest IDs, pins them
uv run ensure_local_gamedata_symbols.py      # re-assert the fork's tables onto the new config
uv run ensure_seed_preprocessors.py          # free deterministic relocations from the last gamever
./run_linux.sh                               # then, separately, ./run_windows.sh  (rule 10)
# ... then the full VERIFICATION BATTERY above, and only then:
uv run write_binary_lock.py -gamever <VER>   # binary_locks/<VER>.json; autopilot does this itself
uv run schema_dump.py impact -old <PREV> -new <VER> -plugins <plugins dir>   # used schema fields that broke
./update_css_gamedata.sh && ./deploy_local_plugins.sh   # this order: the second commits the CSS repo
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
They share IDB locks and both clear `bin/<VER>/**/*.id0|id1|id2|nam|til` for the gamever they are
analysing, so running them together corrupts each other's databases. Ports are no longer the
problem: each entry point takes its own (`run_linux.sh` 13400, `run_windows.sh` 13401,
`gen_references.sh` 13402, all overridable with `CS2VIBE_MCP_PORT`), and the reap is scoped to that
port plus orphaned workers whose parent is gone. The interactive editor session keeps 13337, which
`.mcp.json` points at, and survives a run — it used to be killed by a blanket
`pkill -f 'idalib-mcp --unsafe'`, so every analysis cost the editor its IDA connection.

The session server runs as `systemd/cs2vibe-ida-session.service` (`ida_session.py`: the newest
`bin/<VER>/server/libserver.so` that has a `.i64`). `run_linux.sh`, `run_windows.sh` and
`gen_references.sh` stop it while they run and start it on exit, so it never holds a database a
run needs and always follows the newest analysed build. By hand, when the unit is not installed:

```bash
uv run python cs2vibe_ida_mcp.py --unsafe --host 127.0.0.1 --port 13337 bin/<VER>/server/libserver.so
```

One server holds several binaries - one Nexus worker each, opened with `open_database` - so
Windows work no longer needs a second instance.

**The MCP server is Hex-Rays' `ida-mcp` (IDA 9.4+, IDA Nexus), carrying the fork's tools.**
`cs2vibe_ida_mcp.py` serves Hex-Rays' six tools (`open_database`, `execute_python`, `reference`,
`list_databases`, `save_database`, `close_database`) and lists every tool of the
`mrc4tt/ida-pro-mcp` fork beside them, each run inside the Nexus worker through the fork's own
dispatcher - so `py_eval`, `find_bytes`, `decompile` ... answer exactly as idalib-mcp did and
neither the pipeline nor the skills changed. Three differences, all deliberate: the port opens
only once the database is open and analysed (the readiness signal the launchers wait for);
SIGTERM is where the database is saved, so `stop_idalib_mcp_process` waits
`CS2VIBE_IDA_STOP_TIMEOUT` (300 s) instead of 10; and nothing is truncated - the fork cut any
result over 50 000 characters to a preview plus a download URL nothing here ever fetched.
`CS2VIBE_IDA_MCP=fork` starts the old `idalib-mcp` instead, same arguments, for a rollback
without a code change. The reap patterns in the run scripts match both servers and both kinds of
worker (`ida_pro_mcp.idalib_server`, `ida-nexus worker`). IDA 9.1 and its IDB backup were removed
on 2026-10-20; 9.4 is the only install (`~/ida-pro-9.4`).

**Within one run, binaries go side by side** (`-jobs` / `CS2VIBE_JOBS`, which the run
scripts default to `auto`). IDA is single-threaded per database, so the only way to use
more cores is more databases: the parent starts one `ida_analyze_bin.py` child per
(module, platform), heaviest first so server starts at once, each with its own idalib and
dynamic port, and prefixes its output `[server/linux]`. Every stage of one module stays in
that one child, in config order, because the stages share an IDB. `auto` =
min(cores, RAM / 6 GiB, binaries). A task whose input another binary has not produced yet
is deferred as before; the parent runs the deferred ones after every child exits, ready
ones first and again until no progress, so a chain of deferrals resolves.
Agents are capped separately, across all children, by `CS2VIBE_AGENT_JOBS` (default 3,
flock'd slot files): they wait on the API, not a core, and the plan's rate limit is the
real bound. `-vcall_finder`, `-force_all`, `-selected_execution` and the redis reporter
stay sequential. `CS2VIBE_JOBS=1` is the old behaviour.

A failed idalib start no longer costs 1200 s blind: output goes to
`<binary>.idalib-mcp.log`, the wait ends as soon as the process exits, an existing IDB
gets 300 s, and one retry follows (14185's engine open stalled 20 min, then opened in 2 s).

The aux-file cleanup no longer touches a live database either. `.id0/.id1/.id2/.nam/.til` are what
an OPEN database works in and `.i64` is the packed form written on close, so a set with no owner is
the wreckage of an interrupted run while a set with an owner is somebody's working database. The
run scripts therefore delete only the unowned ones, deciding by which binary a live idalib process
holds (read from `/proc/<pid>/fd`, not per file — a live database keeps `.id0` open but not always
`.til`, so a per-file test deletes the wrong things). Measured: 5 stale files removed, 5 belonging
to the open session kept, and the session decompiled normally afterwards.

The overlap that used to remain - a session holding `libserver.so` made that module of a run fail
with "only <other>.so is open" - is gone for the systemd unit, which the run scripts pause. A
server started by hand on 13337 is still only warned about, not stopped.

### 11. NEVER use `expected_output` for a symbol you have not recovered on every gamever
`expected_output` makes the artifact **required**: pack aborts with "Missing required symbol YAML"
the moment one gamever lacks it. `optional_output` still declares the artifact — so the snapshot
packs it wherever it exists — without failing where it does not. Re-asserting fork-owned
`expected_output` tasks onto 14180/14178b killed pack outright until they were switched.

That declaration used to also disable recovery. A task whose outputs are **all** optional was
skipped outright when its preprocessor failed — "falling back to AGENT SKILL" was printed and then
`Skipping skill: <name> (optional outputs not generated)`, so a symbol that had merely moved
dropped out of the snapshot with no error anywhere. On 14182 that silently lost
`IGameResourceService_SetEntityResourceManifestHandler`, `g_pGameEntitySystem` and
`INetworkSystem_PollSocket`, all three of which 14181 carries on both platforms.
`optional_outputs_with_baseline()` now tells the two cases apart by the previous gamever's
artifacts: a baseline-backed output is hunted (and validated like a required one, so the agent
retries instead of reporting success over a missing file), while a genuinely inlined symbol has no
baseline either and still skips. The filter is per platform, because a task with a literal
`<Symbol>.windows.yaml` output and no `platform:` key runs in the linux run too and only the open
binary can be hunted.

`artifact_has_consumer()` is the second gate, and it is the payer rule in code: a hunt costs up to
three agent attempts, so a baseline-backed symbol is only paid for when a generator's shipped file
names it as a key (in the plugin's own `CClass::Method` spelling, resolved through the symbol's
`alias` list) or another task takes it as `expected_input`. Measured on 14182:
`INetworkSystem_PollSocket` is read by `networksystem/find-CNetworkSystem_PollSocket` and
`CEntityResourceManifest_AddResource` ships in CounterStrikeSharp and swiftlys2, so both are hunted;
`IGameResourceService_SetEntityResourceManifestHandler` and `g_pGameEntitySystem` reach the snapshot
and stop there, so they are skipped with the reason printed. Beware the near-miss that makes
`g_pGameEntitySystem` look consumed: CounterStrikeSharp ships a `GameEntitySystem` key, but it
carries `offsets` (88/80) for a member of another class, not this global's address.

**A required output nothing reads is not paid for.** A reader is an enabled plugin's key
(`generator_consumed_names`; `MODULE_ENABLED = False` removes a plugin's keys), another task's
`expected_input`/`optional_input` (or a `_linux`/`_windows` one) **in the module it reads from** - the
runner resolves an input under the reader's own module, and a `../client/X` entry names its module,
so server's copy of a symbol only client's tasks read is unread (47 artifacts on 14192, among them
the `CGameSystemReallocatingFactory_*` copies an agent hunted on windows every build) - or a **cpp test**: `cpp_tests` compare each class's SDK header
with every `<Class>_*` record (and its `alias_symbols`) for the hl2sdk ABI check
(`cpp_test_class_prefixes`), which is why `IGameSystem_OnRestoreGame` is read although no plugin
ships it. The test list is **`cpp_tests/fork_tests.yaml`** alone: `sdk_abi_check.sh` runs it,
`ensure_local_gamedata_symbols.py` copies it over every config's `cpp_tests:` block, and the
payer rule reads it directly. Add a test there, never in a config (the config block had fallen to
16 of the check's 50 tests). `run_cpp_tests.py` generates the gitignored `cpp_tests/protos` itself
when a test needs it, but it fails on every accepted mismatch: compare against
`cpp_tests/abi_baseline.txt` with `sdk_abi_check.sh`. The client tests (`CNetworkGameClient*`,
`IVEngineClient2`) read `Wend4r_sourcesdk/`, a shallow submodule of Wend4r/sourcesdk `main`, since
hl2sdk carries no client interfaces. It is read-only (no fork, never patched) and stays on its pin
until bumped by hand; its headers disagree with 14192 in 53 places (unkNNN slots, a windows table 2
short), all in the baseline, so the tests catch change, not correctness. A required output with no reader gets the free preprocessor only: the run skips the
hunter and the agent (`no reader (plugin, task input or cpp test)`), and pack does not insist on
it (`artifact_unpaid`, `gamesymbol_snapshot_lib.operations._waived`) but packs it wherever it
exists. On 14192 that is 1609 of 3921 required outputs; over opencode's ledger up to 2026-10-25,
294 of 609 agent runs ($68 of $141 at the API list price) went to such outputs. Until then only
outputs read solely by disabled plugins were waived and the rest stayed required as upstream's
declaration - the fork no longer syncs upstream, so it decides. `CS2VIBE_HUNT_UNREAD=1` restores
that rule. A symbol that gains a reader is hunted again on the next run; re-enabling a plugin
does the same for its keys.

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

### 18. NEVER fix an artifact by editing the artifact
The task that produces it rewrites it from `GENERATE_YAML_DESIRED_FIELDS` on the
next run, so a hand-added field lasts exactly until the next gamever. Four
signatures added by hand this session would have vanished that way. Add the field to
the producing task instead — and find that task by searching `expected_output` for
the artifact name, since tasks are named after their anchor, not their outputs.

### 19. NEVER invent a symbol name to satisfy a report
`CBaseTrigger_EndTouchInternal` was invented to give a tracker something to compare
against, and it was wrong three ways: upstream tracks no such symbol, no generator
consumes it, and the body it named is reached from two different wrappers so it was
not specific to that class at all. If a downstream key and an analysis record
disagree, the answer is an alias, a decision about which is correct, or an honest
advisory — never a new name that makes the red go away.

### 20. NEVER read a plugin file as evidence that the pipeline produced it
A generator writes a key only when the snapshot has the field it needs; otherwise the template's
value stays and the run reports nothing. Both of 14181's shipped defects were frozen template text
that looked like output:

- `bot-controller`'s `vtidx::DropWeapon` shipped `windows 24 / linux 25` on 14180 and 14181 while
  RTTI says 28/29. `vtidx_DropWeapon` was a second record for a function already filed as
  `CCSPlayer_WeaponServices_DropWeapon` (identical `func_va` on both platforms), and once its own
  artifacts lost `vfunc_index` the key fell back to the template.
- `bot-hider`'s `CNetworkGameServer::PackEntities` shipped a 14178b signature that resolved to
  `0x568d00` when the function is at `0x567d20` — a different function, hooked for two gamevers.
  Cause: the file says `"library": "engine2"`, the analysis module is `engine`, and the generator
  compares the two, so every run skipped it as "no matching YAML data".

`verify_plugin_gamedata.py` called both healthy, correctly: a unique match with a clean boundary is
all it claims (rule 12 again). To tell output from template, run `update_gamedata.py -debug` and
read the per-module "Skipped Symbols" list — a skipped key means the plugin keeps whatever it had.

The third key on that list is now fixed too. `CCSPlayer_MovementServices::Pawn` had no producer at
all, so bot-controller and bot-improver kept the plugins' own 56. It is a real field, and the class
proves it itself: slot 26 (`PlayerRunCommand`) calls an accessor that reads the member directly —
linux `0x179b460` `mov rax,[rdi+0x38]`, windows `0x180c36380` `mov rax,[rcx+0x38]`, each followed by
a CHandle load at a *different* offset per platform (0xE90 vs 0xBB0), which is what one field looks
like through two compilers. Declared as a `structmember` with an `offset_sig` anchored on that
instruction, so 56 is re-derived and checked every build instead of trusted. With `ida-pro-mcp`
refusing connections, the decompilation was done headlessly:
`~/ida-pro-9.4/idat -A -S<script> -L<log> bin/<VER>/server/libserver.so.i64` — note that a stale
minidump in `/tmp/ida` makes `idat` block on a dialog even under `-A`, so clear it first.

**The verifier had two blind spots of its own**, both found by pointing it at a file
the battery never checked. `cs2fixes.jsonc` reported `unhealthy: 4`, and all four were
the tool's fault:

- `CNetworkGameServer_ClientList` was called a mismatch, 73 against an analysed 584.
  CS2Fixes indexes that struct by element rather than by byte and its generator says so
  in `STRUCT_MEMBER_OFFSET_DIVISOR`; 584 / 8 = 73 is correct. `check_offset` now reads
  the divisor tables out of the generators and reports `match` with `scaled_by`.
- Two patches were called `broken`. The kind-word hint was only looked for in the path
  segments *below* the entry name, which finds CSS's `Key > signatures > linux` and
  misses CS2Fixes' `Patches > Key > linux` - so patch payloads were scanned as
  signatures. A patch value is what the plugin *writes*, not where, so its bytes are not
  supposed to occur in the binary at all: the status is now `patch-unverifiable`.

All seven shipped files are `unhealthy: 0` after that. A status of `ok-midfunction` or
`ok-globalref` is a pass with a qualification, `no-reference` and `patch-unverifiable`
mean the entry could not be checked, and only `broken`, `ambiguous`, `mismatch` and
`unparsable` are defects - `_report` is the authority.

And the reason a field disappears in the first place: `ensure_seed_preprocessors.py` used to take
`GENERATE_YAML_DESIRED_FIELDS` from whatever the baseline artifact happened to carry. One run that
fails to resolve a vtable writes an artifact without `vfunc_index`, the next regeneration stops
asking for it, and it can never come back. `CATEGORY_REQUIRED_FIELDS` now floors each category with
the fields that define it, so a vfunc always asks for `vtable_name`/`vfunc_offset`/`vfunc_index`.

### 21. NEVER re-run a task without checking that the PREVIOUS gamever's artifact is right
Relocation takes the previous gamever's `func_sig` as ground truth. A baseline naming the
wrong function is reproduced faithfully on the new build — unique match, clean boundary,
nothing complains — so a re-run can be a regression, not a repair. Measured: re-running
`find-CCSPlayer_MovementServices_ProcessMovement` on 14180 replaced the correct
`0x180aa2260` (vtable slot 28) with `0x180c22cb0`, which is in no slot at all, purely
because 14178b's artifact still held it. `find-NetworkStateChanged` and
`find-CCSPlayer_MovementServices_FullWalkMove` regressed the same way.

`abi_guard.py` is the answer to this and it is not optional: run
`uv run abi_guard.py -gamever <VER> --fix` after every run and **before**
`gamesymbol_snapshot.py pack`, on **every** gamever. 14178b had never been through it,
which is precisely why it was still poisoning re-runs on 14180.

Two guards now catch the class before the baseline does:
- a relocation whose address is not an entry of the class's vtable is discarded, so
  `FUNC_VTABLE_RELATIONS` finally constrains the path that actually resolves the symbol
  rather than only the `func_xrefs` fallback beneath it. This only works for symbols that
  declare the relation — `find-NetworkStateChanged` and
  `find-CCSPlayer_MovementServices_FullWalkMove` declare none, so they still depend on the
  guard table. A slot-only record (`vfunc_sig`, no `func_va`) is judged by its **slot**:
  judged as an address it was always "at None - not an entry", so ~150 tasks (300 slot-only
  artifacts on 14192) threw away their free call-site relocation and paid LLM_DECOMPILE
  every build (fixed 2026-10-25).
- `abi_guard.check_symbol` verifies `func_size` as well, which is how four over-measurements
  surfaced that `validate_artifacts` had missed (its swallow check needs a recognisable
  prologue with no branch into it).

## ALWAYS DO

- **Re-pack snapshot after config changes** — and do not rely on check-contract to catch a stale one: the digest covers the find-tasks, not the `symbols:` lists
- **Hydrate `bin/` from `bin_artifacts/` after every `git pull`** — `bin/` is untracked and doesn't auto-sync: `cp -ru bin_artifacts/<VER>/. bin/<VER>/`
- **Run `audit_duplicate_va.py` after every hunt round** — catches batch-contamination (same VA under multiple names, the 0x20c2700 incident)
- **Check `git check-ignore` before committing working files** — missing lists, logs, and alias candidates are now in .gitignore but weren't always
- **Use `git push` immediately after committing on server** — unpushed commits cause divergent branches that produce messy add/add conflicts later
- **Check how the existing tasks do it before writing a task, a preprocessor or a name** — grep `configs/<ver>.yaml` and `ida_preprocessor_scripts/` for a task that already emits the field combination you want. Task names carry the platform they were made for (`-linux` / `-windows`), and a fallback skill only loads when its name equals the task name — so let `ensure_agent_fallback_skills.py` generate them
- **Verify a find before you write it** — unique sig match plus boundary plus one semantic signal (string set, call graph, decompile). See rules 12 and 13
- **Leave `func_size: 0x0` when unsure** — unknown is safe, wrong is a defect
- **Never pin a relative branch target or a RIP-relative displacement in a shipped sig** — those bytes move on every rebuild; `enrich_vfunc_sigs.py` wildcards them, and you must re-run `validate_artifacts.py` after it and drop any sig that then matches more than one place
- **Check the plugin repos were pushed after `deploy_local_plugins.sh`** — it now commits and pushes the generated file in weaponpaints, matchzy and CounterStrikeSharp itself (that path only, rebasing once with `--autostash` when the remote moved) and exits 1 naming any repo it could not push. `check_deploy_drift.py` reads working copies, so it cannot see a commit that never left the server

## TOOL QUICK-REFERENCE

| Tool | When | Notes |
|------|------|-------|
| `abi_guard.py` | After every run, before every pack | Catches a wrong *identification* that relocated cleanly; `--fix` rewrites the artifact. Also verifies `func_size` |
| `audit_xref_identity.py` | After every run, before pack | Each anchored function must still reference its finder's string / byte pattern (or, for an `m_*` anchor, access the schema offset). The run applies the same judgement to every relocation and discards a `bad` one |
| `audit_vtable_slots.py` | After every run, before pack | Every virtual's `vfunc_index` against the previous gamever. SHIFTED = moved unlike its neighbours / the vtable's length / the other platform; decide which build is wrong by the other platform (most vtables: linux = windows + 1). Still flags, on old builds nothing ships from: 14183 windows `OnTakeDamage_Dead`/`_Dying` swapped, 14182-14183 linux `CEntityInstance_GetDataDescMap` on `ReloadPrivateScripts`' slot, `CNetworkGameServerBase_CheckPassword.linux` / `CBaseTrigger_PassesTriggerFilters.linux` from 14182 |
| `audit_identity_drift.py` | After every run, before pack | Every function artifact against the previous gamever: strings must carry over. DRIFT names the function that now holds them. Recognises outlining (the new body calls the holder). The run discards a drifting relocation |
| `audit_artifact_contract.py` | After every run, before pack | Every artifact against its task's declared fields and the previous gamever's name/class. The run applies the same rule to hunter and agent output: undeclared fields are stripped, a wrong name/class or a dropped field is rejected (the agent is told why and retries; a final failure's files are removed, not packed). Fix a finding by re-running its task, never by editing |
| `validate_artifacts.py` | After every artifact change | Re-checks every artifact against the binary; `-strict` fails on warnings. Needs `capstone` — degrades silently without it |
| `verify_plugin_gamedata.py` | Before a deploy, and to answer "is this plugin's file OK" (`-require-verified`: every value must be re-read from the binary by a method of its own - func, sig, rtti, callsite, inherit, insn+anchor, xplat, schema, gv, binary - while width, unique, align and an anchored other platform can contradict it; "match" alone is circular) | Scans every shipped signature against the binaries and re-derives every offset; a CSS `"vtable"` slot must hold the signature's function in the class's *primary* vtable (the only one CSS reads); non-zero exit on broken/ambiguous/mismatch |
| `audit_arg_fingerprint.py` / `audit_plugin_declarations.py` / `audit_shape_drift.py` | autopilot runs all three after the gate, reported in the notification, never blocking | Crash classes no address check sees. Fingerprint: a shipped function's argument registers changed since the previous build. Declarations: a plugin's C# binding passes fewer arguments than the function reads (found CSS's `RemoveWeapons` missing its armor flag). Shape: most of a function's named callees, strings or constants did not survive (layout shifts of big struct offsets are tolerated, size only supports). All three read 0 on neighbouring builds |
| `sync_plugin_templates.py` / `template_refresh.py` | autopilot: before every generation, and on idle ticks at most every 6 h | Follows each generator's `# Seed source:` (the plugin's own gamedata file): added/removed keys reach the template, a key the plugin author's value disagrees with ours is reported with where each lands (found bot-hider's m_UserIDString/m_bIsHLTV misreads, and two plugin-side errors), an alias is suggested when a new key's signature lands on one of our functions. A key with no record here ships the author's value as `upstream` - reported, not a gate failure. Between builds the idle tick regenerates the newest build, gates it with `-require-verified` and commits, or rolls back |
| `auto_repair.py` | When the verified gate fails (autopilot runs it; `AUTOPILOT_AUTO_REPAIR=0` off) | Rebuilds a contradicted struct offset with `emit_artifact.py` only on independent evidence: the other platform's anchored function holds its value, or another instruction in the same `offset_sig` touches the whole field AND equals the other platform. Then pack, generate, verify. Plan only without `-apply`. Repaired 14190's five `CServerSideClient` misreads unaided, identical to the hand fix |
| `check_deploy_drift.py` | After every deploy | Diffs `gamedata/<VER>/<plugin>/` against the deployed file; catches a generation that never left the repo, which no entry-level check can see |
| `update_hl2sdk_submodules.sh` | autopilot, before `sdk_abi_check.sh`; by hand after a fork push | Moves every repo's `mrc4tt/hl2sdk` gitlink to the branch head `.gitmodules` names, fast-forward only, and commits that path alone. Autopilot bumps this repo (the build's push carries it) and only `--check`s CounterStrikeSharp, reporting `hl2sdk-behind` to the admin channel - a new SDK there needs a build. `_work/` runner checkouts are skipped |
| `agent_cost.py` | autopilot after the analysis (`.autopilot/agent-cost-<VER>-<epoch>.json` + the journal); by hand `-since "<time>"` | Agent hunts from opencode's ledger: billed cost, and the same tokens at z.ai's API list price (`LIST_PRICES`), per model and per skill - the most expensive skills are the next candidates for a deterministic preprocessor. `-recurring` (autopilot, every run) writes `.autopilot/needs-preprocessor.txt`: skills paid for in 2+ of the last 5 builds, whose free path fails every build - the work list for a stronger anchor. Not counted: LLM_DECOMPILE, claude, codex |
| `gamesymbol_snapshot.py` | `pack` after changes, `check-contract` to verify | Pack is what generation reads, not `bin_artifacts/` |
| `missing_report.py` | After runs / before hunts | Writes `missing_<plat>_<ver>.txt` |
| `audit_duplicate_va.py` | After every hunt round | 0 suspect clusters = clean |
| `detect_aliases.py` | After snapshot pack | Catches renames (JoinTeam pattern) |
| `gen_references.sh` | After analysis complete | Resume-safe, auto-reap port 13337 |
| `add_gamever.sh` | New gamever release | Probes Steam for manifest IDs |
| `fix_duplicate_symbols.py` | Only on configs with validator errors | NEVER use `-all` |
| `enrich_vfunc_sigs.py` | After analysis | Adds func_sig to vfunc artifacts offline |
| `deploy_local_plugins.sh` | After gamedata generation, after `update_css_gamedata.sh` | → ~/customGIT/weaponpaints + matchzy, then commits and pushes those two and ~/CounterStrikeSharp |
| `schema_dump.py` | New gamever, or "what is offset X on class Y" | Schema (classes/fields/offsets) read statically from libserver.so/server.dll, no server. `diff` flags a field gone + a field added at one offset with one size as *likely renamed* (classes too). `impact -old <PREV> -new <VER> [-plugins DIR]... [-json]`: which fields CounterStrikeSharp's generated `SchemaMember`s and each plugin .dll (ECMA-335 MemberRefs + `ldstr` class/field pairs, `schema_impact.py`) use are removed/renamed/moved; exit 1 on removed or renamed. Moves are harmless (CSSharp resolves offsets by name at runtime). Also flags a base-class field named on a derived class, which CSSharp's lookup silently resolves to 0 |
| `update_css_gamedata.sh` | After gamedata generation | → ~/CounterStrikeSharp install |

## IDA PLUGIN HOTKEYS (local PC)

| Hotkey | Tool | Strategy |
|--------|------|----------|
| Ctrl-Alt-H | auto-hunt v2 | 5 strategies: reloc, vtable, seed-sig, sibling, string-anchor |
| Ctrl-Alt-J | hunt named symbols | Asks for names (comma separated); hunts only those, even if an artifact exists |
| Ctrl-Alt-E | emit artifact here | Artifact for the address under the cursor (also `emit_artifact.py` CLI) |
| Ctrl-Alt-D | sig maker batch | List of symbols, pre-filled from `manual_todo/` or else from `missing_<platform>_<gamever>.txt` (open module only, existing artifacts skipped): hunted automatically first (Ctrl-Alt-H's engine and evidence rule); the rest is written to `manual_todo/<gamever>/<module>.<platform>.txt` with every candidate and the reason (Ctrl-Alt-R opens it as a review window). The cursor is never read, and every write refuses CRT start-up code and an address another artifact already owns |
| Ctrl-Alt-V | vtable finder | Interactive: class + slot + symbol |
| Ctrl-Alt-R | review list | `manual_todo/<gamever>/<module>.<platform>.txt` (written by Ctrl-Alt-D and by the run) as a review window: Enter looks, Ins writes that candidate |
| Ctrl-Alt-O | struct member emitter | Cursor on member-access instruction |

## AGENT SETUP

- **Local PC**: `CS2VIBE_AGENT=claude` (Max 5x, Sonnet default)
- **Server**: `CS2VIBE_AGENT=opencode,opencode@zai/glm-5.3,claude` with
  `CS2VIBE_AGENT_MODEL=zai/glm-5.3-flash` (z.ai pay-per-token API since 2026-10-25, not the coding plan;
  opencode cost per session is in `session.cost` of `~/.local/share/opencode/opencode.db`): flash first, glm-5.3 only
  after flash used its attempts. A chain entry `agent@model` pins its own model (`agent_runner._split_agent_model`)
- **Agent token economy** (an agent re-reads its whole context on every step, ~30 steps a hunt, so
  a fixed prompt cost is paid ~30 times; measured 2026-10-25 on opencode, per step):
  - skill list: `.opencode/skill_runner.config.json` lets the skill tool list only the helper skills
    (`write-*`/`generate-*`/`get-*`). All ~1450 `find-*` skills cost ~245k tokens a step (252k -> 8k);
    the agent reads its own `find-*` SKILL.md by the path in its prompt.
  - IDA tools: `.opencode/agents/sig-finder.md` allows the 32 ida-pro-mcp tools the skills and past
    hunts use, not all 69 (~27k -> ~9k a step). A skill that needs a tool not on the list fails to
    call it - add it there.
  - step cap: `steps: 60` on the opencode agent. 48 of 625 hunts went past 60 steps (up to 129),
    each re-reading a longer context; at the cap the agent must answer, the runner validates.
  - unread outputs: see rule 11 - an output nothing reads gets no agent at all.
  - hunter leads: `run_skill(hunter_leads=...)` puts the hunter's best candidate and why it stopped
    into the first prompt, marked UNVERIFIED, so the agent starts there instead of rediscovering it.
  - `AGENTS.md` tells a skill run to stop reading; `.claude/agents/sig-finder.md` (claude, codex)
    carries the same body as the opencode agent: proof rules first, then economy rules.
  - Not done, on purpose: opencode `compaction.prune` (deprecated, applies between user turns while
    a hunt is one turn, and pruning would break the cached prefix that makes cache-read 20% of the
    input price); trimming the `generate-signature-*` skills (loaded only on demand, and they carry
    the masking rules a correct signature needs).
- **LLM_DECOMPILE** (pay-per-token, separate from the agent subscriptions above):
  `run_linux.sh` / `run_windows.sh` read `LLM_APIKEY`, `LLM_MODEL`, `LLM_BASEURL` and pass them as
  `-llm_apikey` / `-llm_model` / `-llm_baseurl`; if unset, `ida_analyze_bin.py` falls back to
  `CS2VIBE_LLM_APIKEY`, `CS2VIBE_LLM_MODEL`, `CS2VIBE_LLM_BASEURL`. Default model is `gpt-4o`
  (`DEFAULT_LLM_MODEL`) — set it explicitly rather than inheriting that.
  The transport is OpenAI-compatible `chat.completions` (`ida_llm_utils.call_llm_text`), so z.ai
  and any compatible provider work; the `/responses` endpoint is only used by the opt-in
  `fake_as="codex"` path.
  Cost shape: one call sends the prompt (4.3 KB) plus the reference YAML blocks
  (`ida_preprocessor_scripts/references/`, median 12.5 KB, p90 53 KB) plus the target blocks —
  roughly 10k input tokens median, ~30k at p90, and a few hundred output tokens. Validation
  failures retry, so budget ~1.3 calls per spec. Nothing is metered in-repo; there is no token
  accounting. `prompt/call_llm_decompile.md` keeps its fixed rules and examples FIRST and the
  placeholders last, so every call shares one byte-identical prefix that z.ai's KV prompt cache
  serves; a placeholder moved above the rules ends that
- Agent auto-select: if CS2VIBE_AGENT unset, scripts pick first installed CLI
- `CS2VIBE_AGENT=none` (or `manual`/`off`): no agent at all - preprocessors and the in-session
  hunter only, everything else written to `manual_todo/` for Ctrl-Alt-D

## Commit conventions

Never add "Co-Authored-By" lines to commits. Do not include Claude attribution
in commit messages, PR descriptions, or any git metadata.

Two mechanisms enforce this, because a prompt rule alone has been overridden by newer clients:
`.claude/settings.json` sets `"includeCoAuthoredBy": false`, and `.git/hooks/commit-msg` strips any
`Co-Authored-By: … Claude/Anthropic`, `Claude-Session:`, `Generated with [Claude Code]` or bare
`https://claude.ai/code/…` trailer that still reaches the message. The hook lives in `.git/`, so it
is per-clone: re-create it after a fresh clone.
