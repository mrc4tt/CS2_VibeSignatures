"""ida_auto_hunt.py - resolve every missing artifact of the LOADED binary, no cursor involved.

Ctrl-Alt-H in IDA, or `uv run auto_hunt_ida.py ...` headless on a copy of the IDB.
The strategies, verification and report live in hunt_core.py (tool-neutral);
this file only binds them to IDA (ida_backend.py) and to ida_sig_maker's
emitters, so the YAML is byte-for-byte what the hotkeys and emit_artifact.py
write. Needs baseline facts: `uv run baseline_facts.py -gamever <prev> -module <m> -platform <p>`.
"""
import json
import os
import re
import sys

import ida_kernwin
import ida_nalt
import idc

REPO = None
for _cand in (os.environ.get("CS2VIBE_REPO"), os.path.join(os.path.expanduser("~"), "CS2_VibeSignatures"),
              "/home/mikkel/CS2_VibeSignatures", "/root/CS2_VibeSignatures"):
    if _cand and os.path.isdir(_cand):
        REPO = _cand
        break
if REPO and REPO not in sys.path:
    sys.path.insert(0, REPO)

_SIG_MAKER = {"__name__": "cs2_auto_hunt_sig_maker"}


def sig_maker():
    """ida_sig_maker exec'd once INTO this dict, which is therefore the functions' globals:
    setting _OUTPUT_DIR_OVERRIDE on it is what redirects write_yaml. A copy would not."""
    # re-exec on every press so an edited ida_sig_maker takes effect without reopening the
    # database; the dict is cleared in place because the emitters use it as their globals
    name = _SIG_MAKER.get("__name__", "cs2_auto_hunt_sig_maker")
    _SIG_MAKER.clear()
    _SIG_MAKER["__name__"] = name
    if "emit_symbol" not in _SIG_MAKER:
        with open(os.path.join(REPO, "ida_sig_maker.py"), "r", encoding="utf-8") as handle:
            exec(compile(handle.read(), "ida_sig_maker.py", "exec"), _SIG_MAKER)
    return _SIG_MAKER


def loaded_context():
    path = (ida_nalt.get_input_file_path() or "").replace("\\", "/")
    m = re.search(r"/bin/([A-Za-z0-9_.\-]+)/(\w+)/([^/]+)$", path)
    if not m:
        return None
    gamever, module, binname = m.groups()
    return gamever, module, ("windows" if binname.lower().endswith(".dll") else "linux")


def run(symbols=None, dry_run=False, out_dir=None, report_path=None, min_score=None, log=print):
    import importlib
    import hunt_core
    import ida_backend
    # re-read both on every press: the plugin loads once per IDA session, and an edited
    # hunt_core would otherwise only take effect after reopening the database
    hunt_core = importlib.reload(hunt_core)
    ida_backend = importlib.reload(ida_backend)
    if not REPO:
        log("[auto_hunt] repo not found (set CS2VIBE_REPO)"); return None
    ctx = loaded_context()
    if not ctx:
        log("[auto_hunt] load the binary from bin/<gamever>/<module>/"); return None
    gamever, module, platform = ctx
    baseline, facts = hunt_core.load_baseline_facts(REPO, gamever, module, platform)
    if not facts:
        log(f"[auto_hunt] no baseline facts: run  uv run baseline_facts.py -gamever <prev> -module {module} -platform {platform}")
        return None
    # the GUI writes to a review folder, never straight into bin_artifacts: a find is
    # promoted only after validate_artifacts / audit_duplicate_va have seen it
    real_dir = os.path.join(REPO, "bin_artifacts", gamever, module)
    out_dir = out_dir or os.path.join(REPO, "auto_hunt_out", gamever, module)
    os.makedirs(out_dir, exist_ok=True)
    sm = sig_maker()
    # every ida_sig_maker emitter writes through write_yaml when these are set, never
    # through the GUI path that mirrors into bin/ and bin_artifacts/ on its own
    sm["_OUTPUT_DIR_OVERRIDE"] = out_dir
    sm["_PLATFORM_OVERRIDE"] = platform
    backend = ida_backend.IdaBackend()
    scan = sm["Scan"]()

    def emit(symbol, rule):
        out = sm["emit_symbol"](symbol, rule, {}, scan)
        real = os.path.join(REPO, "bin_artifacts", gamever, module)
        if out and os.path.normpath(out_dir) == os.path.normpath(real):
            mirror = os.path.join(REPO, "bin", gamever, module)
            if os.path.isdir(mirror):
                try:
                    with open(out, "r", encoding="utf-8") as src, open(os.path.join(mirror, os.path.basename(out)), "w", encoding="utf-8") as dst:
                        dst.write(src.read())
                except OSError:
                    pass
        return out

    hunter = hunt_core.Hunter(backend, gamever, module, platform, facts, out_dir, emit=emit, dry_run=dry_run,
                              min_score=min_score or hunt_core.MIN_SCORE, log=log)
    report = hunter.run(symbols, baseline_artifact_dir=os.path.join(REPO, "bin_artifacts", baseline, module),
                        # symbols named explicitly are re-hunted even when an artifact
                        # exists: that is how a suspect record gets a second opinion
                        existing_dirs=() if symbols else (real_dir,))
    report.update({"gamever": gamever, "baseline": baseline, "module": module, "platform": platform, "backend": "ida"})
    hunt_core.print_report(report, log)
    if os.path.normpath(out_dir) != os.path.normpath(real_dir):
        log(f"[auto_hunt] written to {out_dir} - review, then:")
        log(f"  uv run validate_artifacts.py -gamever {gamever} -module {module} -platform {platform} -artifactdir {os.path.dirname(os.path.dirname(out_dir))}")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return report


def run_batch_job():
    with open(os.environ["CS2_AUTO_HUNT_JOB"], "r", encoding="utf-8") as handle:
        job = json.load(handle)
    import ida_auto
    ida_auto.auto_wait()
    try:
        run(symbols=job.get("symbols"), dry_run=job.get("dry_run", False), out_dir=job.get("out_dir"),
            report_path=job.get("report_path"), min_score=job.get("min_score"))
    finally:
        idc.qexit(0)


class _AutoHuntAction(ida_kernwin.action_handler_t):
    def activate(self, ctx):
        try:
            run()
        except Exception as error:
            print(f"[auto_hunt] failed: {error}")
        return 1

    def update(self, ctx):
        return ida_kernwin.AST_ENABLE_ALWAYS


ACTION_ID = "cs2vibe:auto_hunt"
try:
    ida_kernwin.unregister_action(ACTION_ID)
except Exception:
    pass
ida_kernwin.register_action(ida_kernwin.action_desc_t(
    ACTION_ID, "CS2 auto-hunt (baseline facts)", _AutoHuntAction(), "Ctrl-Alt-H",
    "Resolve every missing artifact of the loaded binary, verified against baseline facts", -1,
))
ida_kernwin.attach_action_to_menu("Edit/Plugins/CS2 auto-hunt (baseline facts)", ACTION_ID)

if __name__ == "__main__" and os.environ.get("CS2_AUTO_HUNT_JOB"):
    run_batch_job()
