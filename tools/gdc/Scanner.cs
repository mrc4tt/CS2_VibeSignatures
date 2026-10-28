using System.Collections.Concurrent;

namespace Gdc;

/// <summary>
/// One gamedata file judged against one build's binaries, with the statuses
/// verify_plugin_gamedata.check_signature uses so the two can be compared row by row.
/// Offsets are not judged here (they need this repo's analysis, not the binary).
/// </summary>
internal sealed class Scanner(string buildDir)
{
    private static readonly Dictionary<string, string> Linux = new()
    {
        ["server"] = "libserver.so", ["engine"] = "libengine2.so", ["client"] = "libclient.so",
        ["networksystem"] = "libnetworksystem.so", ["scenesystem"] = "libscenesystem.so",
        ["matchmaking"] = "libmatchmaking.so", ["vphysics2"] = "libvphysics2.so",
        ["SDL3"] = "libSDL3.so.0", ["worldrenderer"] = "libworldrenderer.so", ["tier0"] = "libtier0.so",
        ["schemasystem"] = "libschemasystem.so", ["filesystem_stdio"] = "libfilesystem_stdio.so",
        ["soundsystem"] = "libsoundsystem.so",
    };

    private static readonly Dictionary<string, string> Windows = new()
    {
        ["server"] = "server.dll", ["engine"] = "engine2.dll", ["client"] = "client.dll",
        ["networksystem"] = "networksystem.dll", ["scenesystem"] = "scenesystem.dll",
        ["matchmaking"] = "matchmaking.dll", ["vphysics2"] = "vphysics2.dll",
        ["SDL3"] = "SDL3.dll", ["worldrenderer"] = "worldrenderer.dll", ["tier0"] = "tier0.dll",
        ["schemasystem"] = "schemasystem.dll", ["filesystem_stdio"] = "filesystem_stdio.dll",
        ["soundsystem"] = "soundsystem.dll",
    };

    private readonly ConcurrentDictionary<(string, string), Lazy<Image?>> _images = new();

    public Image? Binary(string module, string platform) =>
        _images.GetOrAdd((module, platform), key => new Lazy<Image?>(() =>
        {
            var names = key.Item2 == "linux" ? Linux : Windows;
            if (!names.TryGetValue(key.Item1, out var name))
                return null;
            var path = Path.Combine(buildDir, key.Item1, name);
            return File.Exists(path) ? Image.Load(path) : null;
        })).Value;

    public Dictionary<string, object?> Check(Entry entry, string platform)
    {
        var value = entry.Values.GetValueOrDefault(platform);
        if (value is null or "")
            return Status("not-shipped");
        if (entry.Kind == "offset")
            return Status("skipped");
        if (entry.Kind == "patch")
            return Status("patch-unverifiable");
        var text = GameData.Text(value);
        var result = CheckSignature(Binary(entry.Module, platform), text);
        if (entry.LibraryGiven || result["status"] is not "broken")
            return result;
        // No library in the file: the plugin hard-codes the module. A pattern that resolves
        // uniquely in exactly one other module is that entry's; anything else stays broken.
        var found = (platform == "linux" ? Linux : Windows).Keys
            .Where(module => module != entry.Module)
            .Select(module => (module, info: CheckSignature(Binary(module, platform), text)))
            .Where(hit => hit.info["status"] is "ok" or "ok-midfunction")
            .ToList();
        if (found.Count != 1)
            return result;
        found[0].info["module"] = found[0].module;
        return found[0].info;
    }

    public static Dictionary<string, object?> CheckSignature(Image? image, string text)
    {
        if (image is null)
            return Status("no-binary");
        if (text.StartsWith('@'))
            return Status("symbol-name");
        var pattern = Pattern.Parse(text);
        if (pattern is null)
            return Status("unparsable");
        if (pattern.Literals < Pattern.MinLiteralBytes)
            return new() { ["status"] = "too-few-literals", ["literals"] = pattern.Literals };

        // Only executable memory resolves at runtime and a hit in an ELF linker stub is
        // skipped, so neither one resolves the entry nor makes it ambiguous.
        var hits = new List<long>();
        var outside = 0;
        foreach (var offset in FindAll(image.Bytes, pattern))
        {
            if (image.IsExecutable(offset) && !image.InStub(offset))
                hits.Add(offset);
            else
                outside++;
        }

        if (hits.Count == 0)
        {
            var broken = Status("broken");
            if (outside > 0)
                broken["outside_code"] = outside;
            return broken;
        }
        if (hits.Count > 1)
            return new()
            {
                ["status"] = "ambiguous",
                ["count"] = hits.Count,
                ["at"] = hits.Take(4).Select(h => Hex(image.AddressOf(h) ?? 0)).ToList(),
            };

        var hit = hits[0];
        var va = image.AddressOf(hit) ?? 0;
        // Function head: padding before it, or 16-aligned. Anything else is a pattern
        // that lands inside a function, which is right for a global reference and a
        // weakness otherwise; telling those apart needs this repo's records.
        var boundary = hit > 0 && (image.Bytes[hit - 1] is 0xCC or 0x90 || va % 16 == 0);
        return new() { ["status"] = boundary ? "ok" : "ok-midfunction", ["at"] = Hex(va) };
    }

    /// <summary>Every offset the pattern matches, found by searching for its longest literal run.</summary>
    public static IEnumerable<long> FindAll(byte[] data, Pattern pattern)
    {
        var (start, length) = pattern.Anchor;
        if (length == 0)
            yield break;
        var needle = pattern.Bytes.Skip(start).Take(length).Select(b => b!.Value).ToArray();
        var from = 0;
        while (from <= data.Length - length)
        {
            var found = data.AsSpan(from).IndexOf(needle);
            if (found < 0)
                yield break;
            var at = from + found;
            if (pattern.MatchesAt(data, at - start))
                yield return at - start;
            from = at + 1;
        }
    }

    private static Dictionary<string, object?> Status(string status) => new() { ["status"] = status };

    private static string Hex(ulong value) => "0x" + value.ToString("x");
}
