# CS2_VibeSignatures — GAMEVER-RUNBOOK (v4, autopilot)

Pipeline-ejer: 9950X-serveren (IDA, depot-binærer, disk). Lokal PC: IDA-GUI-jagt + review.
Alt nedenfor = på serveren medmindre andet nævnes.

**Normaltilstand: du gør intet.** `cs2vibe-autopilot.timer` spørger Steam hvert 15. min. En ny
build køres helt igennem — analyse, verifikation, gamedata, commit, push, site-data, deploy til
plugins — og Discord får `started` + `deployed`/`held`/`failed`. Manuelle trin herunder er kun til
når en besked siger `failed` eller `held`, eller når du vil tilføje symboler.

## 1 — HVAD AUTOPILOT GØR (i rækkefølge)

| # | Trin | Ved fejl |
|---|------|----------|
| 0 | preflight: disk ≥40G, DepotDownloader, agent-CLI; tracked ændringer committes + pushes | stop |
| 1 | `add_gamever.sh` → download.yaml | stop |
| 2 | `ensure_local_gamedata_symbols.py` + `ensure_seed_preprocessors.py` | stop |
| 3 | `run_linux.sh`, så `run_windows.sh` (aldrig samtidig) | resume op til 2× |
| 4 | `write_binary_lock.py -check` når låsen findes (bin/ skal være de låste filer), så `abi_guard.py --fix` (ABI-identitet, før pack — regel 21), så `audit_xref_identity.py` (hver funktion skal stadig rumme sit ankers streng/mønster) og `audit_identity_drift.py` (hver funktion mod forrige gamever: strengene skal følge med) | stop |
| 5 | snapshot `pack` + `check-contract` | stop |
| 6 | `update_gamedata.py` — 0 warnings krævet | stop |
| 7 | `validate_artifacts.py`, `audit_duplicate_va.py` | stop |
| 8 | `verify_plugin_gamedata.py` på hver shipped fil (deaktiverede plugins springes over) — `unhealthy: 0` krævet | stop |
| 9 | `detect_aliases`, `missing_report` (info) | — |
| 10 | `publish_site_data.py` (history + diagnostics), `write_binary_lock.py` | stop |
| 11 | `schema_dump.py impact` (info, linje i beskeden) | — |
| 12 | commit `feat(<VER>): analysed by autopilot`; derefter `publish_site_data.py -history-only` + commit `chore(<VER>): record publish date` (publishedAt kræver at commit'en findes); `-check`; push | stop |
| 13 | deploy efter `AUTOPILOT_DEPLOY` (`verified` her): `update_css_gamedata.sh` → `deploy_local_plugins.sh` (commit + push i plugin-repos) → `check_deploy_drift.py` | stop |

Sitet (sig.miksen.me) bygges af `deploy-pages.yml` fra push'et; `check-datasets`-jobbet fejler hvis
history.json er stale.

## 2 — BETJENING

```bash
systemctl list-timers cs2vibe-autopilot.timer     # næste kig
journalctl -u cs2vibe-autopilot -f                # hvad laver den
sudo systemctl start cs2vibe-autopilot.service    # kig nu
sudo systemctl stop cs2vibe-autopilot.timer       # nødbremse
./autopilot.sh -n                                 # dry run
./autopilot.sh <VER>                              # tving én build
rm -f .autopilot/attempts-<VER>                   # nulstil efter 2 fejlede forsøg
rm -f .autopilot/finish-attempts-<VER>            # nulstil efter 6 fejlede push/deploy-genoptag
```

Logs: `.autopilot/{gamedata,verify,gate,impact,missing}-<VER>.*`. En `failed`-besked indeholder
allerede de 2–3 kommandoer der skal køres (`hint_for()` i autopilot.sh) — start der.

Indstillinger i `.env` (se `systemd/README.md`): `AUTOPILOT_DEPLOY`, `AUTOPILOT_NOTIFY_URL`,
`AUTOPILOT_MIN_FREE_GB`, `AUTOPILOT_MAX_ATTEMPTS`, `AUTOPILOT_IMPACT_PLUGINS`, `AUTOPILOT_PUBLISH`.

## 3 — EFTER EN BUILD (tjek, 1 min)

```bash
git log --oneline -3                              # feat(<VER>) + chore(<VER>) pushet
uv run publish_site_data.py -check                # exit 0
uv run check_deploy_drift.py -gamever <VER>       # exit 0
cat manual_todo/<VER>/*.txt 2>/dev/null           # hvad hverken hunter eller agent fandt
```
`manual_todo/` er det eneste reelle restarbejde: Ctrl-Alt-D/Ctrl-Alt-R på PC'en, eller
`review_issue.py publish -gamever <VER> -platform <p>` → `/confirm`-kommentarer →
`review_issue.py apply -gamever <VER> -commit`.

## 4 — MANUELT (kun når autopilot er stoppet)

Samme rækkefølge som tabellen. Hvert trin kan genoptages:

```bash
./run_linux.sh <VER>; ./run_windows.sh <VER>      # resume, starter ikke forfra
uv run abi_guard.py -gamever <VER> --fix
uv run audit_xref_identity.py -gamever <VER>
uv run audit_identity_drift.py -gamever <VER>
uv run gamesymbol_snapshot.py pack -gamever <VER> -snapshot gamesymbols/<VER>.yaml
uv run gamesymbol_snapshot.py check-contract -gamever <VER> -snapshot gamesymbols/<VER>.yaml
uv run update_gamedata.py -gamever <VER> -snapshot gamesymbols/<VER>.yaml -outputdir gamedata/<VER>
uv run validate_artifacts.py -gamever <VER>
uv run audit_duplicate_va.py -gamever <VER>
uv run publish_site_data.py -gamever <VER>
uv run write_binary_lock.py -gamever <VER>          # -check når låsen allerede findes; aldrig -force over en lås
git add configs/<VER>.yaml bin_artifacts/<VER> gamesymbols/<VER>.yaml gamedata/<VER> \
    gamedata/history.json diagnostics/<VER>.json binary_locks/<VER>.json download.yaml
git commit -m "feat(<VER>): ..." && uv run publish_site_data.py -history-only
git commit -m "chore(<VER>): record publish date in site history" gamedata/history.json
git push
./update_css_gamedata.sh <VER> && ./deploy_local_plugins.sh <VER>   # denne rækkefølge
uv run check_deploy_drift.py -gamever <VER>
```
Fuldt batteri (inkl. 5b verify-loop og testsuite): CLAUDE.md → VERIFICATION BATTERY.

Enkelt-task headless:
```bash
uv run ida_analyze_bin.py -gamever <VER> -platform linux -oldgamever <FORRIGE> -skill find-X
```

## 5 — TILFØJ NYE SYMBOLER

Først CLAUDE.md → "WHEN TO CREATE A NEW PREPROCESSOR": findes symbolet allerede (søg
`expected_output`), er det et alias, mangler der bare et felt? Kun ellers en ny `find-<task>.py`.

### A. Nyt symbol til CounterStrikeSharp
Fil: `gamedata-generators/CounterStrikeSharp/templates/gamedata.json` — tilføj nøglen med
community-sig (verificér mod binæren først, regel 6). Commit + push; næste build tager den.
Med det samme: kør trin 4 fra `update_gamedata.py` og frem.

### B. Nyt symbol til weaponpaints / matchzy / bot-*
Fil: `gamedata-generators/<plugin>/gamedata/<plugin>.json`. Samme flow som A.

### C. Nyt plugin
1. `gamedata-generators/<navn>/` med generator (kopiér weaponpaints'), `MODULE_ENABLED = True`
2. Deploy-linje i både `deploy_local_plugins.sh` og `DEPLOY_TARGETS` (`tests/test_deploy_targets.py` håndhæver)
3. Commit + push — næste build analyserer og shipper automatisk

### D. Alias / rename
`ALIAS_OVERRIDES` i `ensure_local_gamedata_symbols.py` (ellers tabt ved næste upstream-merge), så
`uv run ensure_local_gamedata_symbols.py` og regenerér.

## FEJLSKEMA

| Symptom | Fix |
|---------|-----|
| `failed: checking ABI identity` | `uv run abi_guard.py -gamever <VER>`; "good_sig has 0 hits" = opdatér guard-tabellen i abi_guard.py |
| `site datasets stale` / CI `check-datasets` rød | `uv run publish_site_data.py` + commit `gamedata/history.json` |
| snapshot config digest mismatch | re-pack — ufarligt |
| `unhealthy: N` i verify | `grep -B20 "^unhealthy: [1-9]" .autopilot/verify-<VER>.log` |
| deploy drift | `uv run check_deploy_drift.py -gamever <VER>` navngiver nøglerne |
| IDB lock / idalib start-fejl | run-scripts rydder kun ejerløse `.id0/.id1/.id2/.nam/.til` selv; re-run. Aldrig blind `pkill idalib-mcp` (dræber editor-sessionen på 13337) |
| duplicate symbol in module | kirurgisk, kun den navngivne — ALDRIG `fix_duplicate_symbols.py -all` |
| unable to locate function address | mangler artefakt — `manual_todo/` / jagt — eller platform-eksklusiv |
| add/add conflict på artefakter | `sync_upstream.sh` håndterer det (ADDITIVE_PATHS = vores) |

## HUSKEREGLER

- bin/ er untracked: efter `git pull` på en anden maskine `cp -ru bin_artifacts/<VER>/. bin/<VER>/`
- KØR ALDRIG `run_linux.sh` og `run_windows.sh` samtidig
- Ændr aldrig et artefakt i hånden — feltet hører i taskens `GENERATE_YAML_DESIRED_FIELDS` (regel 18)
- Lokale config-ændringer skal også i en tabel i `ensure_local_gamedata_symbols.py`, ellers tabes de ved merge
- `.claude/skills` er beskyttet (pre-commit guard: `FORCE_SKILL_DELETE=1` for bevidst sletning)

## IDA PLUGIN HOTKEYS (lokal PC)

| Hotkey | Værktøj |
|--------|---------|
| Ctrl-Alt-H | auto-hunt (reloc, vtable, seed-sig, sibling, string-anchor) |
| Ctrl-Alt-J | jag navngivne symboler |
| Ctrl-Alt-E | emit artifact for adressen under cursoren |
| Ctrl-Alt-D | sig maker batch, forudfyldt fra `manual_todo/` |
| Ctrl-Alt-R | review-vindue over `manual_todo/` |
| Ctrl-Alt-V | vtable finder |
| Ctrl-Alt-O | struct member emitter |

## AGENT SETUP

- Server: `CS2VIBE_AGENT=opencode,codex,claude` (første tilgængelige), `CS2VIBE_SKILL_TIMEOUT=2400`
- Lokal PC: `CS2VIBE_AGENT=claude`
- LLM_DECOMPILE: `CS2VIBE_LLM_*` i `.env` — z.ai via OpenAI-kompatibel `chat.completions`;
  `CS2VIBE_LLM_FAKE_AS` skal være tom, `CS2VIBE_LLM_EFFORT=low` kræves af glm-5.3-flash
- `CS2VIBE_AGENT=none`: kun gratis arbejde, resten til `manual_todo/`
