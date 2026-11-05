"""The vfunc_sig fallback reuses an old slot index only when the matched call site
still uses that slot's offset.

It used to match the old call-site pattern and take the old index on trust, so a
pattern with wildcarded offset bytes (or one that now matches another call of the
same shape) carried a stale index forward after the class layout moved; only
validate_artifacts objected, after the run. Covered on both platforms, including
linux's Itanium member-function pointer form (offset + 1).
"""
import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ida_analyze_util  # noqa: E402

O_VOID, O_PHRASE, O_DISPL, O_IMM = 0, 3, 4, 5
F_ELF, F_PE = 18, 11


class _Op:
    def __init__(self, type_=O_VOID, addr=0, value=0):
        self.type, self.addr, self.value = type_, addr, value


def _run_check(program, start, sig_len, want, elf, sig_disp=None):
    """Execute build_vcall_offset_check_py against fake ida_ua/ida_ida modules.

    program: {ea: (size, [ops])}"""
    ida_ua = types.ModuleType("ida_ua")
    ida_ua.o_void, ida_ua.o_phrase, ida_ua.o_displ, ida_ua.o_imm = O_VOID, O_PHRASE, O_DISPL, O_IMM

    class insn_t:
        def __init__(self):
            self.ops = []

    def decode_insn(insn, ea):
        size, ops = program.get(ea, (0, []))
        insn.ops = list(ops) + [_Op()]
        return size

    ida_ua.insn_t, ida_ua.decode_insn = insn_t, decode_insn
    ida_ida = types.ModuleType("ida_ida")
    ida_ida.f_ELF = F_ELF
    ida_ida.inf_get_filetype = lambda: F_ELF if elf else F_PE
    saved = {name: sys.modules.get(name) for name in ("ida_ua", "ida_ida")}
    sys.modules.update(ida_ua=ida_ua, ida_ida=ida_ida)
    try:
        scope = {}
        exec(ida_analyze_util.build_vcall_offset_check_py(start, sig_len, want, sig_disp), scope)
        return json.loads(scope["result"])
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class CheckCodeTests(unittest.TestCase):
    def test_windows_call_through_the_slot(self):
        # mov rax,[rcx]; call [rax+0x120]
        program = {0x1000: (3, [_Op(O_DISPL, 0)]), 0x1003: (6, [_Op(O_DISPL, 0x120)])}
        self.assertTrue(_run_check(program, 0x1000, 9, 0x120, elf=False)["ok"])

    def test_a_moved_slot_is_refused_on_both_platforms(self):
        program = {0x1000: (6, [_Op(O_DISPL, 0x128)])}
        for elf in (False, True):
            with self.subTest(elf=elf):
                verdict = _run_check(program, 0x1000, 6, 0x120, elf=elf)
                self.assertFalse(verdict["ok"])
                self.assertEqual(verdict["seen"], [0x128])

    def test_linux_member_pointer_is_offset_plus_one(self):
        # mov qword ptr [rbp-0x38], 0x141 names slot 40 (0x140)
        program = {0x2000: (8, [_Op(O_DISPL, 0xFFFFFFC8), _Op(O_IMM, value=0x141)])}
        self.assertTrue(_run_check(program, 0x2000, 8, 0x140, elf=True)["ok"])
        self.assertFalse(_run_check(program, 0x2000, 8, 0x140, elf=False)["ok"])

    def test_sig_disp_pins_the_instruction(self):
        program = {0x1000: (6, [_Op(O_DISPL, 0x120)]), 0x1006: (6, [_Op(O_DISPL, 0x88)])}
        self.assertFalse(_run_check(program, 0x1000, 12, 0x120, elf=False, sig_disp=6)["ok"])
        self.assertTrue(_run_check(program, 0x1000, 12, 0x120, elf=False, sig_disp=0)["ok"])

    def test_slot_zero_through_a_bare_register(self):
        program = {0x1000: (2, [_Op(O_PHRASE)])}
        self.assertTrue(_run_check(program, 0x1000, 2, 0, elf=False)["ok"])


class _Result:
    def __init__(self, payload):
        self.content = [types.SimpleNamespace(text=json.dumps(payload))]
        self.isError = False


class FallbackTests(unittest.TestCase):
    def _relocate(self, platform, offset_ok):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / f"CFoo_Bar.{platform}.yaml"
            old_path.write_text(yaml.safe_dump({
                "func_name": "CFoo_Bar", "vfunc_sig": "48 8B 01 FF 90 ?? ?? ?? ??", "vtable_name": "CFoo",
                "vfunc_offset": "0x120", "vfunc_index": 36, "func_va": "0x180111111",
            }))
            (Path(temp_dir) / f"CFoo_vtable.{platform}.yaml").write_text(
                yaml.safe_dump({"vtable_entries": {36: "0x180222222"}}))
            calls = []

            async def fake(*, name, arguments):
                calls.append(name)
                if name == "find_bytes":
                    return _Result([{"matches": ["0x180012340"], "n": 1}])
                if "want = " in arguments.get("code", ""):
                    return _Result({"result": json.dumps({"ok": offset_ok, "seen": [0x120 if offset_ok else 0x128]})})
                if "get_func" in arguments.get("code", ""):
                    return _Result({"result": json.dumps({"func_va": "0x180222222", "func_size": "0x40"})})
                return _Result({"result": json.dumps({"func_sig": "48 89 5C 24 ??"})})

            session = AsyncMock()
            session.call_tool.side_effect = fake
            result = asyncio.run(ida_analyze_util.preprocess_func_sig_via_mcp(
                session=session, new_path=str(Path(temp_dir) / f"new.{platform}.yaml"), old_path=str(old_path),
                image_base=0x180000000, new_binary_dir=temp_dir, platform=platform))
            return result, calls

    def test_stale_slot_is_not_reused(self):
        for platform in ("windows", "linux"):
            with self.subTest(platform=platform):
                result, calls = self._relocate(platform, offset_ok=False)
                self.assertIsNone(result)
                self.assertEqual(calls, ["find_bytes", "py_eval"])

    def test_current_slot_still_relocates(self):
        for platform in ("windows", "linux"):
            with self.subTest(platform=platform):
                result, _ = self._relocate(platform, offset_ok=True)
                self.assertIsNotNone(result)
                self.assertEqual((result["vfunc_index"], result["func_va"]), (36, "0x180222222"))


if __name__ == "__main__":
    unittest.main()
