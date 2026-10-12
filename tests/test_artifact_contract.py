import os
import unittest
from tempfile import TemporaryDirectory

import yaml

import artifact_contract
from artifact_contract import artifact_contract_issues

VFUNC = {
    "func_name": "CBaseEntity_OnTakeDamage",
    "vtable_name": "CBaseEntity",
    "vfunc_offset": "0x410",
    "vfunc_index": 130,
    "vfunc_sig": "FF 90 10 04 00 00 48 63 05 ?? ?? ?? ??",
}
CONTRACT = {
    "CBaseEntity_OnTakeDamage": (
        frozenset({"func_name", "vtable_name", "vfunc_offset", "vfunc_index", "vfunc_sig"}),
        frozenset({"vfunc_sig_allow_across_function_boundary"}),
    )
}


class TestArtifactContract(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.new = os.path.join(self._tmp.name, "new")
        self.old = os.path.join(self._tmp.name, "old")
        os.makedirs(self.new)
        os.makedirs(self.old)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, directory, name, data):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle)
        return path

    def _issues(self, new_doc, old_doc=VFUNC, name="CBaseEntity_OnTakeDamage.windows.yaml", declared=CONTRACT):
        if old_doc is not None:
            self._write(self.old, name, old_doc)
        path = self._write(self.new, name, new_doc)
        return artifact_contract_issues([path], "windows", self.old, declared=declared)

    def test_a_relocated_record_passes(self):
        moved = dict(VFUNC, vfunc_index=131, vfunc_offset="0x418")
        self.assertEqual([], self._issues(moved))

    def test_the_14190_agent_record_is_rejected_three_ways(self):
        agent = {
            "func_name": "CBasePlayerPawn_OnTakeDamage",
            "func_va": "0x180b5fc10",
            "func_rva": "0xb5fc10",
            "func_size": "0x1ce",
            "vtable_name": "CBasePlayerPawn",
            "vfunc_offset": "0x410",
            "vfunc_index": 130,
        }
        issues = " | ".join(self._issues(agent))
        self.assertIn("func_name is 'CBasePlayerPawn_OnTakeDamage'", issues)
        self.assertIn("vtable_name is 'CBasePlayerPawn'", issues)
        self.assertIn("not declared: func_rva, func_va", issues)
        self.assertIn("dropped since the previous gamever: vfunc_sig", issues)

    def test_a_previous_gamevers_name_is_kept(self):
        # upstream's CLoopTypeBase_FrameUpdate artifacts carry func_name CLoopTypeBase_Update
        old = dict(VFUNC, func_name="CBaseEntity_OnTakeDamageOld")
        self.assertEqual([], self._issues(dict(old), old_doc=old))

    def test_an_optional_flag_and_func_size_are_allowed(self):
        new = dict(VFUNC, vfunc_sig_allow_across_function_boundary=True, func_size="0x0")
        self.assertEqual([], self._issues(new))

    def test_a_field_neither_build_has_is_not_reported(self):
        # a thunk that cannot be signatured: deterministic producers leave it out too
        old = {k: v for k, v in VFUNC.items() if k != "vfunc_sig"}
        self.assertEqual([], self._issues(dict(old), old_doc=old))

    def test_without_a_task_the_previous_gamevers_fields_are_the_contract(self):
        issues = self._issues(dict(VFUNC, func_sig="48 8B"), declared={})
        self.assertEqual(1, len(issues))
        self.assertIn("not declared: func_sig", issues[0])

    def test_a_new_symbol_is_only_name_checked(self):
        self.assertEqual([], self._issues(dict(VFUNC, extra_field=1), old_doc=None, declared={}))
        issues = self._issues(dict(VFUNC, func_name="Other"), old_doc=None, declared={})
        self.assertIn("func_name is 'Other'", issues[0])

    def test_signature_flags_are_always_allowed(self):
        new = dict(VFUNC, vfunc_sig_max_match=2, func_sig_allow_across_function_boundary=True)
        self.assertEqual([], self._issues(new))

    def test_undeclared_fields_are_stripped_not_rejected(self):
        # the hunter's CEntitySystem_Activate.linux: right slot, plus a func_sig nobody declared
        path = self._write(self.new, "CBaseEntity_OnTakeDamage.windows.yaml", dict(VFUNC, func_sig="48 8B", func_va="0x1"))
        removed = artifact_contract.strip_undeclared_fields([path], "windows", declared=CONTRACT)
        self.assertEqual({path: ["func_sig", "func_va"]}, removed)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(VFUNC, yaml.safe_load(handle))
        self.assertEqual([], artifact_contract_issues([path], "windows", self.old, declared=CONTRACT))

    def test_strip_leaves_undeclared_symbols_alone(self):
        path = self._write(self.new, "Unknown.windows.yaml", {"func_name": "Unknown", "x": 1})
        self.assertEqual({}, artifact_contract.strip_undeclared_fields([path], "windows", declared=CONTRACT))

    def test_declared_fields_parse_optional_markers(self):
        artifact_contract.declared_artifact_fields.cache_clear()
        declared = artifact_contract.declared_artifact_fields()
        self.assertGreater(len(declared), 1000)
        for required, optional in declared.values():
            self.assertFalse(any(field.endswith("?") or ":" in field for field in required | optional))


if __name__ == "__main__":
    unittest.main()
