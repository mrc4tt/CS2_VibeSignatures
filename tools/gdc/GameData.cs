using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Gdc;

internal sealed record Entry(string Name, string Kind, string Module, IReadOnlyDictionary<string, object?> Values);

/// <summary>
/// A plugin's gamedata file read into entries, by the same rules as
/// verify_plugin_gamedata.load_gamedata_text. Matching those rules is the point:
/// gdc is a second opinion on the SAME question, so a different reading of the
/// file would show up as disagreements that say nothing about the binaries.
/// </summary>
internal static partial class GameData
{
    public static readonly string[] Platforms = ["linux", "windows"];

    private static readonly HashSet<string> KindWords =
        ["signature", "signatures", "offset", "offsets", "patch", "patches", "address", "addresses", "games", "csgo", "library"];

    private static readonly Dictionary<string, string> PlatformAliases = new()
    {
        ["linux"] = "linux", ["windows"] = "windows", ["linuxsteamrt64"] = "linux",
        ["win64"] = "windows", ["linux64"] = "linux", ["win32"] = "windows",
    };

    private static readonly Dictionary<string, string> LibraryToModule = new()
    {
        ["server"] = "server", ["engine"] = "engine", ["engine2"] = "engine",
        ["client"] = "client", ["networksystem"] = "networksystem",
        ["scenesystem"] = "scenesystem", ["matchmaking"] = "matchmaking",
        ["vphysics2"] = "vphysics2", ["sdl3"] = "SDL3", ["SDL3"] = "SDL3",
        ["worldrenderer"] = "worldrenderer", ["tier0"] = "tier0",
        ["schemasystem"] = "schemasystem", ["filesystem_stdio"] = "filesystem_stdio",
        ["soundsystem"] = "soundsystem",
    };

    /// <summary>-> (entries, note); a note means the file was not checked and says why.</summary>
    public static (List<Entry> Entries, string? Note) Load(string text)
    {
        if (text.Length > 0 && text[0] == '﻿')
            text = text[1..];

        var (parsed, json) = ReadJson(text);
        var data = parsed ? json as OrderedDictionary<string, object?>
            : text.Contains('"') && text.Contains('{') ? ReadKeyValues(text) : null;
        if (data is null || data.Count == 0)
            return ([], FlatKeyValue().IsMatch(text)
                ? "flat key=value file: no symbol keys to check"
                : "unrecognised format (not JSON, JSONC or KeyValues)");

        var entries = new List<Entry>();
        var seen = new HashSet<string>();
        foreach (var entry in Walk(data, []))
            if (seen.Add(entry.Name)) // the first entry of a name wins, as setdefault does
                entries.Add(entry);
        return entries.Count == 0 ? ([], "parsed, but no entry names a linux/windows value") : (entries, null);
    }

    private static IEnumerable<Entry> Walk(OrderedDictionary<string, object?> node, List<string> path)
    {
        var values = new OrderedDictionary<string, object?>();
        foreach (var (key, value) in node)
            if (PlatformAliases.TryGetValue(key.ToLowerInvariant(), out var platform) && value is not OrderedDictionary<string, object?>)
                values[platform] = value;

        if (values.Count > 0)
        {
            // The name is the nearest ancestor that is not a kind word; the kind word
            // nearest the entry is only a hint, and may sit above or below the name.
            string name = "?", hint = "";
            for (var i = path.Count - 1; i >= 0; i--)
            {
                var lowered = path[i].ToLowerInvariant();
                if (KindWords.Contains(lowered))
                {
                    if (hint.Length == 0)
                        hint = lowered;
                }
                else if (name == "?")
                    name = path[i];
            }

            var sample = values.GetAt(0).Value;
            var kind = sample is double or long ? "offset" : "signature";
            if (sample is string s && AllDigits().IsMatch(s))
                kind = "offset";
            if (hint.Contains("patch"))
                kind = "patch";

            var library = Truthy(node.GetValueOrDefault("library")) ?? Truthy(node.GetValueOrDefault("Library"))
                ?? Truthy(node.GetValueOrDefault("lib")) ?? "server";
            var module = LibraryToModule.GetValueOrDefault(library, "server");

            var converted = new Dictionary<string, object?>();
            foreach (var (platform, value) in values)
                converted[platform] = kind == "signature" && value is string text && text.Contains("\\x")
                    ? KeyValueWildcards(text) : value;
            yield return new Entry(name, kind, module, converted);
            yield break;
        }

        foreach (var (key, value) in node)
            if (value is OrderedDictionary<string, object?> child)
                foreach (var entry in Walk(child, [.. path, key]))
                    yield return entry;
    }

