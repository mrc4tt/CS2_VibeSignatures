# CS2_VibeSignatures — GAMEVER-RUNBOOK (v3, komplet)

Pipeline-ejer: 9950X-serveren (mest komplette bin/). Lokal PC: IDA-GUI-jagt + review.
Alt nedenfor = på serveren medmindre andet nævnes. Agent: CS2VIBE_AGENT (claude/opencode).

## FASE 0 — NY GAMEVER: registrér manifests (engang)

```bash
./add_gamever.sh <VER>                  # prober Steam for manifest-ID'er → download.yaml
git add download.yaml && git commit -m "chore: pin <VER>" && git push
```
("allerede registreret" = spring til fase 1.)

## FASE 1 — ANALYSE (begge platforme)

```bash
git pull                                # altid frisk foer run!
./run_linux.sh <VER>
./run_windows.sh <VER>
```
Hvert script: config-scaffold → ensure-injektion (seeds + fallback-skills) → baseline-hydration
fra bin_artifacts → analyse (relocation foerst, agent ved aendringer) → publish → snapshot-pack.

Vigtigst: **bin/ er utracked** — efter pull altid: `cp -ru bin_artifacts/<VER>/. bin/<VER>/`
(og slet evt. gamle filer i bin/ som er fjernet i git).

## FASE 2 — TJEK RESTER

```bash
uv run missing_report.py -gamever <VER>          # kun ★SEED-rækker = dit arbejde
uv run audit_duplicate_va.py -gamever <VER>      # 0 suspekte klynger påkrævet
```
★SEED-residu → manuel IDA-jagt (PC): Ctrl-Alt-H (auto-hunt: 5 strategier) /
Ctrl-Alt-D (funcs batch) / Ctrl-Alt-V (vtables) / Ctrl-Alt-M (structmembers).

**Auto-hunt (Ctrl-Alt-H) prøver automatisk i rækkefølge:**
1. Relocation (baseline-sig → søg i ny binær)
2. Vtable-walk (RTTI → vtable → slot)
3. Seed-sig (community-sigs fra gamedata-generators)
4. Sibling-cluster (løste naboer → VA-delta)
5. String-anchor (klassenavn-strenge → xref → funktion)

Kun ægte nye/ændrede funktioner ryger i cursor-køen (Ctrl-Alt-D).

