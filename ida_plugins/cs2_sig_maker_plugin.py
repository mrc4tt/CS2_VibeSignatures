"""IDA Pro plugin: CS2 sig maker (persistent hotkey Ctrl-Alt-S).

Loads ida_sig_maker.py from the first path that exists:
  1. ~/CS2_VibeSignatures/ida_sig_maker.py   (repo - edits apply on IDA restart)
  2. ~/.idapro/plugins/ida_sig_maker.py      (fallback copy)
Install: place this file in ~/.idapro/plugins/ and restart IDA.
"""
import os
import ida_idaapi

_CANDIDATES = [
    "/home/mikkel/CS2_VibeSignatures/ida_sig_maker.py",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ida_sig_maker.py"),
]
_NS = {}


def _load():
    if not _NS:
        for path in _CANDIDATES:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    exec(compile(f.read(), path, "exec"), _NS)
                return _NS
        raise FileNotFoundError(f"ida_sig_maker.py not found in any of: {_CANDIDATES}")
    return _NS


class cs2_sig_maker_plugin_t(ida_idaapi.plugin_t):
    flags = ida_idaapi.PLUGIN_KEEP
    comment = "CS2_VibeSignatures signature/YAML maker"
    help = "Cursor in target function, enter symbol name, YAML is written automatically."
    wanted_name = "CS2 sig maker"
    wanted_hotkey = "Ctrl-Alt-S"

    def init(self):
        try:
            _load()
        except Exception as error:
            print(f"[cs2_sig_maker] load failed: {error}")
        return ida_idaapi.PLUGIN_KEEP

    def run(self, arg):
        _load()["main"]()

    def term(self):
        pass


def PLUGIN_ENTRY():
    return cs2_sig_maker_plugin_t()
