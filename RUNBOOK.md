# CS2_VibeSignatures — gamever-runbook (fork)

Komplet kæde fra ny CS2-version til opdateret gamedata overalt.
Pipeline-ejer = 9950X (maskinen med mest komplette `bin/`).

## 0. Ny gamever: registrér manifest-pins (engang)

```bash
./add_gamever.sh 14180                 # prober Steam for aktuelle manifest-ID'er
git add download.yaml && git commit -m "chore: pin gamever 14180" && git push
```

(Springes over hvis tag allerede findes i download.yaml.)

## 1. Analyse — begge platforme

```bash
./run_linux.sh 14180
./run_windows.sh 14180
```

Hvert script gør automatisk: config-scaffold fra nyeste → ensure-injektion af alle
seed-symboler → agent-fallback-skills → baseline-hydration fra bin_artifacts/ →
idalib-analyse (genbrug hvor muligt) → publish bin→bin_artifacts → snapshot-pack.

Miljø: `CS2VIBE_AGENT=opencode` (z.ai). Valgfrit: `LLM_APIKEY` (OpenAI) aktiverer
LLM_DECOMPILE-referencer. `SKIP_ERRORS=0` for at abortere ved fejl (default: fortsæt).

## 2. Tjek rester

```bash
uv run missing_report.py -gamever 14180
```

Kun **★SEED**-rækkerne er dit arbejde (manuel IDA: Ctrl-Alt-S/M/V + emit-driver,
eller re-run). Upstream-symboler helbreder agent-fallbacks eller fremtidig sync.

## 3. (Valgfrit) fang renames

```bash
uv run detect_aliases.py -gamever 14180 -platform linux
uv run detect_aliases.py -gamever 14180 -platform windows
```

Gammel-nøgler der matcher analyserede VAs = alias-kandidater (JoinTeam-mønsteret).

## 4. Generér + deploy gamedata

```bash
./update_css_gamedata.sh 14180
```

Gør: billigt analyse-dobbelttjek → update_gamedata (alle 14 moduler) → merge-deploy
af gamedata.json til ~/CounterStrikeSharp-installen (backup gemmes).

Kun generering uden deploy:
`uv run update_gamedata.py -gamever 14180 -snapshot gamesymbols/14180.yaml -outputdir gamedata/14180`

## 5. Deploy til lokale plugin-clones

```bash
./deploy_local_plugins.sh 14180
```

→ ~/customGIT/weaponpaints/gamedata/weaponpaints.json + ~/customGIT/matchzy/gamedata/matchzy.json

## 6. Publisér

```bash
git add gamedata/14180 gamesymbols/14180.yaml bin_artifacts/14180 configs/14180.yaml download.yaml
git commit -m "feat(14180): complete analysis + gamedata"
git push origin main                  # → sig.miksen.me deployer automatisk
```

## 7. (Valgfrit) plugin-repos

```bash
cd ~/customGIT/weaponpaints && git add gamedata/ && git commit -m "gamedata: 14180" && git push
cd ~/customGIT/matchzy     && git add gamedata/ && git commit -m "gamedata: 14180" && git push
```

## Manuel IDA-jagt (residuet)

| Type | Værktøj | Output |
|---|---|---|
| funcs | Ctrl-Alt-S (batch) / emit_driver.py | .{platform}.yaml i bin/ + bin_artifacts/ |
| vfuncs | Ctrl-Alt-V (RTTI-vtable, interaktiv) | vfunc-schema |
| structmembers | Ctrl-Alt-M (cursor på member-adgang) | structmember-schema |

Efter manuelle emits: re-pack (`gamesymbol_snapshot.py pack`) + trin 4-6 igen.

## Sync med upstream (valgfri kvalitets-boost)

```bash
./sync_upstream.sh        # auto-resolve; beskytter gamedata/, gamesymbols/, deploy-pages.yml
```

## Huskeregler

- `bin/` er lokal pr. maskine — broen er `cp -ru bin_artifacts/<ver>/. bin/<ver>/` efter pull
- Pack/generering kører på maskinen med mest komplette bin/
- Config læses ÉN gang ved run-start — tjek den er current før lange runs
