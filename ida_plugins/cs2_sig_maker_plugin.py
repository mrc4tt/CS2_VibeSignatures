"""IDA Pro plugin: CS2 sig maker (Ctrl-Alt-S) + CS2 vtable finder (Ctrl-Alt-V).

Loads from the first existing path per script:
  1. ~/CS2_VibeSignatures/<script>.py   (repo - edits apply on IDA restart)
  2. ~/.idapro/plugins/<script>.py      (fallback copy)
Install: place this file in ~/.idapro/plugins/ and restart IDA.
"""
import os
import ida_idaapi

_SCRIPTS = ["ida_sig_maker.py", "cs2_vtable_finder.py", "ida_auto_hunt.py"]
_DIRS = [
    "/home/mikkel/CS2_VibeSignatures",
    os.path.dirname(os.path.abspath(__file__)),
]
_NS = {}


def _load_all():
    for script in _SCRIPTS:
        if script in _NS:
            continue
        for d in _DIRS:
            path = os.path.join(d, script)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    exec(compile(f.read(), path, "exec"), _NS.setdefault(script, {}))
                break
        else:
            print(f"[cs2_plugins] {script} not found in any of: {_DIRS}")


class cs2_plugins_t(ida_idaapi.plugin_t):
    flags = ida_idaapi.PLUGIN_KEEP
    comment = "CS2_VibeSignatures tooling"
    help = "Ctrl-Alt-S = sig/YAML maker, Ctrl-Alt-V = vtable finder"
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
