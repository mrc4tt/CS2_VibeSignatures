"""hunt_core's strategies for the cases relocation cannot settle, on a tiny fake binary.

Twins (sibling-callees), inlined functions, the layout fingerprint (consts), symbols
with no baseline (the same build's other platform).
"""
import os
import tempfile
import unittest

import hunt_core as H


class Op:
    def __init__(self, kind, offb=-1, value=None, addr=None, rip=False):
        self.kind, self.offb, self.value, self.addr, self.rip = kind, offb, value, addr, rip


class Insn:
    def __init__(self, ea, mnem, ops=(), raw=b"\x90"):
        self.ea, self.size, self.mnem, self.raw, self.ops = ea, len(raw), mnem, raw, list(ops)


class FakeBinary:
    """functions: {start: {"calls": [target], "strings": [text], "consts": [v], "vcalls": [off], "pad": n}}.
    Every instruction is one byte; string literals live in one data region."""

    DATA = 0x900000

    def __init__(self, functions):
        self.funcs, self.items, self.insns = {}, {}, {}
        self.data = bytearray(b"\0")
        self.string_ea = {}
        for start in sorted(functions):
            spec = functions[start]
            ea, items = start, []

            def put(insn):
                nonlocal ea
                self.insns[ea] = insn
                items.append(ea)
                ea += 1

            put(Insn(ea, "push"))
            for text in spec.get("strings", ()):
                if text not in self.string_ea:
                    self.string_ea[text] = self.DATA + len(self.data)
                    self.data += text.encode() + b"\0"
                put(Insn(ea, "lea", [Op("mem", 3, addr=self.string_ea[text], rip=True)]))
            for value in spec.get("consts", ()):
                put(Insn(ea, "mov", [Op("displ", 2, addr=value)]))
            for off in spec.get("vcalls", ()):
                put(Insn(ea, "call", [Op("displ", 2, addr=off)]))
            for target in spec.get("calls", ()):
                put(Insn(ea, "call", [Op("near", 1, addr=target)]))
            for _ in range(spec.get("pad", 0)):
                put(Insn(ea, "nop"))
            put(Insn(ea, "ret"))
            self.funcs[start] = ea
            self.items[start] = items

    # -- Backend protocol
    def exec_regions(self):
        return [(0x1000, b"\xcc" * 64)]

    def data_regions(self):
        return [(self.DATA, bytes(self.data))]

    def get_func(self, ea):
        for start, end in self.funcs.items():
            if start <= ea < end:
                return start, end
        return None

    def next_func(self, ea):
        later = [s for s in self.funcs if s > ea]
        return min(later) if later else None

    def func_items(self, start):
        return list(self.items.get(start, []))

    def insn(self, ea):
        return self.insns.get(ea)

    def string_at(self, ea):
        for text, at in self.string_ea.items():
            if at == ea:
                return text
        return None

    def data_refs_from(self, ea):
        insn = self.insns.get(ea)
        return [op.addr for op in insn.ops if op.rip] if insn else []

    def code_refs_to(self, target):
        return [ea for ea, insn in self.insns.items() if insn.mnem == "call"
                and any(op.kind == "near" and op.addr == target for op in insn.ops)]

    def xrefs_to(self, target):
        return [ea for ea, insn in self.insns.items() if any(op.rip and op.addr == target for op in insn.ops)]

    def qword(self, ea):
        return None

    def is_code(self, ea):
        return self.get_func(ea) is not None

    def imagebase(self):
        return 0


def facts_of(binary, symbols):
    """Baseline facts {symbol: function_facts} for {symbol: va} on a fake binary."""
    fb = H.FactsBuilder(binary)
    va_to_symbol = {va: name for name, va in symbols.items()}
    out = {}
    for name, va in symbols.items():
        entry = fb.function_facts(va, va_to_symbol)
        entry["category"] = "func"
        out[name] = entry
    return {"gamever": "1", "platform": "windows", "symbols": out}


def hunter(binary, facts, out_dir, resolved=None, sister=None):
    emitted = {}

    def emit(symbol, rule):
        emitted[symbol] = rule["ea"]
        return f"{symbol}.yaml"

    h = H.Hunter(binary, "2", "server", "windows", facts, out_dir, emit=emit, log=lambda *_: None, sister_facts=sister)
    for name, va in (resolved or {}).items():
        h.resolved[name] = va
        h.resolved_va[va] = name
    return h, emitted


