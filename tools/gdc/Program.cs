using System.Text.Json;
using Gdc;

// gdc: scan plugin gamedata signatures against one build's binaries, without loading them.
//
//   gdc --bin bin/14192 [--platform linux,windows] [--json out.json] <file|dir>...
//
// Prints a one-line summary, then one line per problem. Exit 0 when every signature
// resolves, 1 when any is broken/ambiguous/unparsable/too-few-literals, 2 on usage or IO error.

string? bin = null, jsonOut = null;
var platforms = GameData.Platforms;
var inputs = new List<string>();
for (var i = 0; i < args.Length; i++)
{
    string Next() => i + 1 < args.Length ? args[++i] : throw new ArgumentException($"{args[i]} needs a value");
    try
    {
        switch (args[i])
        {
            case "--bin": bin = Next(); break;
            case "--json": jsonOut = Next(); break;
            case "--platform": platforms = Next().Split(',', StringSplitOptions.RemoveEmptyEntries); break;
            case "-h" or "--help": return Usage(0);
            default:
                if (args[i].StartsWith("--"))
                    throw new ArgumentException($"unknown option {args[i]}");
                inputs.Add(args[i]);
                break;
        }
    }
    catch (ArgumentException e)
    {
        Console.Error.WriteLine($"gdc: {e.Message}");
        return Usage(2);
    }
}
if (bin is null || inputs.Count == 0)
    return Usage(2);
if (!Directory.Exists(bin))
{
    Console.Error.WriteLine($"gdc: no build directory {bin}");
    return 2;
}
if (platforms.Except(GameData.Platforms).FirstOrDefault() is { } unknown)
{
    Console.Error.WriteLine($"gdc: unknown platform {unknown}");
    return 2;
}

var files = new List<string>();
foreach (var input in inputs)
{
    if (Directory.Exists(input))
        files.AddRange(Directory.EnumerateFiles(input, "*", SearchOption.AllDirectories)
            .Where(f => f.EndsWith(".json") || f.EndsWith(".jsonc") || f.EndsWith(".txt"))
            .Order(StringComparer.Ordinal));
    else if (File.Exists(input))
        files.Add(input);
    else
    {
        Console.Error.WriteLine($"gdc: no such file {input}");
        return 2;
    }
}

string[] failing = ["broken", "ambiguous", "unparsable", "too-few-literals"];
var scanner = new Scanner(bin);
var report = new List<object>();
var problems = new List<string>();
int entryCount = 0, scanned = 0;
try
{
    foreach (var file in files)
    {
        var (entries, note) = GameData.Load(GameData.ReadFile(file));
        var rows = new Dictionary<string, object?>[entries.Count];
        Parallel.For(0, entries.Count, index =>
        {
            var entry = entries[index];
            rows[index] = new()
            {
                ["name"] = entry.Name,
                ["kind"] = entry.Kind,
                ["module"] = entry.Module,
                ["platforms"] = platforms.ToDictionary(p => p, p => scanner.Check(entry, p)),
            };
        });
        foreach (var row in rows)
            foreach (var (platform, info) in (Dictionary<string, Dictionary<string, object?>>)row["platforms"]!)
            {
                var status = (string)info["status"]!;
                if (status is not ("not-shipped" or "skipped" or "patch-unverifiable" or "symbol-name" or "no-binary"))
                    scanned++;
                if (failing.Contains(status))
                    problems.Add($"{file}: {row["name"]}.{platform} {status}"
                        + (info.TryGetValue("count", out var count) ? $" ({count} hits)" : ""));
            }
        entryCount += entries.Count;
        report.Add(new Dictionary<string, object?> { ["file"] = file, ["note"] = note, ["entries"] = rows });
    }
}
catch (Exception e) when (e is IOException or UnauthorizedAccessException or InvalidDataException or System.Text.DecoderFallbackException)
{
    Console.Error.WriteLine($"gdc: {e.Message}");
    return 2;
}

Console.WriteLine($"gdc: {files.Count} files, {entryCount} entries, {scanned} signatures scanned, {problems.Count} problems");
foreach (var problem in problems)
    Console.WriteLine(problem);

if (jsonOut is not null)
    File.WriteAllText(jsonOut, JsonSerializer.Serialize(new { build = bin, files = report }, new JsonSerializerOptions { WriteIndented = true }));

return problems.Count == 0 ? 0 : 1;

static int Usage(int code)
{
    (code == 0 ? Console.Out : Console.Error).WriteLine(
        "usage: gdc --bin <build dir> [--platform linux,windows] [--json out.json] <gamedata file|dir>...");
    return code;
}
