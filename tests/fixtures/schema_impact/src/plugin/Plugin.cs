using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Modules.Memory;
namespace FixturePlugin {
public static class Uses {
  // fat header: locals, a switch (variable-length operand) before the ldstr pair
  public static int Run(CCSPlayerPawn pawn, int k) {
    pawn.Health = 100;              // get_Health, declared on CBaseEntity
    pawn.Name = "x";                // set_Name, CBaseEntity
    pawn.Armor = 1f;                // set_Armor, CCSPlayerPawn
    string unrelated;
    switch (k) { case 0: unrelated = "a"; break; case 1: unrelated = "b"; break; case 2: unrelated = "c"; break; default: unrelated = "æ"; break; }
    System.Console.WriteLine(unrelated);
    Schema.SetSchemaValue(pawn.Handle, "CCSPlayerPawn", "m_ArmorValue", 5);
    return Schema.GetSchemaValue<int>(pawn.Handle, "CBaseEntity", "m_iMaxHealth");
  }
  // tiny header
  public static string Tiny() => "CBaseEntity";
  // a pair whose field is not a schema member and has no m_ prefix: must be ignored
  public static void NotSchema() => System.Console.WriteLine("{0}{1}", "CBaseEntity", "health");
}}
