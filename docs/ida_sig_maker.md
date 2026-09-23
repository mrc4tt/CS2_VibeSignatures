# Automatisk signatur/YAML-generering med IDA Pro 9.1

`ida_sig_maker.py` kører `DEFAULT_QUEUE` uden cursor, navigationskrav eller spørgsmål.
`ida_sig_maker_batch.py` åbner alle `.dll` og `.so` rekursivt i en gameversion og
kører samme script. Kun Python-standardbiblioteket kræves uden for IDA; IDAPython
skal være installeret i IDA Pro. Binærerne skal være x86-64.

## Hurtig start

Fra repository-mappen, Windows PowerShell:

```powershell
python ida_sig_maker_batch.py bin/14178b --ida "C:/Program Files/IDA Professional 9.1/idat.exe"
```

Linux:

```sh
python3 ida_sig_maker_batch.py bin/14178b --ida /opt/ida-pro-9.1/idat
```

Erstat version og IDA-sti med dine egne. GUI-programmet `ida.exe`/`ida` kan også
bruges. Driveren anvender `-A`, `-S` og en separat midlertidig database via `-o`.
Eksisterende IDB-filer ændres ikke; analyse gentages fra originalbinæren.

Se filer først uden at starte IDA eller skrive noget:

```sh
python3 ida_sig_maker_batch.py bin/14178b --dry-run
```

I en allerede åben IDA-database: kør `ida_sig_maker.py` via File > Script file.
Ved plugin-import registreres Ctrl-Alt-S. Begge kører køen én gang uden spørgsmål.

## Kø og fund

Rediger `DEFAULT_QUEUE` øverst i `ida_sig_maker.py`, eller brug `--queue queue.txt`:

```text
# Et symbol per linje. Modulnavn svarer til mappen under gameversionen.
server!CCSPlayerInventory_GetItemInLoadout
engine2!CNetworkGameServer_GetFreeClient
```

Uden `module!` forsøges symbolet i alle moduler. Brug modulpræfiks for at undgå
forventede fejl i irrelevante moduler. Navne slås op præcist og via demanglede
C++-navne. Overloads eller flere kandidater rapporteres som uafklarede.

**Den medfølgende kø indeholder ønskede navne, ikke dokumenterede finderegler for
alle CS2-versioner.** En stripped binær indeholder ofte ikke disse navne. Der skal
så tilføjes en regel nedenfor. Scriptet gætter ikke på `sub_...`-funktioner og bruger
ikke automatisk projektets MCP-preprocessorer eller en LLM. For disse workflows
bruges fortsat `ida_analyze_bin.py`.

## Finderegler

`--rules rules.json` læser et JSON-objekt med regler per symbol. Eksempel på
navnealias og platformsspecifik opsætning (alias skal passe til din database):

```json
{
  "MyClass_DoWork": {
    "module": "server",
    "kind": "func",
    "windows": {"names": ["MyClass::DoWork"]},
    "linux": {"names": ["MyClass::DoWork"]}
  }
}
```

Understøttede felter:

- `kind: "func"`: præcist navn, `names` (liste af aliaser), `strings` (liste af
  præcise IDA-strenge med direkte xrefs til mål-funktionen), eller `pattern`
  (hexbytes med `??`; skal ramme selve funktionsstarten entydigt).
- Flere angivne ankre skal være enige. En entydig byte-signatur beviser placering,
  ikke funktionens semantiske identitet; reglen skal være fagligt verificeret.
- `kind: "structmember"`: kræver `pattern` ved den konkrete instruktion,
  `operand` (nulbaseret IDA-operandslot), `struct_name`, `member_name`, `size`
  (bytes). Det udvalgte displacement læses fra den aktuelle binær, ikke fra en
  hardcoded offset. Reglen skal identificere objektets member-adgang, ikke
  eksempelvis stack- eller RIP-relativ adressering. Wildcard displacement-bytes
  hvis reglen skal overleve offsetændringer. Mønstret skal være entydigt.
