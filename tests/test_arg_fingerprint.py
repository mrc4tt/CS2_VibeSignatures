"""audit_arg_fingerprint reads which argument registers a function uses before writing
them, so a parameter Valve adds or drops shows up as a changed fingerprint."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_arg_fingerprint as A  # noqa: E402

BASE = 0x1000


def fp(code_hex, platform="linux"):
    code = bytes.fromhex(code_hex.replace(" ", "")) + b"\xCC" * 32
    blob = b"\xCC" * BASE + code
    info = {"segs": [(0, 0, len(blob), 0x1)], "base": 0, "type": "elf"}
    return A.fingerprint(blob, info, BASE, platform)


@unittest.skipIf(A.capstone is None, "needs capstone")
class FingerprintTests(unittest.TestCase):
    def test_two_arguments_read(self):
        # mov rax, rdi ; add rax, rsi ; ret
        self.assertEqual(fp("4889F8 4801F0 C3")["int"], ["rdi", "rsi"])

    def test_a_register_written_first_is_not_an_argument(self):
        # xor esi, esi ; mov rax, rdi ; add rax, rsi ; ret
        self.assertEqual(fp("31F6 4889F8 4801F0 C3")["int"], ["rdi"])

    def test_default_argument_wrapper_passes_the_first_ones_through(self):
        # xor r9d,r9d ; xor r8d,r8d ; xor ecx,ecx ; xor edx,edx ; jmp +0
        self.assertEqual(fp("4531C9 4531C0 31C9 31D2 E900000000")["int"], ["rdi", "rsi"])

    def test_thunk_is_followed_into_its_body(self):
        # jmp +2 ; (int3 int3) ; mov rax, rdx ; ret  -> reads rdx (and rdi/rsi pass-through? no call)
        self.assertEqual(fp("EB02 CCCC 4889D0 C3")["int"], ["rdx"])

    def test_byte_register_counts_as_its_argument(self):
        # movzx esi, dl ; ret   -> windows second argument (rdx), as RemoveWeapons reads it
        self.assertEqual(fp("0FB6F2 C3", "windows")["int"], ["rdx"])
        # movzx eax, cl ; ret
        self.assertEqual(fp("0FB6C1 C3", "windows")["int"], ["rcx"])

    def test_bool_normalised_for_an_empty_callee_is_not_a_parameter(self):
        # movzx ecx, cl ; mov rbx, rdi ; call +3 ; int3 ; int3 ; int3 ; ret   (callee is a bare ret)
        self.assertEqual(fp("0FB6C9 4889FB E803000000 CCCCCC C3")["int"], ["rdi"])

    def test_bool_normalised_for_a_real_callee_is_a_parameter(self):
        # movzx ecx, cl ; call +3 ; int3*3 ; mov eax, ecx ; ret
        self.assertIn("rcx", fp("0FB6C9 E803000000 CCCCCC 89C8 C3")["int"])

    def test_windows_stack_argument(self):
        # mov rax, [rsp+0x28] ; ret   -> the fifth argument
        got = fp("488B442428 C3", "windows")
        self.assertEqual(got["stack"], 1)

    def test_an_added_parameter_changes_the_fingerprint(self):
        before = fp("4889F8 C3")                 # f(a)
        after = fp("4889F8 4801F0 C3")           # f(a, b)
        self.assertNotEqual(before["int"], after["int"])
        self.assertEqual((A.arity(before), A.arity(after)), (1, 2))


if __name__ == "__main__":
    unittest.main()
