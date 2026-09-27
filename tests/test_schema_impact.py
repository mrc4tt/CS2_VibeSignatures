"""schema_dump's rename heuristic and `impact`, and schema_impact's ECMA-335 reader.

tests/fixtures/schema_impact/FixturePlugin.dll is built from src/plugin against the stub API in
src/api (an assembly named CounterStrikeSharp.API with CBaseEntity/CCSPlayerPawn and a Schema
class), so it carries exactly the references a real plugin does. Rebuild with
`dotnet build -c Release -o <out> tests/fixtures/schema_impact/src/plugin` and copy the dll back.
"""
import contextlib
import io
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import schema_dump
import schema_impact

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "schema_impact" / "FixturePlugin.dll"


def cls(name, size, fields, bases=()):
    return {"name": name, "size": size, "bases": [{"name": b, "offset": 0} for b in bases],
            "fields": [{"name": n, "offset": o, "metadata": []} for n, o in fields]}


OLD = {
    "CEntityInstance": cls("CEntityInstance", 0x10, [("m_pEntity", 0x8)]),
    "CBaseEntity": cls("CBaseEntity", 0x40, [("m_iHealth", 0x10), ("m_iMaxHealth", 0x14), ("m_iszName", 0x18),
                                             ("m_flOld", 0x20)], ["CEntityInstance"]),
    "CCSPlayerPawn": cls("CCSPlayerPawn", 0x80, [("m_ArmorValue", 0x40), ("m_bGone", 0x44)], ["CBaseEntity"]),
    "CPlayer_WeaponServices": cls("CPlayer_WeaponServices", 0x20, [("m_hActiveWeapon", 0x10)]),
    "CCSPlayer_WeaponServices": cls("CCSPlayer_WeaponServices", 0x30, [("m_x", 0x20)], ["CPlayer_WeaponServices"]),
    "CLogicOld": cls("CLogicOld", 0x20, [("m_a", 0x8), ("m_b", 0xC), ("m_c", 0x10)]),
}
NEW = {
    "CEntityInstance": OLD["CEntityInstance"],
    # m_iHealth moved, m_flOld -> m_flNew at the same offset and size
    "CBaseEntity": cls("CBaseEntity", 0x48, [("m_iHealth", 0x1C), ("m_iMaxHealth", 0x14), ("m_iszName", 0x18),
                                             ("m_flNew", 0x20)], ["CEntityInstance"]),
    "CCSPlayerPawn": cls("CCSPlayerPawn", 0x80, [("m_ArmorValue", 0x40)], ["CBaseEntity"]),
    "CPlayer_WeaponServices": OLD["CPlayer_WeaponServices"],
    "CCSPlayer_WeaponServices": OLD["CCSPlayer_WeaponServices"],
    "CLogicNew": cls("CLogicNew", 0x20, [("m_a", 0x8), ("m_b", 0xC), ("m_d", 0x10)]),
}

GENERATED = {
    "CEntityInstance.g.cs": """
public partial class CEntityInstance : NativeEntity
{
\t[SchemaMember("CEntityInstance", "m_pEntity")]
\tpublic CEntityIdentity? Entity => Schema.GetPointer<CEntityIdentity>(this.Handle, "CEntityInstance", "m_pEntity");
}
""",
    "CBaseEntity.g.cs": """
public partial class CBaseEntity : CEntityInstance
{
\t// m_iHealth
\t[SchemaMember("CBaseEntity", "m_iHealth")]
\tpublic ref Int32 Health => ref Schema.GetRef<Int32>(this.Handle, "CBaseEntity", "m_iHealth");

\t[SchemaMember("CBaseEntity", "m_iszName")]
\tpublic string Name
\t{
\t\tget { return Schema.GetUtf8String(this.Handle, "CBaseEntity", "m_iszName"); }
\t}

\t[SchemaMember("CBaseEntity", "m_flOld")]
\tpublic ref float Old => ref Schema.GetRef<float>(this.Handle, "CBaseEntity", "m_flOld");
}
""",
    "CCSPlayerPawn.g.cs": """
public partial class CCSPlayerPawn : CCSPlayerPawnBase
{
\t[SchemaMember("CCSPlayerPawn", "m_ArmorValue")]
\tpublic ref Int32 Armor => ref Schema.GetRef<Int32>(this.Handle, "CCSPlayerPawn", "m_ArmorValue");
}
""",
    "CCSPlayerPawnBase.g.cs": """
public partial class CCSPlayerPawnBase : CBaseEntity
{
}
""",
}


def write_css(root):
    gen = Path(root) / "managed" / "CounterStrikeSharp.API" / "Generated" / "Schema" / "Classes"
    gen.mkdir(parents=True)
    for name, text in GENERATED.items():
        (gen / name).write_text(text, encoding="utf-8")
    model = Path(root) / "managed" / "CounterStrikeSharp.API" / "Core" / "Model"
    model.mkdir(parents=True)
    (model / "Hand.cs").write_text(
        '/// <example>Schema.GetRef(h, "CBaseEntity", "m_iszName")</example>\n'
        'var x = Schema.GetSchemaValue<bool>(Handle, "CCSPlayerPawn", "m_bGone");\n', encoding="utf-8")