class TwinTests(unittest.TestCase):
    """Two template twins, identical but for their helpers; each has a found sibling."""

    def setUp(self):
        # baseline: helpers A1 A2 (string family) and B1 B2 (class family)
        self.old = FakeBinary({
            0x100: {"calls": [0x900, 0x910], "pad": 4},            # SetString (sibling)
            0x200: {"calls": [0x900, 0x910, 0x990], "pad": 9},     # SetStringForPlayer
            0x300: {"calls": [0x920, 0x930], "pad": 4},            # SetClass (sibling)
            0x400: {"calls": [0x920, 0x930, 0x990], "pad": 9},     # SetClassForPlayer
            0x900: {}, 0x910: {}, 0x920: {}, 0x930: {}, 0x990: {},
        })
        self.facts = facts_of(self.old, {"SetString": 0x100, "SetStringForPlayer": 0x200,
                                         "SetClass": 0x300, "SetClassForPlayer": 0x400})
        # new build: everything moved, the twins swapped places
        self.new = FakeBinary({
            0x1100: {"calls": [0x1900, 0x1910], "pad": 4},
            0x1200: {"calls": [0x1920, 0x1930, 0x1990], "pad": 9},  # class twin now first
            0x1300: {"calls": [0x1920, 0x1930], "pad": 4},
            0x1400: {"calls": [0x1900, 0x1910, 0x1990], "pad": 9},  # string twin
            0x1900: {}, 0x1910: {}, 0x1920: {}, 0x1930: {}, 0x1990: {},
        })

    def test_each_twin_goes_to_the_function_calling_its_siblings_helpers(self):
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(self.new, self.facts, out, resolved={"SetString": 0x1100, "SetClass": 0x1300})
            base = self.facts["symbols"]
            self.assertEqual(h.s_siblingcallees("SetStringForPlayer", base["SetStringForPlayer"], {}),
                             [(0x1400, "sibling-callees 2 shared helpers")])
            self.assertEqual(h.s_siblingcallees("SetClassForPlayer", base["SetClassForPlayer"], {})[0][0], 0x1200)

    def test_no_vote_without_a_found_sibling(self):
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(self.new, self.facts, out)
            self.assertEqual(h.s_siblingcallees("SetStringForPlayer", self.facts["symbols"]["SetStringForPlayer"], {}), [])

    def test_sibling_callees_is_a_strong_family(self):
        self.assertIn("sibling-callees", H.Hunter._strong_families(["sibling-callees 3 shared helpers"]))


class InlinedTests(unittest.TestCase):
    STRINGS = ["ParseNetadrList: bad address", "ParseNetadrList: too many entries"]

    def test_strings_moved_into_a_found_function(self):
        old = FakeBinary({0x100: {"strings": self.STRINGS, "pad": 2}})
        facts = facts_of(old, {"ParseNetadrList": 0x100})
        new = FakeBinary({0x1000: {"strings": self.STRINGS + ["connect %s"], "pad": 40}})
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(new, facts, out, resolved={"ConnectSocketToAddressList": 0x1000})
            va, why = h.inlined_into("ParseNetadrList", facts["symbols"]["ParseNetadrList"])
        self.assertEqual(va, 0x1000)
        self.assertIn("ConnectSocketToAddressList", why)

    def test_same_sized_function_with_its_strings_is_not_inlined(self):
        old = FakeBinary({0x100: {"strings": self.STRINGS, "pad": 2}})
        facts = facts_of(old, {"ParseNetadrList": 0x100})
        new = FakeBinary({0x1000: {"strings": self.STRINGS, "pad": 2}})
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(new, facts, out)
            self.assertIsNone(h.inlined_into("ParseNetadrList", facts["symbols"]["ParseNetadrList"]))


class ConstsTests(unittest.TestCase):
    LAYOUT = [0x4c8, 0x4d0, 0x529, 0x198, 0x530, 0x600]

    def _run(self, candidates):
        old = FakeBinary({0x100: {"pad": 2}, 0x200: {"consts": self.LAYOUT, "pad": 3}, 0x300: {"pad": 2}})
        facts = facts_of(old, {"Before": 0x100, "Target": 0x200, "After": 0x300})
        new = FakeBinary({0x1000: {"pad": 2}, **candidates, 0x1900: {"pad": 2}})
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(new, facts, out, resolved={"Before": 0x1000, "After": 0x1900})
            return h.s_consts("Target", facts["symbols"]["Target"], {})

    def test_unique_layout_match_votes(self):
        got = self._run({0x1100: {"consts": [0x10000], "pad": 3}, 0x1200: {"consts": self.LAYOUT, "pad": 5}})
        self.assertEqual(got[0][0], 0x1200)
        self.assertTrue(got[0][1].startswith("consts 1.00"))

    def test_twins_tie_and_do_not_vote(self):
        self.assertEqual(self._run({0x1100: {"consts": self.LAYOUT}, 0x1200: {"consts": self.LAYOUT}}), [])


