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
