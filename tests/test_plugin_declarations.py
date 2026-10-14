"""audit_plugin_declarations reads how plugins call gamedata functions from their C# source."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_plugin_declarations as D  # noqa: E402

SOURCE = '''
public static class VirtualFunctions {
    public static readonly MemoryFunctionVoid<IntPtr, string> SetModelFunc =
        new(() => GameData.GetSignature("CBaseModelEntity_SetModel"));
    [Obsolete("Passes only two of SetPawn's four flags")]
    public static readonly MemoryFunctionVoid<CBasePlayerController, CBasePlayerPawn, bool, bool> SetPawnFunc =
        new(() => GameData.GetSignature("CBasePlayerController_SetPawn"));
    public static readonly MemoryFunctionWithReturn<string, int, IntPtr> CreateFunc =
        new(GameData.GetSignature("UTIL_CreateEntityByName"));
}
class X { void F() {
    VirtualFunction.CreateVoid<nint, float>(Handle, GameData.GetOffset("K_Virtual"))(Handle, 1f);
    var g = new MemoryFunctionWithReturn<IntPtr, Func<int, int>, CSmoke>(GameData.GetSignature("K_New"));
} }
'''


class DeclarationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        with open(os.path.join(self.dir.name, "A.cs"), "w") as handle:
            handle.write(SOURCE)
        self.found = {d["key"]: d for d in D.declarations([self.dir.name])}

    def tearDown(self):
        self.dir.cleanup()

    def test_all_three_forms_are_read(self):
        self.assertEqual(set(self.found), {"CBaseModelEntity_SetModel", "CBasePlayerController_SetPawn",
                                           "UTIL_CreateEntityByName", "K_Virtual", "K_New"})

    def test_with_return_drops_the_return_type(self):
        self.assertEqual(self.found["UTIL_CreateEntityByName"]["params"], ["string", "int"])
        self.assertEqual(self.found["K_New"]["params"], ["IntPtr", "Func<int, int>"])

    def test_obsolete_is_marked_and_only_there(self):
        self.assertTrue(self.found["CBasePlayerController_SetPawn"]["obsolete"])
        self.assertFalse(self.found["UTIL_CreateEntityByName"]["obsolete"])

    def test_counts_per_platform(self):
        params = self.found["K_Virtual"]["params"]
        self.assertEqual(D.declared_counts(params, "linux"), {"int": 1, "float": 1})
        self.assertEqual(D.declared_counts(params, "windows"), {"positions": 2})

    def test_observed_windows_positions_include_stack(self):
        fp = {"int": ["rcx", "rdx", "r8"], "float": [], "stack": 1}
        self.assertEqual(D.observed_counts(fp, "windows"), {"positions": 5})


if __name__ == "__main__":
    unittest.main()
