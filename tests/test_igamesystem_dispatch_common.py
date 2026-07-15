import importlib
import json
import types
import unittest
from unittest.mock import patch


def _load_module():
    return importlib.import_module("ida_preprocessor_scripts._igamesystem_dispatch_common")


# Fake operand type ids (values only need to be internally consistent).
O_DISPL = 4
O_IMM = 5


def _run_dispatch_py_eval(
    *,
    source_func_va: int,
    platform: str,
    funcs: dict[int, tuple[int, int]],
    instructions: dict[int, dict[str, object]],
    marker_addrs: set[int],
) -> dict[str, object]:
    """Exec the generated py_eval with fake IDA modules and return the parsed result.

    ``instructions`` maps an ea to a spec:
        mnem, operand_values (tuple), operands (print_operand strings tuple),
        ops (list of dicts merged onto insn.ops for decode_insn).
    ``marker_addrs`` are function start_eas whose bytes contain the dispatch marker.
    """
    module = _load_module()
    code = module._build_dispatch_py_eval(
        source_func_va=hex(source_func_va),
        via_internal_wrapper=False,
        platform=platform,
    )
    heads = sorted(instructions)

    def fake_decode_insn(insn, ea):
        spec = instructions.get(ea)
        if spec is None:
            return False
        insn.ops = [types.SimpleNamespace(**op) for op in spec.get("ops", [])]
        return True

    idaapi = types.ModuleType("idaapi")
    idaapi.o_displ = O_DISPL
    idaapi.o_imm = O_IMM
    idaapi.BADADDR = -1
    idaapi.get_func = lambda ea: (
        types.SimpleNamespace(start_ea=funcs[ea][0], end_ea=funcs[ea][1]) if ea in funcs else None
    )
    idaapi.add_func = lambda _ea: None
    idaapi.insn_t = lambda: types.SimpleNamespace(
        ops=[types.SimpleNamespace(type=0, addr=-1, value=0) for _ in range(2)]
    )
    idaapi.decode_insn = fake_decode_insn

    idautils = types.ModuleType("idautils")
    idautils.Heads = lambda start, end: [ea for ea in heads if start <= ea < end]

    idc = types.ModuleType("idc")
    idc.print_insn_mnem = lambda ea: instructions.get(ea, {}).get("mnem", "")
    idc.print_operand = lambda ea, idx: instructions.get(ea, {}).get("operands", ("", ""))[idx]
    idc.get_operand_value = lambda ea, idx: instructions.get(ea, {}).get("operand_values", (0, 0))[idx]

    marker = bytes((0x65, 0x48, 0x8B, 0x04, 0x25, 0x58, 0x00, 0x00, 0x00))
    ida_bytes = types.ModuleType("ida_bytes")
    ida_bytes.get_bytes = lambda start, size: marker if start in marker_addrs else b"\x90" * max(size, 0)

    fake_modules = {
        "idaapi": idaapi,
        "idautils": idautils,
        "idc": idc,
        "ida_bytes": ida_bytes,
    }
    exec_globals = {"__builtins__": __builtins__}
    exec_locals: dict[str, object] = {}
    with patch.dict("sys.modules", fake_modules, clear=False):
        exec(code, exec_globals, exec_locals)
    return json.loads(exec_locals["result"])


