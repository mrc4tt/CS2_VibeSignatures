"""Template RTTI, the data-pointer table and call-chain strategies, on tiny fake binaries.

The template case is the one that kept CGameSystemReallocatingFactory<X>'s
CreateGameSystem / DestroyGameSystem for an agent on every build: the binary spells
the template with all its arguments and back-references, never as `<len><name>`.
"""
import os
import struct
import tempfile
import unittest

import hunt_core as H
from tests.test_hunt_strategies import FakeBinary, facts_of, hunter


class DataBinary(FakeBinary):
    """FakeBinary whose data region can hold pointers, read back by qword()."""

    def qword(self, ea):
        off = ea - self.DATA
        if 0 <= off and off + 8 <= len(self.data):
            return struct.unpack_from("<Q", self.data, off)[0]
        return None

    def put_qwords(self, values):
        while len(self.data) % 8:
            self.data += b"\0"
        at = self.DATA + len(self.data)
        for value in values:
            self.data += struct.pack("<Q", value)
        return at


class TokenTests(unittest.TestCase):
    def test_itanium_back_reference_is_left_out(self):
        self.assertEqual(["CGameSystemReallocatingFactory", "CCSEventLog"],
                         H.itanium_tokens("30CGameSystemReallocatingFactoryI11CCSEventLogS0_E"))
        self.assertEqual(["CGameSystemReallocatingFactory", "CPVSManager", "IPVSManager"],
                         H.itanium_tokens("30CGameSystemReallocatingFactoryI11CPVSManager11IPVSManagerE"))

    def test_msvc_back_reference_and_type_codes_are_left_out(self):
        self.assertEqual(["CGameSystemReallocatingFactory", "CCheckClient"],
                         H.msvc_tokens(".?AV?$CGameSystemReallocatingFactory@VCCheckClient@@V1@@@"))

    def test_a_short_template_name_matches_its_unique_prefix(self):
        candidates = [(1, ["F", "A"]), (2, ["F", "B", "IB"]), (3, ["F", "C"]), (4, ["F", "C", "D"])]
        self.assertEqual([1], H._template_name_matches(candidates, ["F", "A"]))
        self.assertEqual([2], H._template_name_matches(candidates, ["F", "B"]))
        self.assertEqual([3], H._template_name_matches(candidates, ["F", "C"]))  # exact beats prefix

    def test_artifact_stems(self):
        self.assertEqual(["CGameSystemReallocatingFactory<CSource2EntitySystem>",
                          "CGameSystemReallocatingFactory_CSource2EntitySystem"],
                         H.vtable_artifact_stems("CGameSystemReallocatingFactory<CSource2EntitySystem>_vtable"))
        self.assertEqual(["CBaseEntity"], H.vtable_artifact_stems("CBaseEntity"))


class TemplateRttiTests(unittest.TestCase):
    def test_itanium_template_vtable_is_found_by_its_identifiers(self):
        binary = DataBinary({0x1000: {"pad": 2}})
        binary.input_path = lambda: "libserver.so"
        binary.data += b"\0"
        name_ea = binary.DATA + len(binary.data)
        binary.data += b"30CGameSystemReallocatingFactoryI20CSource2EntitySystemS0_E\0"
        typeinfo = binary.put_qwords([0xDEAD, name_ea])
        vtable = binary.put_qwords([0, typeinfo, 0x1000])
        found = H.rtti_vtables(binary, "CGameSystemReallocatingFactory<CSource2EntitySystem>")
        self.assertEqual([(vtable + 16, 0)], found)

    def test_angle_bracket_name_finds_the_underscore_artifact(self):
        binary = DataBinary({0x1000: {"pad": 2}})
        table = binary.put_qwords([0x1000])
        with tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, "CGameSystemReallocatingFactory_CSource2EntitySystem_vtable.windows.yaml"), "w") as handle:
                handle.write(f"vtable_class: CGameSystemReallocatingFactory_CSource2EntitySystem\nvtable_va: '{hex(table)}'\n")
            h, _ = hunter(binary, {"gamever": "1", "symbols": {}}, out)
            self.assertEqual(table, h.vtable_from_artifact("CGameSystemReallocatingFactory<CSource2EntitySystem>"))


