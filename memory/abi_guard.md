# abi_guard.py — ABI-identity guard

- Problem class: relocation propagates a wrong *identification*. Sig stays unique/valid per
  gamever but points at a function with a different ABI. `audit_duplicate_va.py` cannot see it.
- Known cases (14176→14181): `CBaseEntity_EmitSoundFilter` (picked a `this`-method; callers
  use sret → css_slay crash in CS#), `NetworkStateChanged` (picked a wrapper method that
  *calls* `CEntityInstance::NetworkStateChanged`; CS# SetStateChanged silently wrong).
- `uv run abi_guard.py [-gamever V] [--fix]` checks fn-head at yaml `func_va` against
  accepted/known-bad patterns, re-seeds `bin_artifacts/` (+`bin/`) from the accepted sig.
- Hooked: `sync_upstream.sh` (post-merge, upstream still carries the bad artifacts) and
  RUNBOOK fase 4 before `gamesymbol_snapshot.py pack`. Unit test: `tests/test_abi_guard.py`.
- Adding a symbol: extend `ABI_GUARDS` with good_sig + accept_heads + bad_heads per platform.
  Verify good_sig is 1 hit on the newest binaries first.

## 2026-09-16 update
- Guarded symbols now: CBaseEntity_EmitSoundFilter, NetworkStateChanged, CCSPlayer_MovementServices_ProcessMovement,
  CCSPlayer_MovementServices_WalkMove, CBaseTrigger_EndTouch, CBaseEntity_EmitSoundFilter_SoundName (ModSharp-only
  overload; routed via KEY_SYMBOL_OVERRIDES in gamedata-generators/modsharp-public/gamedata.py, fork-owned in
  ensure_local_gamedata_symbols.py).
- Finder anchors fixed at the source: NetworkStateChanged/ProcessMovement/WalkMove use per-platform
  `xref_signatures` (FUNC_XREFS_BY_PLATFORM, selected in preprocess_skill); ProcessMovement additionally requires
  vtable membership (FUNC_VTABLE_RELATIONS + CCSPlayer_MovementServices_vtable input); CBaseTrigger StartTouch/EndTouch
  emit func_sig (generate_func_sig=True + func_sig_allow_across_function_boundary:true).
- `consumer_drift_audit.py`: generic detector. Resolves our sig and each consumer's upstream sig on the same
  binary; DIFFERENT/OURS_* fail, OFFSET_DIFF/TEMPLATE_PASSTHROUGH/BOTH_STALE/UPSTREAM_MISALIGNED are informational.
  Found WalkMove and the ModSharp overload. Run before pack and before publish (RUNBOOK fase 4/5).
- Headless IDA verification without MCP: `uv run python` + `idapro.open_database("bin/<VER>/server/libserver.so.i64")`
  + ida_hexrays.decompile(va). ~1 min per DB.
