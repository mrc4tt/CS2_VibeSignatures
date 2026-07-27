import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.ida_preprocessor_test_support import FakeCallToolResult, load_module, py_eval_payload


ORDINAL_VTABLE_COMMON_PATH = Path("ida_preprocessor_scripts/_ordinal_vtable_common.py")


class _FakeSegment:
    def __init__(self, start_ea: int, end_ea: int, perm: int) -> None:
        self.start_ea = start_ea
        self.end_ea = end_ea
        self.perm = perm


def _run_ordinal_vtable_py_eval(
    *,
    class_name: str,
    ordinal: int,
    symbol_aliases=None,
    expected_offset_to_top=None,
    name_to_ea=None,
    name_by_ea=None,
    data_refs=None,
    ptr_values=None,
    func_addrs=None,
    code_addrs=None,
    segments=None,
):
    module = load_module(
        ORDINAL_VTABLE_COMMON_PATH,
        "ordinal_vtable_common_exec",
    )
    py_code = module._build_ordinal_vtable_py_eval(
        class_name=class_name,
        ordinal=ordinal,
        symbol_aliases=symbol_aliases,
        expected_offset_to_top=expected_offset_to_top,
    )

    name_to_ea = dict(name_to_ea or {})
    name_by_ea = dict(name_by_ea or {})
    data_refs = {int(target): list(refs) for target, refs in dict(data_refs or {}).items()}
    ptr_values = dict(ptr_values or {})
    func_addrs = set(func_addrs or [])
    code_addrs = set(code_addrs or [])
    segments = list(segments or [])

    def _get_seg(ea: int):
        for segment in segments:
            if segment.start_ea <= ea < segment.end_ea:
                return segment
        return None

    idaapi = types.ModuleType("idaapi")
    idaapi.BADADDR = -1
    idaapi.inf_is_64bit = lambda: True
    idaapi.get_func = lambda ea: types.SimpleNamespace(start_ea=ea, end_ea=ea + 1) if ea in func_addrs else None

    ida_bytes = types.ModuleType("ida_bytes")
    ida_bytes.get_qword = lambda ea: ptr_values.get(ea, 0)
    ida_bytes.get_dword = lambda ea: ptr_values.get(ea, 0) & 0xFFFFFFFF
    ida_bytes.get_full_flags = lambda ea: 1 if ea in code_addrs else 0
    ida_bytes.is_code = lambda flags: bool(flags)

    ida_name = types.ModuleType("ida_name")
    ida_name.get_name_ea = lambda badaddr, name: name_to_ea.get(name, badaddr)
    ida_name.get_name = lambda ea: name_by_ea.get(ea, "")

    idautils = types.ModuleType("idautils")
    idautils.DataRefsTo = lambda ea: list(data_refs.get(ea, []))
    idautils.Names = lambda: [(ea, name) for name, ea in name_to_ea.items()]

    ida_segment = types.ModuleType("ida_segment")
    ida_segment.SEGPERM_EXEC = 1
    ida_segment.getseg = _get_seg

    fake_modules = {
        "idaapi": idaapi,
        "ida_bytes": ida_bytes,
        "ida_name": ida_name,
        "idautils": idautils,
        "ida_segment": ida_segment,
    }
    globals_dict = {"__builtins__": __builtins__}
    with patch.dict(sys.modules, fake_modules, clear=False):
        exec(py_code, globals_dict)

    return json.loads(globals_dict["result"])