    /// <summary>Valve KeyValues signatures are \xAA escapes, and \x2A is their wildcard.</summary>
    public static string KeyValueWildcards(string raw) =>
        string.Join(' ', EscapedByte().Matches(raw).Select(m =>
            m.Groups[1].Value.Equals("2A", StringComparison.OrdinalIgnoreCase) ? "??" : m.Groups[1].Value.ToUpperInvariant()));

    /// <summary>Python's str() of a scalar, which is what the reference scans when a value is not text.</summary>
    public static string Text(object? value) => value switch
    {
        string s => s,
        long l => l.ToString(CultureInfo.InvariantCulture),
        double d => d.ToString("R", CultureInfo.InvariantCulture),
        bool b => b ? "True" : "False",
        null => "None",
        _ => value.ToString() ?? "",
    };

    private static string? Truthy(object? value) => value switch
    {
        null or false or "" or 0L or 0.0 => null,
        OrderedDictionary<string, object?> { Count: 0 } or List<object?> { Count: 0 } => null,
        _ => Text(value),
    };

    private static (bool Parsed, object? Value) ReadJson(string text)
    {
        // Strict JSON, then JSONC: one reader that skips comments and trailing commas
        // accepts the union of what json.loads and json.loads(_strip_jsonc(...)) accept.
        try
        {
            using var document = JsonDocument.Parse(text, new JsonDocumentOptions
            {
                CommentHandling = JsonCommentHandling.Skip,
                AllowTrailingCommas = true,
                MaxDepth = 256,
            });
            return (true, Convert(document.RootElement));
        }
        catch (JsonException)
        {
            return (false, null);
        }
    }

    private static object? Convert(JsonElement element) => element.ValueKind switch
    {
        JsonValueKind.Object => ConvertObject(element),
        JsonValueKind.Array => element.EnumerateArray().Select(Convert).ToList(),
        JsonValueKind.String => element.GetString(),
        JsonValueKind.Number => element.TryGetInt64(out var l) ? l : element.GetDouble(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        _ => null,
    };

    private static OrderedDictionary<string, object?> ConvertObject(JsonElement element)
    {
        // A repeated key keeps its first position and its last value, as a Python dict does.
        var node = new OrderedDictionary<string, object?>();
        foreach (var property in element.EnumerateObject())
            node[property.Name] = Convert(property.Value);
        return node;
    }

    /// <summary>Minimal Valve KeyValues -> nested dicts, token for token as _parse_kv.</summary>
    private static OrderedDictionary<string, object?> ReadKeyValues(string text)
    {
        var root = new OrderedDictionary<string, object?>();
        var stack = new List<OrderedDictionary<string, object?>> { root };
        string? pending = null;
        foreach (Match token in KeyValueToken().Matches(text))
        {
            var brace = token.Groups[2].Value;
            if (brace == "{")
            {
                var child = new OrderedDictionary<string, object?>();
                if (pending is not null)
                {
                    stack[^1][pending] = child;
                    pending = null;
                }
                stack.Add(child);
            }
            else if (brace == "}")
            {
                if (stack.Count > 1)
                    stack.RemoveAt(stack.Count - 1);
            }
            else if (pending is null)
                pending = token.Groups[1].Value;
            else
            {
                stack[^1][pending] = token.Groups[1].Value;
                pending = null;
            }
        }
        return root;
    }

    public static string ReadFile(string path) => File.ReadAllText(path, new UTF8Encoding(false, true));

    [GeneratedRegex(@"\\x([0-9A-Fa-f]{2})")]
    private static partial Regex EscapedByte();

    [GeneratedRegex(@"\A\s*\d+\s*\z")]
    private static partial Regex AllDigits();

    [GeneratedRegex(@"""((?:[^""\\]|\\.)*)""|([{}])")]
    private static partial Regex KeyValueToken();

    [GeneratedRegex(@"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=", RegexOptions.Multiline)]
    private static partial Regex FlatKeyValue();
}