- `kind: "vfunc"`: kræver `address_point_name` (IDA-navn ved slot 0, efter eventuel
  ABI-header), `vtable_name` og `index` (nulbaseret). Funktionen læses fra slotten.
  Windows/Linux-indeks kan angives i separate platformsoverrides.
- `module` begrænser reglen til ét modul; `windows`/`linux` overskriver fælles felter.

Symboler med `_m_` behandles som structmembers og kræver en regel; de skrives aldrig
stiltiende som funktioner. Andre typer, såsom globale variable og patches, kræver
projektets eksisterende analysepipeline og understøttes ikke af dette script.

Ved interaktiv brug med regler:

```python
import json
import ida_sig_maker
rules = json.load(open("C:/work/rules.json", encoding="utf-8"))
ida_sig_maker.main(rules=rules)
```

Sørg for, at repository-mappen findes på IDA's Python-importsti.

## Fra fund til artifact på ét tastetryk (Ctrl-Alt-E) og fra kommandolinjen

Når du selv har fundet målet i GUI'en, skal scriptet kun gøre det mekaniske: læse
de aktuelle bytes, wildcarde det der relokeres, vokse til mønstret er entydigt og
skrive pipelinens schema. **Ctrl-Alt-E** ("CS2 emit artifact here") vælger art efter
det der står under cursoren:

| cursor på | art | hvad der udledes |
|---|---|---|
| vtable-slot (qword i data der peger på kode) | `vfunc` | klasse og index via RTTI-typeinfo-pointeren over slottet; `func_sig` når den findes |
| instruktion med `[reg+disp]` og symbol `Struct_m_member` | `structmember` | displacement fra DENNE binær; `offset_sig` vokser til entydig, `..._allow_across_function_boundary` sættes hvis nødvendigt |
| instruktion med RIP-relativ operand | `gv` / `func` / `patch` (spørger) | `gv_va` = RIP-mål, `gv_sig_va`, `gv_inst_length`, `gv_inst_disp` |
| andet inde i en funktion | `func` (eller `patch`) | funktionshovedet |

Forrige gamevers artifact (`bin_artifacts/<ældre>/<module>/<Symbol>.<platform>.yaml`)
udfylder `vtable_name`, `size`, `patch_bytes` og struct/member-navne, så de ikke
skal tastes igen. Værdierne er hints, aldrig bevis.

Samme kode fra kommandolinjen, på en midlertidig kopi af den varme `.i64` (GUI'en
kan blive stående åben; ingen genanalyse):

```
uv run emit_artifact.py -gamever 14182 -module server -platform linux \
    -symbol CCSPointScript_OnCustomHudClicked -kind func -ea 0xb27740
uv run emit_artifact.py ... -symbol CBaseTrigger_EndTouch -kind vfunc -class CBaseTrigger -index 151
uv run emit_artifact.py ... -symbol CGameEntitySystem_m_entityListeners -kind structmember \
    -ea 0x16f6bce -struct CGameEntitySystem -member m_entityListeners -size 8
uv run emit_artifact.py ... -symbol IGameSystem_InitAllSystems_pFirst -kind gv -ea 0xf022a6
uv run emit_artifact.py ... -symbol X_Patch -kind patch -ea 0x15dacf9 -patch_bytes "EB 7E"
```

Artifactet valideres bagefter med `validate_artifacts.py` for modulet. Et entydigt
mønster beviser placering, ikke identitet (CLAUDE.md regel 12): det er dig der står
inde for adressen. `uv run hunt_list.py -gamever <VER> -platform linux -module server
-only consumed` viser hvad der mangler, om relokering vil ramme (hits), hvilke ankre
den producerende task har, hvem der bruger symbolet, og den færdige emit-kommando.

Nye regelfelter i `--rules`: `ea` (eksplicit adresse) for `func`, `structmember`,
`gv` og `patch`; `class` + `index` for `vfunc` (RTTI i stedet for et IDA-navn);
`patch_bytes` for `patch`.

