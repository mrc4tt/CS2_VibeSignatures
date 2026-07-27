[Back to README](../../README.md) | [中文](../zh-CN/ci-cd.md)

# CI/CD and Jenkins workflow reference

The following Windows batch fragments show the guarded workflow stages.

## Download binaries

```batch
@echo Download latest game binaries

uv run download_depot.py -tag %CS2_GAMEVER%
uv run copy_depot_bin.py -gamever %CS2_GAMEVER% -platform %CS2_PLATFORM%
```

## Analyze binaries

```batch
@echo Analyze game binaries

uv run ida_analyze_bin.py -gamever %CS2_GAMEVER% -agent=claude.cmd -platform %CS2_PLATFORM% -debug
```

## Build the immutable symbol candidate

```batch
@echo Build the immutable candidate immediately after analysis

set "CANDIDATE_ID=%RANDOM%"
set "CANDIDATE_ROOT=%TEMP%\cs2vibe-%CS2_GAMEVER%-%CANDIDATE_ID%"
set "CANDIDATE_SNAPSHOT=%CANDIDATE_ROOT%\%CS2_GAMEVER%.yaml"
set "CANDIDATE_SESSION=%CANDIDATE_ROOT%\%CS2_GAMEVER%.session.json"
set "GAMEDATA_ROOT=%CANDIDATE_ROOT%\gamedata-candidate"
set "GAMEDATA_SESSION=%CANDIDATE_ROOT%\%CS2_GAMEVER%.gamedata.session.json"
if not exist "%CANDIDATE_ROOT%" mkdir "%CANDIDATE_ROOT%"
uv run gamesymbol_candidate.py build -gamever %CS2_GAMEVER% -bindir bin -configyaml configs/%CS2_GAMEVER%.yaml -output "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%"
```

## Build and guard the gamedata candidate

```batch
@echo Build gamedata from the immutable symbol candidate

uv run gamedata_candidate.py build -gamever %CS2_GAMEVER% -build-id %CANDIDATE_ID% -snapshot "%CANDIDATE_SNAPSHOT%" -configyaml configs/%CS2_GAMEVER%.yaml -candidate-root "%GAMEDATA_ROOT%" -session "%GAMEDATA_SESSION%"
uv run gamedata_candidate.py guard -session "%GAMEDATA_SESSION%"
uv run gamesymbol_candidate.py mark -candidate "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%" -step gamedata
```

## Validate C++ headers and publish the candidates

```batch
@echo Validate and publish the guarded candidates

uv run run_cpp_tests.py -gamever %CS2_GAMEVER% -configyaml configs/%CS2_GAMEVER%.yaml -snapshot "%CANDIDATE_SNAPSHOT%" -debug
uv run gamesymbol_candidate.py mark -candidate "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%" -step cpp_tests
uv run gamesymbol_candidate.py publish -candidate "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%" -snapshot gamesymbols/%CS2_GAMEVER%.yaml
uv run gamedata_candidate.py publish -session "%GAMEDATA_SESSION%" -outputdir gamedata/%CS2_GAMEVER%
```

See [Snapshots, gamedata, and C++ validation](snapshot-and-gamedata.md) for candidate-state guarantees, restore behavior, and pull-request output rules.
