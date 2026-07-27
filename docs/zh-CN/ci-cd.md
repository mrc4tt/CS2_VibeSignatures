[返回中文 README](../../README_CN.md) | [English](../en/ci-cd.md)

# CI/CD 与 Jenkins 工作流参考

以下 Windows batch 片段展示带 guard 的工作流阶段。

## 下载二进制

```batch
@echo Download latest game binaries

uv run download_depot.py -tag %CS2_GAMEVER%
uv run copy_depot_bin.py -gamever %CS2_GAMEVER% -platform %CS2_PLATFORM%
```

## 分析二进制

```batch
@echo Analyze game binaries

uv run ida_analyze_bin.py -gamever %CS2_GAMEVER% -agent=claude.cmd -platform %CS2_PLATFORM% -debug
```

## 构建 immutable symbol candidate

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

## 构建并 guard gamedata candidate

```batch
@echo Build gamedata from the immutable symbol candidate

uv run gamedata_candidate.py build -gamever %CS2_GAMEVER% -build-id %CANDIDATE_ID% -snapshot "%CANDIDATE_SNAPSHOT%" -configyaml configs/%CS2_GAMEVER%.yaml -candidate-root "%GAMEDATA_ROOT%" -session "%GAMEDATA_SESSION%"
uv run gamedata_candidate.py guard -session "%GAMEDATA_SESSION%"
uv run gamesymbol_candidate.py mark -candidate "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%" -step gamedata
```

## 验证 C++ headers 并发布 candidates

```batch
@echo Validate and publish the guarded candidates

uv run run_cpp_tests.py -gamever %CS2_GAMEVER% -configyaml configs/%CS2_GAMEVER%.yaml -snapshot "%CANDIDATE_SNAPSHOT%" -debug
uv run gamesymbol_candidate.py mark -candidate "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%" -step cpp_tests
uv run gamesymbol_candidate.py publish -candidate "%CANDIDATE_SNAPSHOT%" -session "%CANDIDATE_SESSION%" -snapshot gamesymbols/%CS2_GAMEVER%.yaml
uv run gamedata_candidate.py publish -session "%GAMEDATA_SESSION%" -outputdir gamedata/%CS2_GAMEVER%
```

candidate 状态保证、restore 行为与 pull request 输出规则见 [Snapshot、gamedata 与 C++ 验证](snapshot-and-gamedata.md)。
