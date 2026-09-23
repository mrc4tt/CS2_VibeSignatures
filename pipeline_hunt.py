"""pipeline_hunt.py - Ctrl-Alt-H's hunter inside the pipeline's own idalib session.

ida_analyze_bin.py calls hunt() through py_eval when a task's preprocessor fails, before
it pays an agent: the same strategies, evidence rule and emitters as the IDA hotkey
(hunt_core + ida_backend + ida_sig_maker), so a symbol the hotkey would solve for free
is no longer handed to an agent. Nothing here needs a UI.

State (baseline facts, byte caches) is kept in this module between calls, because the
session answers one task at a time and a server.dll scan costs seconds.
"""
import os
import re
import sys

_STATE = {}


class _NothingToHunt(Exception):
    pass


def _context():
    import ida_nalt

    path = (ida_nalt.get_input_file_path() or "").replace("\\", "/")
    m = re.search(r"/bin/([A-Za-z0-9_.\-]+)/(\w+)/([^/]+)$", path)
    if not m:
        return None
    gamever, module, binname = m.groups()
    return gamever, module, ("windows" if binname.lower().endswith(".dll") else "linux")


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
    state = {"baseline": baseline, "facts": facts, "backend": backend,
             "scan": hunt_core.Scan(backend.exec_regions()), "sm_scan": sig_maker["Scan"]()}
    _STATE[key] = state
    return state


def hunt(repo, symbols, out_dir):
    """Hunt `symbols` on the open binary, writing artifacts to `out_dir`.

    Returns {"solved": [...], "unresolved": [...], "log": [...]} or {"error": ...}. Only
    decisive evidence is written (hunt_core's rule); everything else comes back
    unresolved with its best candidates, for an agent or a person to decide.
    """
    if repo not in sys.path:
        sys.path.insert(0, repo)
    import hunt_core

    ctx = _context()
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
    wanted = [s for s in symbols if s in known]
    report = {"solved": [], "unresolved": [], "changed": [], "skipped": []}
    try:
        if not wanted:
            # Hunter.run treats an empty list as "every missing symbol"
            raise _NothingToHunt
        hunter = hunt_core.Hunter(
            state["backend"], gamever, module, platform, facts, out_dir,
            emit=lambda symbol, rule: sig_maker["emit_symbol"](symbol, rule, {}, state["sm_scan"]),
            log=lines.append, scan=state["scan"],
        )
        report = hunter.run(wanted, baseline_artifact_dir=os.path.join(repo, "bin_artifacts", state["baseline"], module))
    except _NothingToHunt:
        pass
    finally:
        sig_maker["_OUTPUT_DIR_OVERRIDE"] = None
        sig_maker["_PLATFORM_OVERRIDE"] = None
    for symbol in symbols:
        if symbol not in known:
            report["unresolved"].append({"symbol": symbol, "category": "?", "candidates": [],
                                         "why": f"not in the {state['baseline']} baseline facts"})
    hunt_core.print_report(report, lines.append)
    return {"solved": report["solved"], "unresolved": report["unresolved"] + report["changed"],
            "baseline": state["baseline"], "log": lines}
