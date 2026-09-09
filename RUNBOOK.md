# CS2_VibeSignatures — GAMEVER-RUNBOOK (v2, komplet)

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
★SEED-residu → manuel IDA-jagt (PC): Ctrl-Alt-S (funcs) / Ctrl-Alt-V (vtables) /
Ctrl-Alt-M (structmembers). Alternativ headless enkelt-skill:
```bash
uv run ida_analyze_bin.py -gamever <VER> -platform linux -oldgamever <FORRIGE> -skill find-X
```
IDB-lås undervejs: pkill -9 -f 'idalib-mcp|ida_pro_mcp\.idalib_server' + slet bin/<VER>/*/*.id0/.id1/.id2/.nam/.til

## FASE 3 — RENAMES (valgfri men klogt)

```bash
uv run detect_aliases.py -gamever <VER> -platform linux   # og windows
```
Gammel noegle matcher analyseret VA = alias-kandidat (JoinTeam-moenstret).

## FASE 4 — GAMEDATA-GENERERING + DEPLOY

```bash
uv run gamesymbol_snapshot.py pack -gamever <VER> -snapshot gamesymbols/<VER>.yaml
uv run update_gamedata.py -gamever <VER> -snapshot gamesymbols/<VER>.yaml -outputdir gamedata/<VER>
./update_css_gamedata.sh <VER>            # gamedata.json → ~/CounterStrikeSharp-installen
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

## FEJLSKEMA (hurtig-diagnose)

| Symptom | Fix |
|---|---|
| snapshot config digest mismatch | re-pack (config ændret siden sidst) — ufarligt |
| IDB lock file detected | reap (fase 2-kommandoen) og re-run |
| MCP port 13337 in use | gen_references' auto-reap klarer det; ellers pkill |
| duplicate symbol in module | ensure-injektion har lagt symbol ved siden af upstreams — fjern BARE den navngivne (behold alias-bærende entry) |
| unable to locate function address | funktionen mangler artefakt → jagt (fase 2) — eller platform-eksklusiv |
| unable to export reference | kør lokalt paa PC (varm IDB + Hex-Rays) — eller jmp-thunk: OK lokalt |
| agent timeout x3 | -skip_error fortsætter; symbolet lander paa missing-listen → IDA-manuelt |
| ValidationError func_sig vs func_va | agent har dikter sig — re-run (hardned skills har contaminations-advarsler) |

## HUSKEREGLER

- bin/ = lokal pr. maskine; broen er cp -ru bin_artifacts/<VER>/. bin/<VER>/ efter pull
- Pack/generering på maskinen med mest komplette bin/ (= serveren)
- Config læses ÉN gang pr. run-start — pull altid først
- .claude/skills = gamever-uafhængige og beskyttet (pre-commit guard: FORCE_SKILL_DELETE=1 for bevidst sletning)
- sync_upstream.sh = valgfri kvalitets-boost; beskytter gamedata/, gamesymbols/, deploy-pages.yml
- dot-commits: skriv ordentlige beskeder — guarden fanger skills-sletninger men ikke doven historik