class NewSymbolTests(unittest.TestCase):
    def _facts(self):
        return {"gamever": "1", "platform": "linux", "symbols": {}}

    def test_other_platform_strings_transfer(self):
        strings = ["Blocking load because marked", "CreateWorld_Internal( %s )", "world load failed: %s"]
        linux = FakeBinary({0x500: {"strings": strings, "pad": 3}})
        sister = facts_of(linux, {"CreateWorld": 0x500})
        sister["platform"], sister["gamever"] = "linux", "2"
        windows = FakeBinary({0x7000: {"pad": 3}, 0x8000: {"strings": strings, "pad": 6}})
        with tempfile.TemporaryDirectory() as out:
            h, emitted = hunter(windows, self._facts(), out, sister=sister)
            h.run(["CreateWorld"], categories={"CreateWorld": "func"})
        self.assertEqual(emitted, {"CreateWorld": 0x8000})

    def test_no_evidence_asks_for_an_anchor(self):
        with tempfile.TemporaryDirectory() as out:
            h, emitted = hunter(FakeBinary({0x1000: {}}), self._facts(), out)
            h.run(["Nothing_Known"], categories={"Nothing_Known": "gv"})
        self.assertEqual(emitted, {})
        self.assertIn("anchor", h.report["unresolved"][0]["why"])


if __name__ == "__main__":
    unittest.main()


class SharedStubTests(unittest.TestCase):
    """_purecall fills hundreds of vtable slots on engine2.dll 14182; never one symbol."""

    def test_many_vtable_slots_mark_a_shared_stub(self):
        import struct
        binary = FakeBinary({0x1000: {"pad": 2}, 0x2000: {"pad": 2}})
        binary.data += struct.pack("<Q", 0x1000) * 40 + struct.pack("<Q", 0x2000) * 2
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(binary, {"gamever": "1", "symbols": {}}, out)
            self.assertTrue(h.is_shared_stub(0x1000))
            self.assertFalse(h.is_shared_stub(0x2000))


class TemplateVtableTests(unittest.TestCase):
    """RTTI cannot name CLoopModeFactory<CLoopModeGame>; this build's vtable artifact can."""

    def test_vtable_artifact_is_the_fallback(self):
        binary = FakeBinary({0x1000: {"pad": 2}})
        binary.qword = lambda ea: 0x1000 if ea == 0x5000 else None
        with tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, "CLoopModeFactory_CLoopModeGame_vtable.windows.yaml"), "w") as handle:
                handle.write("vtable_class: CLoopModeFactory_CLoopModeGame\nvtable_va: '0x5000'\n")
            h, _ = hunter(binary, {"gamever": "1", "symbols": {}}, out)
            self.assertEqual(h.vtable_from_artifact("CLoopModeFactory_CLoopModeGame_vtable"), 0x5000)
            self.assertEqual(h.vtable_from_artifact("CLoopModeFactory_CLoopModeGame"), 0x5000)
            self.assertIsNone(h.vtable_from_artifact("Other_vtable"))


class ParseYamlTests(unittest.TestCase):
    def test_folded_signature_and_nested_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.yaml")
            with open(path, "w") as handle:
                handle.write("func_name: X\nvfunc_sig: FF 50 08 EB ?? 48\n  FF 50 ?? EB\nvtable_entries:\n  0: '0x10'\n"
                             "vfunc_index: 1\n")
            got = H.parse_yaml(path)
        self.assertEqual(got["vfunc_sig"], "FF 50 08 EB ?? 48 FF 50 ?? EB")   # both lines, not the first
        self.assertEqual(got["vtable_entries"], "")
        self.assertEqual(got["vfunc_index"], "1")


class SlotOnlyTests(unittest.TestCase):
    def test_interface_slot_follows_the_sibling_that_shared_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = os.path.join(tmp, "old"), os.path.join(tmp, "new")
            os.makedirs(old), os.makedirs(new)
            for folder, index in ((old, 1), (new, 2)):
                with open(os.path.join(folder, "CBase_SetX.windows.yaml"), "w") as handle:
                    handle.write(f"vtable_name: CBase\nvfunc_index: {index}\n")
            h, _ = hunter(FakeBinary({0x1000: {}}), {"gamever": "1", "symbols": {}}, new)
            h.baseline_artifact_dir = old
            self.assertTrue(h.relocate_slot_only("IBase_SetX", {"vtable_name": "IBase", "vfunc_index": "1"}))
            got = H.parse_yaml(os.path.join(new, "IBase_SetX.windows.yaml"))
        self.assertEqual((got["vfunc_index"], got["vfunc_offset"], got["vtable_name"]), ("2", "0x10", "IBase"))