class TestBuildDispatchPyEval(unittest.TestCase):
    def test_generated_code_embeds_deinline_fallback(self) -> None:
        code = _load_module()._build_dispatch_py_eval(
            source_func_va="0x1000", via_internal_wrapper=False, platform="windows"
        )
        self.assertIn("import idaapi, idautils, idc, ida_bytes, json", code)
        self.assertIn(
            "DISPATCH_MARKER = bytes((0x65, 0x48, 0x8B, 0x04, 0x25, 0x58, 0x00, 0x00, 0x00))",
            code,
        )
        # py_eval dual-namespace bridge is required for the helper functions.
        self.assertIn("globals().update(locals())", code)
        self.assertIn("def _has_dispatch_marker(gef):", code)
        self.assertIn("def _ordered_callees(gef):", code)
        self.assertIn("def _scan_entries(gef):", code)
        self.assertIn("if not entries:", code)
        self.assertIn("'deinlined_dispatchers'", code)
        self.assertIn("is_windows = 1", code)

    def test_windows_deinlined_dispatchers_are_scanned(self) -> None:
        # Source (0x1000) only calls a dispatcher; the lea/vcall lives in the callee.
        payload = _run_dispatch_py_eval(
            source_func_va=0x1000,
            platform="windows",
            funcs={
                0x1000: (0x1000, 0x1010),
                0x2000: (0x2000, 0x2020),
                0x3000: (0x3000, 0x3010),
            },
            instructions={
                0x1000: {"mnem": "call", "operand_values": (0x2000, 0)},
                0x2000: {"mnem": "lea", "operands": ("rdx", ""), "operand_values": (0, 0x3000)},
                0x3000: {
                    "mnem": "call",
                    "ops": [{"type": O_DISPL, "addr": 0x148, "value": 0}, {"type": 0, "addr": -1, "value": 0}],
                },
            },
            marker_addrs={0x2000},
        )
        self.assertEqual(["0x2000"], payload["deinlined_dispatchers"])
        self.assertEqual(
            [{"game_event_addr": "0x3000", "vfunc_offset": 0x148, "vfunc_index": 41}],
            payload["entries"],
        )

    def test_windows_inlined_source_skips_fallback(self) -> None:
        # Source already contains the lea/vcall -> no callee fallback, no marker read.
        payload = _run_dispatch_py_eval(
            source_func_va=0x1000,
            platform="windows",
            funcs={0x1000: (0x1000, 0x1010), 0x3000: (0x3000, 0x3010)},
            instructions={
                0x1000: {"mnem": "lea", "operands": ("rdx", ""), "operand_values": (0, 0x3000)},
                0x3000: {
                    "mnem": "call",
                    "ops": [{"type": O_DISPL, "addr": 0x150, "value": 0}, {"type": 0, "addr": -1, "value": 0}],
                },
            },
            marker_addrs=set(),
        )
        self.assertNotIn("deinlined_dispatchers", payload)
        self.assertEqual(
            [{"game_event_addr": "0x3000", "vfunc_offset": 0x150, "vfunc_index": 42}],
            payload["entries"],
        )

    def test_linux_scan_collects_mov_esi_call(self) -> None:
        payload = _run_dispatch_py_eval(
            source_func_va=0x1000,
            platform="linux",
            funcs={0x1000: (0x1000, 0x1010)},
            instructions={
                0x1000: {
                    "mnem": "mov",
                    "operands": ("esi", ""),
                    "ops": [{"type": 0, "addr": -1, "value": 0}, {"type": O_IMM, "addr": -1, "value": 329}],
                },
                0x1004: {"mnem": "call", "operand_values": (0x5000, 0)},
            },
            marker_addrs=set(),
        )
        self.assertNotIn("deinlined_dispatchers", payload)
        self.assertEqual([{"vfunc_offset": 328, "vfunc_index": 41}], payload["entries"])


class TestDedupEntriesByOffset(unittest.TestCase):
    def setUp(self) -> None:
        self.dedup = _load_module()._dedup_entries_by_offset

    def test_empty(self) -> None:
        self.assertEqual([], self.dedup([]))

    def test_unique_offsets_unchanged(self) -> None:
        entries = [{"vfunc_offset": 328, "vfunc_index": 41}, {"vfunc_offset": 336, "vfunc_index": 42}]
        self.assertEqual(entries, self.dedup(entries))

    def test_repeated_offsets_collapse_keeping_first(self) -> None:
        # Mirrors 14168 Linux Begin over-match: [41, 42, 41, 42] -> [41, 42].
        entries = [
            {"vfunc_offset": 328, "vfunc_index": 41, "src": "dispatch"},
            {"vfunc_offset": 336, "vfunc_index": 42},
            {"vfunc_offset": 328, "vfunc_index": 41, "src": "resolver"},
            {"vfunc_offset": 336, "vfunc_index": 42},
        ]
        result = self.dedup(entries)
        self.assertEqual(2, len(result))
        self.assertEqual([328, 336], [e["vfunc_offset"] for e in result])
        self.assertEqual("dispatch", result[0]["src"])

    def test_hex_string_offsets_are_normalized(self) -> None:
        entries = [{"vfunc_offset": "0x148"}, {"vfunc_offset": 328}]
        self.assertEqual([{"vfunc_offset": "0x148"}], self.dedup(entries))

    def test_unparseable_entries_pass_through(self) -> None:
        entries = [{"vfunc_offset": None}, "not-a-dict", {"vfunc_offset": None}]
        self.assertEqual(entries, self.dedup(entries))


if __name__ == "__main__":
    unittest.main()