Alternativ headless enkelt-skill:
```bash
uv run ida_analyze_bin.py -gamever <VER> -platform linux -oldgamever <FORRIGE> -skill find-X
```
IDB-lås undervejs: pkill -9 -f 'idalib-mcp|ida_pro_mcp\.idalib_server' + slet bin/<VER>/*/*.id0/.id1/.id2/.nam/.til

## FASE 3 — RENAMES (valgfri men klogt)

```bash
uv run detect_aliases.py -gamever <VER> -platform linux   # og windows
```
Gammel noegle matcher analyseret VA = alias-kandidat (JoinTeam-moenstret).
Alias-fil: `aliases/<VER>.json` (curated + auto-detected).

## FASE 4 — GAMEDATA-GENERERING + DEPLOY

```bash
uv run gamesymbol_snapshot.py pack -gamever <VER> -snapshot gamesymbols/<VER>.yaml
uv run update_gamedata.py -gamever <VER> -snapshot gamesymbols/<VER>.yaml -outputdir gamedata/<VER>
./update_css_gamedata.sh <VER>            # gamedata.json → ~/CounterStrikeSharp-installen
                                          #   + css-extras HUD-symbols merges automatisk ind
./deploy_local_plugins.sh <VER>           # weaponpaints.json + matchzy.json → ~/customGIT/*-klonerne
```

## FASE 5 — PUBILCER

```bash
uv run audit_duplicate_va.py -gamever <VER>     # sidste check
git add gamedata/<VER> gamesymbols/<VER>.yaml bin_artifacts/<VER> configs/<VER>.yaml
git commit -m "feat(<VER>): complete analysis + gamedata" && git push origin main
# → sig.miksen.me deployer automatisk

cd /root/customGIT/weaponpaints && git add gamedata/ && git commit -m "gamedata: <VER>" && git push
cd /root/customGIT/matchzy     && git add gamedata/ && git commit -m "gamedata: <VER>" && git push
# PC'en bagefter: git pull i begge repos
```

## FASE 6 (VALGFRI) — LLM_DECOMPILE-REFERENCER

```bash
./gen_references.sh <VER>                  # resume-sikker, auto-reap, platform-bevidt
```
- SKIP "ingen <plat>-artefakt" = funktionen skal jages på den platform foerst (eller er
  platform-eksklusiv: SendViolationReport.linux + CDemoPlayer_StartPlayback.linux er
  dokumenteret umulige — ignorer dem altid)
- Efter nye jagter: kør igen, den tager kun resten

## FASE 7 — TILFØJ NYE SYMBOLER (manuelt)

### A. Nyt symbol til CounterStrikeSharp gamedata.json

**Fil at redigere:** `gamedata-generators/CounterStrikeSharp/templates/gamedata.json`

```bash
cd ~/CS2_VibeSignatures
nano gamedata-generators/CounterStrikeSharp/templates/gamedata.json
```

Tilføj din nye nøgle med community-sig (eller tomme felter som TODO):
```json
  "CCSMyNewFunction": {
    "signatures": {
      "library": "server",
      "windows": "48 89 ...",
      "linux": "55 48 ..."
    }
  }
```

Derefter:
```bash
# 1. ensure-scripts opdager den automatisk ved næste run (seed-scan)
# 2. generer med det samme:
uv run update_gamedata.py -gamever <VER> -snapshot gamesymbols/<VER>.yaml -outputdir gamedata/<VER>
# 3. commit + push:
git add gamedata-generators/CounterStrikeSharp/templates/gamedata.json gamedata/<VER>/CounterStrikeSharp/
git commit -m "feat: add <SYMBOL> to CSSharp gamedata" && git push
```

### B. Nyt symbol til weaponpaints / matchzy / bot-* (plugin-gamedata)

**Fil at redigere:** `gamedata-generators/<plugin>/gamedata/<plugin>.json`

```bash
nano gamedata-generators/weaponpaints/gamedata/weaponpaints.json
# eller: gamedata-generators/matchzy/gamedata/matchzy.json
# eller: gamedata-generators/bot-controller/gamedata/bot-controller.json
```

Tilføj nøglen → kør samme generering → commit → push.

### C. Nyt plugin/consumer (hel ny gamedata-kilde)

```bash
# 1. opret mappe-struktur:
mkdir -p gamedata-generators/<navn>/gamedata
# 2. kopier weaponpaints-generatoren som skabelon:
cp gamedata-generators/weaponpaints/gamedata.py gamedata-generators/<navn>/gamedata.py
# 3. rediger MODULE_NAME + GAMEDATA_PATH i filen
# 4. læg dit gamedata-json i gamedata-generators/<navn>/gamedata/<navn>.json
# 5. tilføj stien i ensure_local_gamedata_symbols.py's SEEDS-liste
# 6. (valgfrit) tilføj deploy-linje i deploy_local_plugins.sh
# 7. commit → næste run analyserer automatisk alle nye symbols
```

### D. Nyt alias / rename

```bash
# 1. tilføj i ensure_local_gamedata_symbols.py's ALIAS_OVERRIDES:
"CCSOldName": "CCSNewName",

# 2. kør ensure:
uv run python ensure_local_gamedata_symbols.py -config configs/<VER>.yaml

# 3. regenerer:
uv run update_gamedata.py -gamever <VER> -snapshot gamesymbols/<VER>.yaml -outputdir gamedata/<VER>
```

## FEJLSKEMA (hurtig-diagnose)

| Symptom | Fix |
|---------|-----|
| snapshot config digest mismatch | re-pack (config ændret siden sidst) — ufarligt |
| IDB lock file detected | reap (fase 2-kommandoen) og re-run |
| MCP port 13337 in use | gen_references' auto-reap klarer det; ellers pkill |
| duplicate symbol in module | kirurgisk fjern KUN den navngivne (behold alias-bærende entry) — ALDRIG `-all` |
| unable to locate function address | funktionen mangler artefakt → jagt (fase 2) — eller platform-eksklusiv |
| unable to export reference | kør lokalt paa PC (varm IDB + Hex-Rays) — eller jmp-thunk: OK lokalt |
| agent timeout x3 | -skip_error fortsætter; symbolet lander paa missing-listen → IDA-manuelt |
| ValidationError func_sig vs func_va | agent har dikter sig — re-run (hardned skills har contaminations-advarsler) |
| pages-snapshots push fejler | re-run workflow; hvis igen: `git push origin --delete pages-snapshots` → re-run |
| add/add conflict på artefakter | behold HEAD (server-agent har typisk fulere data: func_size, vtable-info) |
| config dependency gaps efter cleanup | for aggressiv dedupe — revert og kirurgisk fix kun de navngivne |

## HUSKEREGLER

- bin/ = lokal pr. maskine; broen er cp -ru bin_artifacts/<VER>/. bin/<VER>/ efter pull
- Pack/generering på maskinen med mest komplette bin/ (= serveren)
- Config læses ÉN gang pr. run-start — pull altid først
- .claude/skills = gamever-uafhængige og beskyttet (pre-commit guard: FORCE_SKILL_DELETE=1 for bevidst sletning)
- sync_upstream.sh = valgfri kvalitets-boost; beskytter gamedata/, gamesymbols/, deploy-pages.yml
- dot-commits: skriv ordentlige beskeder — guarden fanger skills-sletninger men ikke doven historik
- KØR ALDRIG run_linux.sh og run_windows.sh samtidig — de dræber hinandens idalib-mcp
- fix_duplicate_symbols.py: KUN på specifikke configs (-c), ALDRIG -all
- css-extras HUD-symbols: nu i CSSharp-template (genereres automatisk pr. gamever)

## VÆRKTØJ QUICK-REFERENCE

| Værktøj | Hvornår | Bemærkning |
|---------|---------|------------|
| `add_gamever.sh` | Ny gamever | Prober Steam for manifest-ID'er |
| `run_linux.sh` / `run_windows.sh` | Analyse | Agent auto-select + ensure-hooks |
| `missing_report.py` | Efter runs | Skriver missing-lister |
| `audit_duplicate_va.py` | Efter jagt | 0 suspekte = rent |
| `detect_aliases.py` | Efter snapshot-pack | Fanger renames |
| `enrich_vfunc_sigs.py` | Efter analyse | func_sig til vfunc-artefakter offline |
| `gen_references.sh` | Efter analyse | LLM_DECOMPILE-refs, resume-sikker |
| `update_css_gamedata.sh` | Efter generering | Deploy + css-extras merge |
| `deploy_local_plugins.sh` | Efter generering | → weaponpaints + matchzy clones |
| `fix_duplicate_symbols.py` | Kun ved validator-fejl | ALDRIG -all |
| `ensure_local_gamedata_symbols.py` | Auto i run-scripts | Seeds → config-tasks |
| `ensure_agent_fallback_skills.py` | Auto i run-scripts | Alle tasks får skills |
| `ensure_reference_base_tasks.py` | Efter nyt gamever | Tasks til reference-mål |
| `deploy_local_plugins.sh` | Efter gamedata-gen | → ~/customGIT/* |

## IDA PLUGIN HOTKEYS (lokal PC)

| Hotkey | Værktøj | Strategi |
|--------|---------|----------|
| Ctrl-Alt-H | auto-hunt v2 | 5 strategier automatisk |
| Ctrl-Alt-D | sig maker batch | Cursor-drevet (omdøbt fra S) |
| Ctrl-Alt-V | vtable finder | Interaktiv: klasse + slot + symbol |
| Ctrl-Alt-M | struct member emitter | Cursor på member-adgang |

## AGENT SETUP

- **Lokal PC**: `CS2VIBE_AGENT=claude` (Max 5x, Sonnet default)
- **Server**: `CS2VIBE_AGENT=opencode` (z.ai coding plan, glm-5.3-flash)
- **LLM_DECOMPILE**: kræver `LLM_APIKEY` (OpenAI /responses API — z.ai understøtter IKKE)
- Agent auto-select: hvis CS2VIBE_AGENT ikke sat, vælger scripts første installerede CLI