Signatur-stigen for funktionshoveder: (1) wildcarded inden for funktionen, (2) fortsat
ind i padding/næste hoved med `func_sig_allow_across_function_boundary`, (3) sidste
udvej: de lave displacement-bytes fastholdes (det pipelinen selv gør for familier af
identiske hoveder som point_script-bindingerne). Trin 3 flytter sig ved næste build -
scriptet siger det, og et streng- eller vtable-anker bør så tilføjes i preprocessoren.

## Automatisk jagt uden cursor (Ctrl-Alt-H / `auto_hunt_ida.py`)

1. Én gang per baseline: `uv run baseline_facts.py -gamever 14181 -module server -platform linux`
   (kører headless over en kopi af den varme baseline-IDB, ~2 min, skriver
   `baseline_facts/14181/server.linux.json`: maskerede hoveder, mnemonic-sekvens, kald i
   rækkefølge, kaldere med ordinal, strenge, vcall-offsets, hele vtable-nabolaget per klasse,
   og for members/globals/patches instruktions-form + kontekst + ejerfunktion).
2. I GUI'en med den NYE binær åben: **Ctrl-Alt-H**. Eller headless på en kopi af IDB'en:
   `uv run auto_hunt_ida.py -gamever 14182 -module server -platform linux [-symbols A,B] [-dry_run] [-outdir DIR]`

Strategier per manglende symbol, alle verificeret mod baseline-fakta før der skrives:
reloc, head-reloc (maskeret hoved vokset til entydigt), vtable med **målt slot-forskydning**
(nabolaget justeres, aldrig det gamle index), strengsæt-afstemning, kaldgraf (N'te kald i
en allerede løst kalder, funktioner der kalder kendte callees), callee-hoveder, nabo. Members,
globals og patches findes inde i den løste ejerfunktion efter instruktions-form + kontekst; en
patch hvis instruktion har skiftet form rapporteres som CHG og skrives aldrig. Resten kommer
med kandidater og score, så et menneske starter fra en shortlist. Målt på 14182 server/linux:
20 af 22 løst, alle enige med håndderiverede adresser; de to sidste korrekt tilbageholdt.

## Output og fejl

YAML skrives atomisk til `bin_artifacts/<gamever>/<module>/<Symbol>.<platform>.yaml`.
`--output` angiver alternativ gameversion-outputrod. Der skrives ingen YAML i `bin`.
Succesfulde fund overskriver samme symbols eksisterende YAML. Uafklarede fund
ændrer ikke gamle filer; gamle filer er ikke bevis på et succesfuldt nyt fund.

Funktioners signaturer genereres fra aktuelle bytes, holder sig inden for den
første sammenhængende funktionsdel og kontrolleres for overlappende matches i alle
læselige executable segmenter. Maksimum er 128 bytes. Meget korte eller ens
funktioner kan derfor være uafklarede.

Rapporter og IDA-logs findes i `sig_maker_reports/<gamever>/`; `--report-dir` kan
ændre placering. Hver binær får JSON/log og kørslen får `summary.json`. Exitkode 1
betyder mindst én fejlet binær eller ét uafklaret symbol. Timeout gælder per binær;
andres behandling fortsætter. `--timeout` er som standard 1800 sekunder.

Mappestrukturen forventes at have ét modul per mappe, eksempelvis
`server/server.dll` og `server/libserver.so`. Flere binærer for samme modul og
platform afvises før kørsel for at undgå YAML-kollisioner. Begge filtyper kan
analyseres fra samme værts-OS, hvis IDA-installationen har de nødvendige loaders.

Output er semantiske YAML-payloads. Projektets centrale validering/kanonisering
skal stadig køres før artefakter bruges i repository-releaseflowet.

IDA 9.1-reference: https://docs.hex-rays.com/9.1/user-guide/configuration/command-line-switches