class TestOrdinalVtableCommon(unittest.IsolatedAsyncioTestCase):
    def test_build_ordinal_vtable_py_eval_embeds_constraints(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common",
        )

        py_code = module._build_ordinal_vtable_py_eval(
            class_name="CSpawnGroupMgrGameSystem",
            ordinal=2,
            symbol_aliases=["??_7CSpawnGroupMgrGameSystem@@6B@_0"],
            expected_offset_to_top=-8,
        )

        self.assertIn('"CSpawnGroupMgrGameSystem"', py_code)
        self.assertIn("??_7CSpawnGroupMgrGameSystem@@6B@_0", py_code)
        self.assertIn("ordinal = 2", py_code)
        self.assertIn("expected_offset_to_top = -8", py_code)
        self.assertIn("debug_trace_enabled = False", py_code)
        self.assertIn("globals().update(locals())", py_code)
        self.assertIn("addr + (2 * ptr_size)", py_code)
        self.assertIn('symbol_name + " + " + hex(2 * ptr_size)', py_code)
        self.assertIn("if ptr_value == 0:", py_code)
        self.assertIn("if is_linux:", py_code)

    def test_ordinal_py_eval_runs_with_separate_globals_and_locals(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common_separate_exec",
        )
        py_code = module._build_ordinal_vtable_py_eval(
            class_name="Foo",
            ordinal=0,
            symbol_aliases=["??_7Foo@@6B@_0"],
            expected_offset_to_top=None,
        )

        idaapi = types.ModuleType("idaapi")
        idaapi.BADADDR = -1
        idaapi.inf_is_64bit = lambda: True
        idaapi.get_func = lambda ea: types.SimpleNamespace(start_ea=ea, end_ea=ea + 1) if ea == 0x9000 else None

        ida_bytes = types.ModuleType("ida_bytes")
        ida_bytes.get_qword = lambda ea: {
            0x2008: 0x9000,
            0x2010: 0,
        }.get(ea, 0)
        ida_bytes.get_dword = lambda ea: 0
        ida_bytes.get_full_flags = lambda ea: 0
        ida_bytes.is_code = lambda flags: False

        ida_name = types.ModuleType("ida_name")
        ida_name.get_name_ea = lambda badaddr, name: badaddr
        ida_name.get_name = lambda ea: {
            0x2008: "??_7Foo@@6B@_0",
        }.get(ea, "")

        idautils = types.ModuleType("idautils")
        idautils.DataRefsTo = lambda ea: [0x2000] if ea == 0x1500 else []
        idautils.Names = lambda: [(0x1500, "??_R4Foo@@6B@_0")]

        ida_segment = types.ModuleType("ida_segment")
        ida_segment.SEGPERM_EXEC = 1
        ida_segment.getseg = lambda ea: (
            _FakeSegment(0x2000, 0x3000, 0)
            if 0x2000 <= ea < 0x3000
            else _FakeSegment(0x9000, 0xA000, 1)
            if 0x9000 <= ea < 0xA000
            else None
        )

        fake_modules = {
            "idaapi": idaapi,
            "ida_bytes": ida_bytes,
            "ida_name": ida_name,
            "idautils": idautils,
            "ida_segment": ida_segment,
        }
        exec_globals = {"__builtins__": __builtins__}
        exec_locals = {}
        with patch.dict(sys.modules, fake_modules, clear=False):
            exec(py_code, exec_globals, exec_locals)

        result = json.loads(exec_locals["result"])
        self.assertEqual("??_7Foo@@6B@_0", result["vtable_symbol"])
        self.assertEqual("0x2008", result["vtable_va"])

    async def test_preprocess_ordinal_vtable_normalizes_result(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common_preprocess",
        )
        session = AsyncMock()
        session.call_tool.return_value = py_eval_payload(
            {
                "vtable_class": "CSpawnGroupMgrGameSystem",
                "vtable_symbol": "??_7CSpawnGroupMgrGameSystem@@6B@_0",
                "vtable_va": "0x1819682b0",
                "vtable_size": "0x10",
                "vtable_numvfunc": 2,
                "vtable_entries": {
                    "0": "0x18014c840",
                    "1": "0x18014c850",
                },
                "offset_to_top": -8,
                "source": "linux-typeinfo",
            }
        )

        result = await module.preprocess_ordinal_vtable_via_mcp(
            session=session,
            class_name="CSpawnGroupMgrGameSystem",
            ordinal=0,
            image_base=0x180000000,
            platform="windows",
            debug=True,
            symbol_aliases=["??_7CSpawnGroupMgrGameSystem@@6B@_0"],
            expected_offset_to_top=None,
            canonical_vtable_symbol="CSpawnGroupMgrGameSystem_vtable2",
        )

        self.assertEqual(
            {
                "vtable_class": "CSpawnGroupMgrGameSystem",
                "vtable_symbol": "CSpawnGroupMgrGameSystem_vtable2",
                "vtable_va": "0x1819682b0",
                "vtable_rva": "0x19682b0",
                "vtable_size": "0x10",
                "vtable_numvfunc": 2,
                "vtable_entries": {
                    0: "0x18014c840",
                    1: "0x18014c850",
                },
            },
            result,
        )
        self.assertNotIn("offset_to_top", result)
        self.assertNotIn("source", result)
        session.call_tool.assert_awaited_once()

    async def test_preprocess_ordinal_vtable_prints_debug_trace_from_wrapped_payload(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common_debug_trace",
        )
        session = AsyncMock()
        session.call_tool.return_value = py_eval_payload(
            {
                "selected": None,
                "debug_trace": [
                    "[direct-miss] symbol=??_7CSpawnGroupMgrGameSystem@@6B@_0",
                    "[result-none] reason=no_alias_candidate_matched aliases=['??_7CSpawnGroupMgrGameSystem@@6B@_0']",
                ],
            }
        )

        with patch("builtins.print") as mock_print:
            result = await module.preprocess_ordinal_vtable_via_mcp(
                session=session,
                class_name="CSpawnGroupMgrGameSystem",
                ordinal=0,
                image_base=0x180000000,
                platform="windows",
                debug=True,
                symbol_aliases=["??_7CSpawnGroupMgrGameSystem@@6B@_0"],
                expected_offset_to_top=None,
            )

        self.assertIsNone(result)
        mock_print.assert_any_call(
            "    Preprocess ordinal vtable trace: [direct-miss] symbol=??_7CSpawnGroupMgrGameSystem@@6B@_0"
        )
        mock_print.assert_any_call(
            "    Preprocess ordinal vtable trace: "
            "[result-none] reason=no_alias_candidate_matched "
            "aliases=['??_7CSpawnGroupMgrGameSystem@@6B@_0']"
        )
        mock_print.assert_any_call("    Preprocess ordinal vtable: no result for CSpawnGroupMgrGameSystem[0]")

    async def test_preprocess_ordinal_vtable_prints_py_eval_stderr_when_result_empty(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common_stderr",
        )
        session = AsyncMock()
        session.call_tool.return_value = FakeCallToolResult(
            {
                "result": "",
                "stdout": "debug stdout",
                "stderr": "Traceback: boom",
            }
        )

        with patch("builtins.print") as mock_print:
            result = await module.preprocess_ordinal_vtable_via_mcp(
                session=session,
                class_name="CSpawnGroupMgrGameSystem",
                ordinal=0,
                image_base=0x180000000,
                platform="windows",
                debug=True,
                symbol_aliases=["??_7CSpawnGroupMgrGameSystem@@6B@_0"],
                expected_offset_to_top=None,
            )

        self.assertIsNone(result)
        mock_print.assert_any_call("    Preprocess ordinal vtable py_eval stderr:")
        mock_print.assert_any_call("Traceback: boom")
        mock_print.assert_any_call("    Preprocess ordinal vtable py_eval stdout:")
        mock_print.assert_any_call("debug stdout")
        mock_print.assert_any_call(
            "    Preprocess ordinal vtable: empty py_eval result for CSpawnGroupMgrGameSystem[0]"
        )

    async def test_preprocess_ordinal_vtable_forwards_constraints_into_py_eval(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common_constraints",
        )
        session = AsyncMock()
        session.call_tool.return_value = py_eval_payload(None)

        result = await module.preprocess_ordinal_vtable_via_mcp(
            session=session,
            class_name="CSpawnGroupMgrGameSystem",
            ordinal=2,
            image_base=0x180000000,
            platform="linux",
            debug=False,
            expected_offset_to_top=-16,
        )

        self.assertIsNone(result)
        py_code = session.call_tool.await_args.kwargs["arguments"]["code"]
        self.assertIn("ordinal = 2", py_code)
        self.assertIn("expected_offset_to_top = -16", py_code)

    async def test_preprocess_ordinal_vtable_returns_none_for_empty_result(self) -> None:
        module = load_module(
            ORDINAL_VTABLE_COMMON_PATH,
            "ordinal_vtable_common_none",
        )
        session = AsyncMock()
        session.call_tool.return_value = py_eval_payload(None)

        result = await module.preprocess_ordinal_vtable_via_mcp(
            session=session,
            class_name="CSpawnGroupMgrGameSystem",
            ordinal=0,
            image_base=0x180000000,
            platform="linux",
            debug=False,
            symbol_aliases=["??_7CSpawnGroupMgrGameSystem@@6B@_0"],
            expected_offset_to_top=-8,
        )

        self.assertIsNone(result)

    def test_ordinal_py_eval_alias_fail_closed_even_when_rtti_is_available(self) -> None:
        shared_kwargs = {
            "class_name": "Foo",
            "ordinal": 0,
            "name_to_ea": {
                "??_R4Foo@@6B@": 0x1500,
            },
            "name_by_ea": {
                0x2008: "rtti_candidate",
            },
            "data_refs": {
                0x1500: [0x2000],
            },
            "ptr_values": {
                0x2008: 0x9000,
                0x2010: 0,
            },
            "func_addrs": {0x9000},
            "segments": [
                _FakeSegment(0x2000, 0x3000, 0),
                _FakeSegment(0x9000, 0xA000, 1),
            ],
        }

        fallback_result = _run_ordinal_vtable_py_eval(**shared_kwargs)
        self.assertEqual("rtti_candidate", fallback_result["vtable_symbol"])
        self.assertEqual("0x2008", fallback_result["vtable_va"])

        fail_closed_result = _run_ordinal_vtable_py_eval(
            **shared_kwargs,
            symbol_aliases=["??_7Foo@@6B@_0"],
        )
        self.assertIsNone(fail_closed_result)

    def test_ordinal_py_eval_can_match_alias_via_windows_rtti_when_direct_lookup_misses(self) -> None:
        result = _run_ordinal_vtable_py_eval(
            class_name="Foo",
            ordinal=0,
            symbol_aliases=["??_7Foo@@6B@_0"],
            name_to_ea={
                "??_R4Foo@@6B@_0": 0x1500,
            },
            name_by_ea={
                0x2008: "??_7Foo@@6B@_0",
            },
            data_refs={
                0x1500: [0x2000],
            },
            ptr_values={
                0x2008: 0x9000,
                0x2010: 0,
            },
            func_addrs={0x9000},
            segments=[
                _FakeSegment(0x2000, 0x3000, 0),
                _FakeSegment(0x9000, 0xA000, 1),
            ],
        )

        self.assertEqual("??_7Foo@@6B@_0", result["vtable_symbol"])
        self.assertEqual("0x2008", result["vtable_va"])

    def test_ordinal_py_eval_linux_zero_slot_continues_until_boundary(self) -> None:
        result = _run_ordinal_vtable_py_eval(
            class_name="Foo",
            ordinal=0,
            symbol_aliases=["_ZTV3Foo"],
            name_to_ea={
                "_ZTV3Foo": 0x2000,
            },
            name_by_ea={
                0x2028: "_ZTI3Foo",
            },
            ptr_values={
                0x2010: 0x9000,
                0x2018: 0,
                0x2020: 0x9010,
            },
            func_addrs={0x9000, 0x9010},
            segments=[
                _FakeSegment(0x2000, 0x3000, 0),
                _FakeSegment(0x9000, 0xA000, 1),
            ],
        )

        self.assertEqual("_ZTV3Foo + 0x10", result["vtable_symbol"])
        self.assertEqual(
            {
                "0": "0x9000",
                "1": "0x0",
                "2": "0x9010",
            },
            result["vtable_entries"],
        )
        self.assertEqual(3, result["vtable_numvfunc"])

    def test_ordinal_py_eval_filters_sorts_then_selects_by_ordinal(self) -> None:
        result = _run_ordinal_vtable_py_eval(
            class_name="Foo",
            ordinal=1,
            expected_offset_to_top=-8,
            name_to_ea={
                "_ZTI3Foo": 0x1800,
            },
            name_by_ea={
                0x5010: "vt_high",
                0x3010: "vt_filtered_out",
                0x4010: "vt_low",
                0x5018: "_ZTVboundary_high",
                0x3018: "_ZTVboundary_filtered_out",
                0x4018: "_ZTIboundary_low",
            },
            data_refs={
                0x1800: [0x5008, 0x3008, 0x4008],
            },
            ptr_values={
                0x5000: 0xFFFFFFFFFFFFFFF8,
                0x3000: 0xFFFFFFFFFFFFFFF0,
                0x4000: 0xFFFFFFFFFFFFFFF8,
                0x5010: 0x9500,
                0x3010: 0x9300,
                0x4010: 0x9400,
            },
            func_addrs={0x9300, 0x9400, 0x9500},
            segments=[
                _FakeSegment(0x3000, 0x6000, 0),
                _FakeSegment(0x9300, 0x9600, 1),
            ],
        )

        self.assertEqual("vt_high", result["vtable_symbol"])
        self.assertEqual("0x5010", result["vtable_va"])


if __name__ == "__main__":
    unittest.main()