class RenameHeuristicTests(unittest.TestCase):
    def test_same_offset_same_size_is_a_rename(self):
        self.assertEqual(schema_dump.field_renames(OLD["CBaseEntity"], NEW["CBaseEntity"]),
                         [("m_flOld", "m_flNew", 0x20)])

    def test_size_change_is_not_a_rename(self):
        a = cls("C", 0x30, [("m_a", 0x10), ("m_b", 0x14)])
        b = cls("C", 0x30, [("m_c", 0x10), ("m_b", 0x18)])  # m_a spanned 4 bytes, m_c spans 8
        self.assertEqual(schema_dump.field_renames(a, b), [])

    def test_two_candidates_at_one_offset_stay_undecided(self):
        a = cls("C", 0x20, [("m_a", 0x10), ("m_b", 0x10)])
        b = cls("C", 0x20, [("m_c", 0x10)])
        self.assertEqual(schema_dump.field_renames(a, b), [])

    def test_class_rename_needs_size_bases_and_most_fields(self):
        self.assertEqual(schema_dump.class_renames(OLD, NEW), {"CLogicOld": "CLogicNew"})
        other = dict(NEW, CLogicNew=cls("CLogicNew", 0x28, [("m_a", 0x8), ("m_b", 0xC), ("m_d", 0x10)]))
        self.assertEqual(schema_dump.class_renames(OLD, other), {})

    def test_diff_reports_a_rename_once(self):
        report = schema_dump.diff_schemas(OLD, NEW)
        entry = report["classes"]["CBaseEntity"]
        self.assertEqual(entry["renamed"], {"m_flOld": {"to": "m_flNew", "offset": 0x20}})
        self.assertNotIn("m_flOld", entry["removed"])
        self.assertNotIn("m_flNew", entry["added"])
        self.assertEqual(entry["moved"], {"m_iHealth": [0x10, 0x1C]})
        self.assertEqual(report["classes"]["CCSPlayerPawn"]["removed"], {"m_bGone": 0x44})
        self.assertEqual(report["classes_renamed"], {"CLogicOld": "CLogicNew"})
        self.assertEqual(report["classes_removed"], [])


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.report = schema_dump.diff_schemas(OLD, NEW)

    def status(self, c, f):
        return schema_impact.classify(OLD, NEW, self.report, c, f)

    def test_statuses(self):
        self.assertEqual(self.status("CBaseEntity", "m_iMaxHealth"), ("ok", "0x14"))
        self.assertEqual(self.status("CBaseEntity", "m_iHealth")[0], "moved")
        self.assertEqual(self.status("CCSPlayerPawn", "m_bGone")[0], "removed")
        status, detail = self.status("CBaseEntity", "m_flOld")
        self.assertEqual(status, "renamed")
        self.assertIn("m_flNew", detail)
        self.assertEqual(self.status("CLogicOld", "m_a")[0], "renamed")
        self.assertEqual(self.status("CBaseEntity", "m_flNew")[0], "added")
        self.assertEqual(self.status("CNoSuchClass", "m_x")[0], "absent")

    def test_base_class_field_named_on_derived_class(self):
        status, detail = self.status("CCSPlayer_WeaponServices", "m_hActiveWeapon")
        self.assertEqual(status, "inherited")
        self.assertIn("CPlayer_WeaponServices", detail)
        self.assertIn("SetStateChanged", detail)


class MetadataReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asm = schema_impact.Assembly(FIXTURE)

    def test_assembly_and_member_refs(self):
        self.assertIn("CounterStrikeSharp.API", self.asm.assembly_refs())
        refs = {(a, ns, t, m) for a, ns, t, m in self.asm.member_refs()}
        core = ("CounterStrikeSharp.API", "CounterStrikeSharp.API.Core")
        self.assertIn(core + ("CBaseEntity", "get_Health"), refs)  # declared on the base, called via the pawn
        self.assertIn(core + ("CBaseEntity", "set_Name"), refs)
        self.assertIn(core + ("CCSPlayerPawn", "set_Armor"), refs)
        self.assertIn(("CounterStrikeSharp.API", "CounterStrikeSharp.API.Modules.Memory", "Schema", "SetSchemaValue"),
                      refs)

    def test_ldstr_order_through_fat_and_tiny_bodies(self):
        methods = dict(self.asm.method_strings())
        # a switch table sits between "c" and the schema pair: the decoder must step over it
        self.assertEqual(methods["Run"], ["x", "a", "b", "c", "æ", "CCSPlayerPawn", "m_ArmorValue",
                                          "CBaseEntity", "m_iMaxHealth"])
        self.assertEqual(methods["Tiny"], ["CBaseEntity"])

    def test_native_file_is_not_dotnet(self):
        with tempfile.NamedTemporaryFile(suffix=".dll") as tmp:
            tmp.write(b"\x7fELF" + bytes(64))
            tmp.flush()
            with self.assertRaises(schema_impact.NotDotnet):
                schema_impact.Assembly(tmp.name)


class CssSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        write_css(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_generated_properties_and_base_chain(self):
        classes, bases = schema_impact.load_css_generated(self.tmp.name)
        self.assertEqual(classes["CBaseEntity"]["Health"], ("CBaseEntity", "m_iHealth"))
        self.assertEqual(classes["CBaseEntity"]["Name"], ("CBaseEntity", "m_iszName"))
        self.assertEqual(bases["CCSPlayerPawn"], "CCSPlayerPawnBase")
        self.assertEqual(schema_impact.resolve_property(classes, bases, "CCSPlayerPawn", "Health"),
                         ("CBaseEntity", "m_iHealth"))
        self.assertEqual(schema_impact.resolve_property(classes, bases, "CCSPlayerPawn", "Entity"),
                         ("CEntityInstance", "m_pEntity"))
        self.assertIsNone(schema_impact.resolve_property(classes, bases, "CCSPlayerPawn", "Nope"))

    def test_handwritten_pairs_skip_comments(self):
        known = {"CBaseEntity": {"m_iszName"}, "CCSPlayerPawn": {"m_bGone"}}
        self.assertEqual(schema_impact.load_css_handwritten(self.tmp.name, known), {("CCSPlayerPawn", "m_bGone")})

    def test_scan_fixture_plugin(self):
        classes, bases = schema_impact.load_css_generated(self.tmp.name)
        known = {"CBaseEntity": {"m_iHealth", "m_iMaxHealth", "m_iszName"}, "CCSPlayerPawn": {"m_ArmorValue"}}
        used = schema_impact.scan_assembly(FIXTURE, classes, bases, known)
        self.assertEqual(set(used), {("CBaseEntity", "m_iHealth"), ("CBaseEntity", "m_iszName"),
                                     ("CCSPlayerPawn", "m_ArmorValue"), ("CBaseEntity", "m_iMaxHealth")})
        self.assertEqual(used[("CCSPlayerPawn", "m_ArmorValue")], {"CCSPlayerPawn.Armor", "string"})
        self.assertEqual(used[("CBaseEntity", "m_iHealth")], {"CBaseEntity.Health"})


class ImpactCommandTests(unittest.TestCase):
    def run_impact(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            css = Path(tmp) / "css"
            write_css(css)
            plugins = Path(tmp) / "plugins"
            (plugins / "Fixture").mkdir(parents=True)
            (plugins / "Fixture" / "Fixture.dll").write_bytes(FIXTURE.read_bytes())
            (plugins / "disabled").mkdir()
            (plugins / "disabled" / "Old.dll").write_bytes(FIXTURE.read_bytes())
            args = types.SimpleNamespace(old="1", new="2", module="server", platform="linux", bindir="bin",
                                         css=str(css), plugins=[str(plugins)], json="-json" in extra,
                                         verbose=False)
            dumps = {"1": OLD, "2": NEW}
            out = io.StringIO()
            with mock.patch.object(schema_dump, "load_or_dump", lambda v, *a, **k: dumps[v]), \
                    contextlib.redirect_stdout(out):
                code = schema_dump.impact(args)
        return code, out.getvalue()

    def test_json_report_and_exit_code(self):
        code, text = self.run_impact("-json")
        self.assertEqual(code, 1)  # the API's CBaseEntity.Old maps to m_flOld, renamed
        report = json.loads(text)
        groups = {g["name"]: g for g in report["groups"]}
        self.assertNotIn(os.path.join("disabled", "Old.dll"), groups)
        plugin = groups[os.path.join("Fixture", "Fixture.dll")]
        status = {(f["class"], f["field"]): f["status"] for f in plugin["fields"]}
        self.assertEqual(status, {("CBaseEntity", "m_iHealth"): "moved", ("CBaseEntity", "m_iMaxHealth"): "ok",
                                  ("CBaseEntity", "m_iszName"): "ok", ("CCSPlayerPawn", "m_ArmorValue"): "ok"})
        api = groups["CounterStrikeSharp.API (generated)"]
        self.assertEqual(api["counts"].get("renamed"), 1)
        hand = groups["CounterStrikeSharp.API (hand-written)"]
        self.assertEqual(hand["counts"], {"removed": 1})
        self.assertEqual(report["summary"]["plugins_broken"], 0)
        self.assertTrue(report["summary"]["api_broken"])

    def test_text_report_says_moves_are_harmless(self):
        code, text = self.run_impact()
        self.assertEqual(code, 1)
        self.assertIn("moves are informational", text)
        self.assertIn("RENAMED  CBaseEntity::m_flOld", text)
        self.assertIn("MOVED    CBaseEntity::m_iHealth", text)


if __name__ == "__main__":
    unittest.main()
