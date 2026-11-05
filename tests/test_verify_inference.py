"""The scanner recognises a key named after no record: by its method name when every
candidate ships the same value, or by the record whose function its signature lands on."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify_plugin_gamedata as VPG  # noqa: E402


def rec(symbol, module="server", **fields):
    return {"_symbol": symbol, "_module": module, **fields}


def make_index(*records_by_platform):
    index = {}
    for platform, record in records_by_platform:
        index.setdefault(record["_symbol"], {})[platform] = record
    return index


class InferByNameTests(unittest.TestCase):
    def setUp(self):
        VPG._INFER_CACHE.clear()
        self.index = make_index(
            ("linux", rec("CNetworkSystem_GetPublicAdr", "networksystem", vfunc_index=32)),
            ("linux", rec("INetworkMessageProcessingPreFilter_FilterMessage", "engine", func_va="0x1000")),
            ("linux", rec("CFoo_Twin", vfunc_index=4)),
            ("linux", rec("CBar_Twin", vfunc_index=5)),
            ("linux", rec("CA_Same", vfunc_index=7)),
            ("linux", rec("CB_Same", vfunc_index=7)),
        )

    def test_bare_method_name(self):
        record, how = VPG.infer_by_name(self.index, "GetPublicAdr", "linux", "offset")
        self.assertEqual(record["_symbol"], "CNetworkSystem_GetPublicAdr")
        self.assertTrue(how.startswith("name:"))

    def test_signature_kind_only_takes_functions(self):
        record, _ = VPG.infer_by_name(self.index, "FilterMessage", "linux", "signature")
        self.assertEqual(record["_symbol"], "INetworkMessageProcessingPreFilter_FilterMessage")
        self.assertIsNone(VPG.infer_by_name(self.index, "FilterMessage", "linux", "offset")[0])

    def test_disagreeing_candidates_are_left_alone(self):
        self.assertIsNone(VPG.infer_by_name(self.index, "Twin", "linux", "offset")[0])

    def test_agreeing_candidates_are_taken(self):
        self.assertEqual(VPG.infer_by_name(self.index, "Same", "linux", "offset")[0]["vfunc_index"], 7)

    def test_class_qualified_name_prefers_exact_class(self):
        record, _ = VPG.infer_by_name(self.index, "CFoo::Twin", "linux", "offset")
        self.assertEqual(record["_symbol"], "CFoo_Twin")

    def test_underscore_prefixed_key_is_its_own_name(self):
        # CNetworkSystem_GetPublicAdrX is a different name, not "GetPublicAdrX"'s method
        self.assertIsNone(VPG.infer_by_name(self.index, "CQux_GetPublicAdr", "linux", "offset")[0])

    def test_other_platform_does_not_answer(self):
        self.assertIsNone(VPG.infer_by_name(self.index, "GetPublicAdr", "windows", "offset")[0])


class InferByAddressTests(unittest.TestCase):
    def test_record_at_the_hit(self):
        VPG._INFER_CACHE.clear()
        index = make_index(("windows", rec("CThing_Do", "engine", func_va="0x180001000")))
        record, how = VPG.infer_by_address(index, "engine", "windows", 0x180001000)
        self.assertEqual(record["_symbol"], "CThing_Do")
        self.assertTrue(how.startswith("address:"))
        self.assertIsNone(VPG.infer_by_address(index, "server", "windows", 0x180001000)[0])
        self.assertIsNone(VPG.infer_by_address(index, "engine", "windows", 0x180001004)[0])


if __name__ == "__main__":
    unittest.main()
