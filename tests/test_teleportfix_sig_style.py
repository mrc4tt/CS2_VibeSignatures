"""TeleportFix writes each signature in the style its plugin file uses (code-style since
2026-11-13), and the template sync reads a code-style value as the IDA style it scans."""

import importlib.util
import os

import sync_plugin_templates as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _generator():
    path = os.path.join(ROOT, "gamedata-generators", "TeleportFix", "gamedata.py")
    spec = importlib.util.spec_from_file_location("teleportfix_gamedata", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_code_style_value_stays_code_style():
    g = _generator()
    assert g.convert_sig("48 8D 05 ?? ?? ?? ??", "\\x40\\x53") == "\\x48\\x8D\\x05\\x2A\\x2A\\x2A\\x2A"


def test_ida_style_value_stays_ida_style():
    g = _generator()
    assert g.convert_sig("48 8D 05 ?? ??", "40 53 ?") == "48 8D 05 ? ?"
    assert g.convert_sig("48 ??", None) == "48 ?"


def test_sync_reads_code_style_as_ida_style():
    entry = {"signatures": {"library": "server", "linux": "\\x55\\x48\\x2A", "windows": "40 53 ?"}}
    kind, values, library = S._values(entry)
    assert (kind, library) == ("signatures", "server")
    assert values == {"linux": "55 48 ?", "windows": "40 53 ?"}