class VcallVariantTests(unittest.TestCase):
    def test_displacement_wildcards(self):
        self.assertEqual(H.vcall_disp_variants("FF 90 E8 00 00 00 48 8B D8"), ["FF 90 ?? ?? ?? ?? 48 8B D8"])
        self.assertEqual(H.vcall_disp_variants("FF 50 48 83 F8"), ["FF 50 ?? 83 F8", "FF 90 ?? ?? ?? ?? 83 F8"])
        self.assertEqual(H.vcall_disp_variants("48 8B 01 FF 50 08"), [])      # not starting at the call
        self.assertEqual(H.vcall_disp_variants("FF 60 08"), [])               # jmp, not call


class SameLayoutTests(unittest.TestCase):
    """IGameSystem on windows 14182: 65 slots, many identical `ret` stubs - neighbour
    agreement cannot pick one, an unchanged layout can."""

    def _setup(self, extra_slot=False):
        functions = {0x1000 + 0x100 * i: {"pad": i % 3} for i in range(10)}
        binary = FakeBinary(functions)
        fns = sorted(functions)
        live = fns + ([0x1000] if extra_slot else [])
        table = {0x9000 + 8 * i: fn for i, fn in enumerate(live)}
        binary.qword = lambda ea: table.get(ea)
        facts = {"gamever": "1", "symbols": {},
                 "vtables": {"IGameSystem": {"slots": [[hex(f), H.masked_head(binary, f, limit=16), None] for f in fns]}}}
        return binary, facts, fns

    def _hunter(self, binary, facts, out):
        with open(os.path.join(out, "IGameSystem_vtable.windows.yaml"), "w") as handle:
            handle.write("vtable_va: '0x9000'\n")
        return hunter(binary, facts, out)[0]

    def test_unchanged_layout_gives_the_slot(self):
        binary, facts, fns = self._setup()
        with tempfile.TemporaryDirectory() as out:
            h = self._hunter(binary, facts, out)
            got = h.s_samelayout("IGameSystem_X", {"category": "vfunc", "vtable_name": "IGameSystem", "vfunc_index": 6}, {})
        self.assertEqual(got, [(fns[6], "vtable-layout unchanged (10/10 slots)")])

    def test_an_added_slot_means_no_vote(self):
        binary, facts, _ = self._setup(extra_slot=True)
        with tempfile.TemporaryDirectory() as out:
            h = self._hunter(binary, facts, out)
            self.assertEqual(h.s_samelayout("IGameSystem_X", {"category": "vfunc", "vtable_name": "IGameSystem",
                                                              "vfunc_index": 6}, {}), [])


class SlotWindowTests(unittest.TestCase):
    """vtidx_PlayerRunCommand: a func record that sat in CCSPlayer_MovementServices[25];
    the table gained a slot elsewhere, the window around 25 kept its code."""

    def _run(self, live_order):
        functions = {0x1000 + 0x100 * i: {"pad": i} for i in range(9)}
        binary = FakeBinary(functions)
        fns = sorted(functions)
        facts = {"gamever": "1", "symbols": {},
                 "vtables": {"C": {"slots": [[hex(f), H.masked_head(binary, f, limit=16), None] for f in fns]}}}
        live = [fns[i] if i is not None else fns[0] for i in live_order]
        table = {0x9000 + 8 * k: fn for k, fn in enumerate(live)}
        binary.qword = lambda ea: table.get(ea)
        with tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, "C_vtable.windows.yaml"), "w") as handle:
                handle.write("vtable_va: '0x9000'\n")
            h, _ = hunter(binary, facts, out)
            return h.s_slotwindow("X", {"va": hex(fns[4])}, {}), fns

    def test_slot_found_after_an_insertion_before_it(self):
        got, fns = self._run([0, 1, None, 2, 3, 4, 5, 6, 7, 8])     # a new slot at 2
        self.assertEqual(got, [(fns[4], "vtable-window C[4]->[5] (5/5 slots around it unchanged)")])

    def test_window_broken_no_vote(self):
        got, _ = self._run([0, 1, 2, 3, 4, None, 6, 7, 8])          # slot 5's code changed
        self.assertEqual(got, [])
