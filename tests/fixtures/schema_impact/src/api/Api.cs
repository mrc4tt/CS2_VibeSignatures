using System;
namespace CounterStrikeSharp.API.Modules.Memory {
public static class Schema {
  public static T GetSchemaValue<T>(IntPtr h, string c, string f) => default;
  public static void SetSchemaValue<T>(IntPtr h, string c, string f, T v) {}
}}
namespace CounterStrikeSharp.API.Core {
public class CEntityInstance { public IntPtr Handle; }
public class CBaseEntity : CEntityInstance { static int s; public ref int Health => ref s; public string Name { get => ""; set {} } }
public class CCSPlayerPawn : CBaseEntity { public float Armor { get; set; } }
}
