"""ensure_seed_preprocessors -force may add a requested field but never removes one,
keeps a boundary flag's ":true", and does not floor a signature onto a slot-only vfunc."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ensure_seed_preprocessors as E  # noqa: E402


def artifact(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    handle.write(text)
    handle.close()
    return handle.name


class SeedForceTests(unittest.TestCase):
    def test_slot_only_vfunc_is_not_asked_for_a_signature(self):
        path = artifact("func_name: X\nvtable_name: C\nvfunc_offset: '0x8'\nvfunc_index: 1\n")
        fields = E.desired_fields([path], "vfunc")
        self.assertNotIn("func_sig", fields)
        self.assertIn("vfunc_index", fields)

    def test_boundary_flag_keeps_true(self):
        path = artifact("func_name: X\nfunc_va: '0x1'\nfunc_sig: AA BB\n"
                        "func_sig_allow_across_function_boundary: true\n")
        self.assertIn("func_sig_allow_across_function_boundary:true", E.desired_fields([path], "func"))

    def test_merge_never_drops_a_requested_field(self):
        current = ["func_name", "func_va", "func_sig", "func_sig_allow_across_function_boundary:true",
                   "vtable_name", "vfunc_offset", "vfunc_index"]
        derived = ["func_name", "vtable_name", "vfunc_offset", "vfunc_index"]
        self.assertEqual(E.merge_fields(current, derived, "vfunc"), current)

    def test_merge_adds_a_missing_field(self):
        current = ["struct_name", "member_name", "offset", "size", "offset_sig"]
        derived = current + ["offset_sig_disp"]
        self.assertEqual(E.merge_fields(current, derived, "structmember"), derived)

    def test_existing_fields_ignores_comments(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
        handle.write('GENERATE_YAML_DESIRED_FIELDS = [\n    ("X", [\n        "func_name",\n'
                     '        # why\n        "func_sig",\n    ]),\n]\n')
        handle.close()
        self.assertEqual(E.existing_fields(handle.name), [["func_name", "func_sig"]])


if __name__ == "__main__":
    unittest.main()
