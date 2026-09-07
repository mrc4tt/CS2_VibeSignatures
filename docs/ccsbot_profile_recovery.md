# CCSBot_Profile: ret kategori og genkør efter opdatering

Fejlen `vfunc artifact has unknown fields: member_name, offset, offset_sig, size,
struct_name` skyldes en konfigurationskonflikt. Begge konfigurationer klassificerede
`CCSBot_Profile` som `vfunc`, mens gamedata i bot-controller og bot-improver
beskriver `CCSBot -> m_profile`. Skillen instruerede samtidig agenten i både vfunc-
og structmember-output. En ren structmember-YAML fejlede derfor finalisering.

Rettelsen angiver `category: structmember`, `struct: CCSBot`, `member: m_profile`
i `configs/14178.yaml` og `configs/14178b.yaml`. Skillen kræver nu kun member-offset
og aktuelle binærbeviser. Den centrale validator forbliver streng.

Timeout på første agentforsøg er en separat hændelse. De gamle vtable-instruktioner
kan have sendt agenten på forkert spor, men logudsnittet beviser ikke timeoutens
årsag. Timeoutgrænse og sessionsgenoptagelse er ikke ændret.

## Opdatering på serveren

`ida_analyze_bin.py` indlæser konfiguration og kategorikort ved processtart.
`git pull` ændrer ikke kategorikortet i en allerede kørende Python-proces. En
fortsat OpenCode-session kan desuden bevare de gamle instruktioner.

1. Lad den aktuelle analyse afslutte, eller stop den kontrolleret. Start ikke en
   ny analyse mod samme binær/IDA-database, mens den gamle stadig bruger den.
2. Push rettelsen fra din lokale fork. På serveren: kontrollér lokale ændringer
   med `git status`, og brug `git pull --ff-only`, når arbejdsområdet er klar.
   Overskriv ikke ucommittede analyseartefakter for at få pull til at lykkes.
3. Start en ny målrettet analysekørsel med en frisk outputrod. Dermed bliver den
   eksisterende fejlfil ikke sprunget over som et allerede produceret output.

Eksempel fra repository-mappen på Linux-serveren:

```sh
profile_output=$(mktemp -d /tmp/ccsbot-profile-artifacts.XXXXXX)
uv run ida_analyze_bin.py \
  -gamever 14178b \
  -modules server \
  -platform windows,linux \
  -skill find-CCSBot_Profile \
  -agent opencode \
  -oldgamever none \
  -artifactdir "$profile_output"
```

Behold nødvendige miljøvariabler/modelindstillinger fra din normale kørsel.
Brug `-platform windows` hvis kun Windows skal repareres nu. Output findes under
`$profile_output/14178b/server/`. Kontrollér succesfuld runtime-finalisering før
artefakterne overtages i `bin_artifacts/14178b/server/` og committes. Ved fejl skal
agentens fund undersøges; undlad at fjerne felter for at omgå valideringen.

Den eksisterende lokale `CCSBot_Profile.linux.yaml` har funktion-schema og er
heller ikke et verificeret member-offset. Den skal regenereres; rettelsen opfinder
ikke en offset eller en signatur. Windows-fejlfilen fra serverloggen findes ikke
i dette lokale checkout. Ingen af disse binærartefakter er repareret af selve
kildeændringen.

Kategorirettelsen fjerner schema-konflikten, men garanterer ikke, at agenten finder
memberet inden for timeout. Release-/artefaktvalidering kræver stadig friske,
verificerede resultater for de berørte platforme.