class DataPtrTests(unittest.TestCase):
    """A callback table [Before, Target, After]: it moved, its order did not."""

    def setUp(self):
        self.old = DataBinary({0x100: {"pad": 3}, 0x200: {"pad": 5, "consts": [0x1234]}, 0x300: {"pad": 4}})
        self.old.put_qwords([0x100, 0x200, 0x300])
        fb = H.FactsBuilder(self.old)
        names = {0x100: "Before", 0x200: "Target", 0x300: "After"}
        self.facts = facts_of(self.old, {"Before": 0x100, "Target": 0x200, "After": 0x300})
        self.facts["symbols"]["Target"]["data_holders"] = fb.data_holders(0x200, names, self.old.data_regions())
        self.new = DataBinary({0x1100: {"pad": 3}, 0x1250: {"pad": 5, "consts": [0x1234]}, 0x1300: {"pad": 4}})
        self.new.put_qwords([0xAAAA, 0x1100, 0x1250, 0x1300])

    def test_baseline_records_the_table_neighbours(self):
        holders = self.facts["symbols"]["Target"]["data_holders"]
        self.assertEqual([[-1, "Before"], [1, "After"]], holders[0]["neighbours"])

    def test_two_found_neighbours_point_at_the_target(self):
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(self.new, self.facts, out, resolved={"Before": 0x1100, "After": 0x1300})
            self.assertEqual([(0x1250, "data-ptr 2 table neighbours")],
                             h.s_dataptr("Target", self.facts["symbols"]["Target"], {}))
            self.assertIn("data-ptr", H.Hunter._strong_families(["data-ptr 2 table neighbours"]))

    def test_one_neighbour_is_not_enough(self):
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(self.new, self.facts, out, resolved={"Before": 0x1100})
            self.assertEqual([], h.s_dataptr("Target", self.facts["symbols"]["Target"], {}))
        self.assertNotIn("data-ptr", H.Hunter._strong_families(["data-ptr 1 table neighbours"]))


class CallChainTests(unittest.TestCase):
    """Known Root -> unnamed Middle (2nd call) -> Target (1st call)."""

    def setUp(self):
        self.old = FakeBinary({
            0x100: {"calls": [0x900, 0x200], "pad": 2},          # Root
            0x200: {"calls": [0x300, 0x910], "pad": 3},          # Middle (unnamed)
            0x300: {"consts": [0x4321, 0x88], "pad": 6},          # Target
            0x900: {}, 0x910: {},
        })
        fb = H.FactsBuilder(self.old)
        names = {0x100: "Root", 0x300: "Target"}
        self.facts = facts_of(self.old, {"Root": 0x100, "Target": 0x300})
        self.facts["symbols"]["Target"]["call_chains"] = fb.call_chains(0x300, names)
        self.new = FakeBinary({
            0x1100: {"calls": [0x1900, 0x1200], "pad": 2},
            0x1200: {"calls": [0x1350, 0x1910], "pad": 3},
            0x1350: {"consts": [0x4321, 0x88], "pad": 6},
            0x1900: {}, 0x1910: {},
        })

    def test_baseline_records_the_chain_through_the_unnamed_caller(self):
        self.assertEqual([[["Root", 1], 0]], self.facts["symbols"]["Target"]["call_chains"])

    def test_chain_is_walked_down_from_the_found_root(self):
        with tempfile.TemporaryDirectory() as out:
            h, _ = hunter(self.new, self.facts, out, resolved={"Root": 0x1100})
            got = h.s_callchain("Target", self.facts["symbols"]["Target"], {})
            self.assertEqual(0x1350, got[0][0])
            self.assertTrue(got[0][1].startswith("callchain 1 from Root"))

    def test_a_direct_named_caller_is_left_to_callgraph(self):
        fb = H.FactsBuilder(self.old)
        self.assertEqual([], fb.call_chains(0x200, {0x100: "Root", 0x200: "Middle"}))


if __name__ == "__main__":
    unittest.main()
