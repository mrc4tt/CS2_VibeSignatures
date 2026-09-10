"""IDA Pro plugin: CS2 sig maker (Ctrl-Alt-D) + CS2 vtable finder (Ctrl-Alt-V).

This is the ONLY file that belongs in ~/.idapro/plugins/. The scripts it loads
are plain scripts with no PLUGIN_ENTRY, so dropping them in plugins/ too makes
IDA report "undefined function __plugins__<name>.PLUGIN_ENTRY" for each one.

Repo location is resolved at load time (CS2VIBE_REPO wins), so the same plugin
works on a workstation and on the server without editing a hardcoded path; the
copy sitting beside this file is only a last-resort fallback.

Install: place this file in ~/.idapro/plugins/ and restart IDA.
"""
import os
import ida_idaapi

_SCRIPTS = ["ida_sig_maker.py", "cs2_vtable_finder.py", "ida_auto_hunt.py"]
_NS = {}


def _candidate_dirs():
    """Repo checkouts first so edits apply on restart; plugins dir copy last."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("CS2VIBE_REPO"),
        os.path.join(os.path.expanduser("~"), "CS2_VibeSignatures"),
        "/root/CS2_VibeSignatures",
        here,
    ]
    out, seen = [], set()
    for directory in candidates:
        if not directory:
            continue
        directory = os.path.normpath(directory)
        if directory in seen:
            continue
        seen.add(directory)
        out.append(directory)
    return out


def _load_all():
    dirs = _candidate_dirs()
    for script in _SCRIPTS:
        if script in _NS:
            continue
        for directory in dirs:
            path = os.path.join(directory, script)
            if os.path.exists(path):
                # a real __name__ keeps the scripts' own __main__ guards from
                # firing (bare exec globals would resolve it to "builtins")
                namespace = _NS.setdefault(script, {"__name__": "cs2_plugin_" + script[:-3]})
                with open(path, "r", encoding="utf-8") as handle:
                    exec(compile(handle.read(), path, "exec"), namespace)
                print(f"[cs2_plugins] loaded {path}")
                break
        else:
            print(f"[cs2_plugins] {script} not found in any of: {dirs}")


class cs2_plugins_t(ida_idaapi.plugin_t):
    flags = ida_idaapi.PLUGIN_KEEP
    comment = "CS2_VibeSignatures tooling"
    help = "Ctrl-Alt-D = sig/YAML maker, Ctrl-Alt-V = vtable finder"
    wanted_name = "CS2 plugins"
    wanted_hotkey = ""

    def init(self):
        try:
            _load_all()
        except Exception as error:
            print(f"[cs2_plugins] load failed: {error}")
        return ida_idaapi.PLUGIN_KEEP

    def run(self, arg):
        _load_all()
        for ns in _NS.values():
            if "main" in ns:
                ns["main"]()

    def term(self):
        pass


def PLUGIN_ENTRY():
    return cs2_plugins_t()
