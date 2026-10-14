"""audit_shape_drift reports a shipped function whose callees, strings or constants mostly
did not survive, and stays quiet when code merely moved or a class layout shifted."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_shape_drift as S  # noqa: E402


def shape(callees=(), strings=(), consts=(), size=0x100):
    return {"callees": set(callees), "strings": set(strings), "consts": set(consts), "size": size}


class CompareTests(unittest.TestCase):
    def test_unchanged_function_is_quiet(self):
        a = shape(["F", "G", "H"], ["one", "two", "three"], [16, 24, 32])
        self.assertEqual(S.compare_shapes(a, a), [])

    def test_lost_strings_are_reported(self):
        a = shape(strings=["CNetworkGameServer::PackEntities", "PackEntities_Normal", "x.cpp"])
        b = shape(strings=["CheckTransmit", "ComputeClientPacks", "sv_packedentities.cpp"])
        self.assertEqual([m[0] for m in S.compare_shapes(a, b)], ["strings"])

    def test_class_layout_shift_is_not_a_change(self):
        a = shape(consts=[2016, 2040, 2076, 2092])
        b = shape(consts=[2024, 2048, 2084, 2100])
        self.assertEqual(S.compare_shapes(a, b), [])

    def test_small_constants_must_match_exactly(self):
        a = shape(consts=[16, 24, 35, 40])
        b = shape(consts=[104, 112, 348, 448])
        self.assertEqual([m[0] for m in S.compare_shapes(a, b)], ["consts"])

    def test_size_alone_is_not_reported(self):
        self.assertEqual(S.compare_shapes(shape(size=0x29a), shape(size=0x2f)), [])

    def test_size_supports_another_component(self):
        a = shape(strings=["a1", "a2", "a3"], size=0xfd9)
        b = shape(strings=["b1", "b2", "b3"], size=0x4e9)
        self.assertEqual([m[0] for m in S.compare_shapes(a, b)], ["strings", "size"])

    def test_too_little_to_judge_is_quiet(self):
        self.assertEqual(S.compare_shapes(shape(callees=["F"]), shape(callees=["G"])), [])


if __name__ == "__main__":
    unittest.main()
