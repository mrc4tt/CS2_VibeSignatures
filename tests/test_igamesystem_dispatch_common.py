import importlib
import json
import types
import unittest
from unittest.mock import AsyncMock, patch


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


class TestSourceString(unittest.IsolatedAsyncioTestCase):
    """source_string: the dispatch source is the one function referencing a string."""

    async def _run(self, located, tmpdir):
        import os
        import yaml

        module = _load_module()
        with open(os.path.join(tmpdir, "IGameSystem_vtable.linux.yaml"), "w", encoding="utf-8") as handle:
            yaml.safe_dump({"vtable_entries": {51: "0xa347f0"}}, handle)
        built = []

        def build(source_func_va, via_internal_wrapper, platform):
            built.append(source_func_va)
            return "dispatch"

        # the second py_eval (the dispatch scan) answers nothing, so the run stops there
        calls = AsyncMock(side_effect=[located, None])
        with patch.object(module, "_call_py_eval_json", calls), patch.object(module, "_build_dispatch_py_eval", build):
            ok = await module.preprocess_igamesystem_dispatch_skill(
                session=object(),
                expected_outputs=[os.path.join(tmpdir, "IGameSystem_OnRestoreGame.linux.yaml")],
                new_binary_dir=tmpdir,
                platform="linux",
                image_base=0,
                source_yaml_stem="CSource2Server_OnStreamEntitiesFromFileCompleted",  # no YAML on purpose
                target_specs=[{"target_name": "IGameSystem_OnRestoreGame"}],
                via_internal_wrapper=False,
                internal_rename_to=None,
                multi_order="scan",
                source_string="%s:  EndRestoreEntities( %s%s )\n",
            )
        return ok, built, calls

    async def test_the_one_referencing_function_is_scanned(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            ok, built, calls = await self._run({"funcs": ["0x170d090"]}, tmpdir)
        self.assertFalse(ok)
        self.assertEqual(["0x170d090"], built)
        self.assertIn("EndRestoreEntities", calls.call_args_list[0].args[1])

    async def test_an_ambiguous_string_stops_before_scanning(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            ok, built, calls = await self._run({"funcs": ["0x1", "0x2"]}, tmpdir)
        self.assertFalse(ok)
        self.assertEqual([], built)
        self.assertEqual(1, calls.call_count)


class TestFuncSigPlatforms(unittest.IsolatedAsyncioTestCase):
    """func_sig_platforms: a boundary-crossing func_sig on the named platforms only."""

    async def _run(self, platform):
        import os
        from tempfile import TemporaryDirectory

        import yaml

        module = _load_module()
        with TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, f"IGameSystem_vtable.{platform}.yaml"), "w", encoding="utf-8") as handle:
                yaml.safe_dump({"vtable_entries": {51: "0x180158980"}}, handle)
            output = os.path.join(tmpdir, f"IGameSystem_OnRestoreGame.{platform}.yaml")
            located = {"funcs": ["0x180bfa370"]}
            scanned = {"entries": [{"vfunc_offset": 408, "vfunc_index": 51}]}
            gen = AsyncMock(return_value={"func_sig": "C2 ?? ?? CC 40 55"})
            with (
                patch.object(module, "_call_py_eval_json", AsyncMock(side_effect=[located, scanned])),
                patch.object(
                    module, "_query_func_info", AsyncMock(return_value={"func_va": "0x180158980", "func_size": "0x3"})
                ),
                patch.object(module, "_rename_func_best_effort", AsyncMock()),
                patch.object(module, "preprocess_gen_func_sig_via_mcp", gen),
            ):
                ok = await module.preprocess_igamesystem_dispatch_skill(
                    session=object(),
                    expected_outputs=[output],
                    new_binary_dir=tmpdir,
                    platform=platform,
                    image_base=0x180000000,
                    source_yaml_stem="unused",
                    target_specs=[{"target_name": "IGameSystem_OnRestoreGame", "func_sig_platforms": ["windows"]}],
                    via_internal_wrapper=False,
                    internal_rename_to=None,
                    multi_order="scan",
                    source_string="%s:  EndRestoreEntities( %s%s )\n",
                )
            with open(output, encoding="utf-8") as handle:
                written = yaml.safe_load(handle)
        return ok, written, gen

    async def test_named_platform_gets_a_boundary_crossing_sig(self) -> None:
        ok, written, gen = await self._run("windows")
        self.assertTrue(ok)
        self.assertEqual(51, written["vfunc_index"])
        self.assertEqual("C2 ?? ?? CC 40 55", written["func_sig"])
        self.assertTrue(written["func_sig_allow_across_function_boundary"])
        self.assertTrue(gen.call_args.kwargs["allow_across_function_boundary"])

    async def test_other_platform_stays_slot_only(self) -> None:
        ok, written, gen = await self._run("linux")
        self.assertTrue(ok)
        self.assertNotIn("func_sig", written)
        gen.assert_not_called()
