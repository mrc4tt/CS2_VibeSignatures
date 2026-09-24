"""pipeline_hunt.py - Ctrl-Alt-H's hunter inside the pipeline's own idalib session.

ida_analyze_bin.py calls hunt() through py_eval when a task's preprocessor fails, before
it pays an agent: the same strategies, evidence rule and emitters as the IDA hotkey
(hunt_core + ida_backend + ida_sig_maker), so a symbol the hotkey would solve for free
is no longer handed to an agent. Nothing here needs a UI.

State (baseline facts, byte caches) is kept in this module between calls, because the
session answers one task at a time and a server.dll scan costs seconds.
"""
import os
import sys

_STATE = {}


class _NothingToHunt(Exception):
    pass


def _context(repo=None):
    import hunt_core
    import ida_nalt

    return hunt_core.bin_context(ida_nalt.get_input_file_path(), repo)


def _sig_maker(repo):
    namespace = _STATE.get("sig_maker")
    if namespace is None:
        path = os.path.join(repo, "ida_sig_maker.py")
        namespace = {"__name__": "cs2_pipeline_sig_maker"}
        with open(path, "r", encoding="utf-8") as handle:
            exec(compile(handle.read(), path, "exec"), namespace)
        _STATE["sig_maker"] = namespace
    return namespace


def _session(repo, gamever, module, platform):
    key = (gamever, module, platform)
    state = _STATE.get(key)
    if state is not None:
        if state["sister"] is None and os.path.isfile(state["sister_path"]):
            # built by the caller after the first ask
            import json

            with open(state["sister_path"], "r", encoding="utf-8") as handle:
                state["sister"] = json.load(handle)
        return state
    import hunt_core
    import ida_backend

    baseline, facts = hunt_core.load_baseline_facts(repo, gamever, module, platform)
    if not facts:
        # not cached: the caller may build the facts and ask again
        return {"error": f"no baseline facts for {module}.{platform} before {gamever} "
                         f"(uv run baseline_facts.py -gamever <prev> -module {module} -platform {platform})"}
    backend = ida_backend.IdaBackend()
    sig_maker = _sig_maker(repo)
    sister_platform = "linux" if platform == "windows" else "windows"
    sister_path = hunt_core.facts_path(repo, gamever, module, sister_platform)
    sister = None
    if os.path.isfile(sister_path):
        import json

        with open(sister_path, "r", encoding="utf-8") as handle:
            sister = json.load(handle)
    state = {"baseline": baseline, "facts": facts, "backend": backend, "sister": sister, "sister_path": sister_path,
             "scan": hunt_core.Scan(backend.exec_regions()), "sm_scan": sig_maker["Scan"]()}
    _STATE[key] = state
    return state


def hunt(repo, symbols, out_dir, categories=None):
    """Hunt `symbols` on the open binary, writing artifacts to `out_dir`.

    Returns {"solved": [...], "unresolved": [...], "log": [...]} or {"error": ...}. Only
    decisive evidence is written (hunt_core's rule); everything else comes back
    unresolved with its best candidates, for an agent or a person to decide.
    """
    if repo not in sys.path:
        sys.path.insert(0, repo)
    import hunt_core

    ctx = _context(repo)
    if not ctx:
        return {"error": "the open binary is not under bin/<gamever>/<module>/"}
    gamever, module, platform = ctx
    state = _session(repo, gamever, module, platform)
    if state.get("error"):
        return {"error": state["error"]}
    facts = state["facts"]
    known = facts.get("symbols") or {}
    lines = []
    sig_maker = _STATE["sig_maker"]
    # every emitter writes through write_yaml when these are set - never the GUI path
    # that mirrors into bin/ and bin_artifacts/ on its own
    sig_maker["_OUTPUT_DIR_OVERRIDE"] = out_dir
    sig_maker["_PLATFORM_OVERRIDE"] = platform
    wanted = list(symbols)
    report = {"solved": [], "unresolved": [], "changed": [], "skipped": []}
    try:
        if not wanted:
            # Hunter.run treats an empty list as "every missing symbol"
            raise _NothingToHunt
        hunter = hunt_core.Hunter(
            state["backend"], gamever, module, platform, facts, out_dir,
            emit=lambda symbol, rule: sig_maker["emit_symbol"](symbol, rule, {}, state["sm_scan"]),
            log=lines.append, scan=state["scan"], sister_facts=state["sister"],
        )
        report = hunter.run(wanted, baseline_artifact_dir=os.path.join(repo, "bin_artifacts", state["baseline"], module),
                            categories=categories)
    except _NothingToHunt:
        pass
    finally:
        sig_maker["_OUTPUT_DIR_OVERRIDE"] = None
        sig_maker["_PLATFORM_OVERRIDE"] = None
    hunt_core.print_report(report, lines.append)
    new_symbols = [s for s in symbols if s not in known]
    return {"solved": report["solved"], "unresolved": report["unresolved"] + report["changed"],
            "baseline": state["baseline"], "log": lines,
            # a symbol this platform's baseline never had can be transferred from the same
            # build's other platform, once its facts exist
            "sister_missing": bool(new_symbols) and state["sister"] is None and platform == "windows"}
