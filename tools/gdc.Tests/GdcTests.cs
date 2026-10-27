using Xunit;
using static Gdc.Tests.Fixtures;

namespace Gdc.Tests;

public class PatternTests
{
    [Theory]
    [InlineData("48 8B ? ?? 05", 5, 3)]
    [InlineData("  48   8b\t05 ", 3, 3)]
    public void ReadsTwoDigitBytesAndWildcards(string text, int length, int literals)
    {
        var pattern = Pattern.Parse(text)!;
        Assert.Equal(length, pattern.Bytes.Length);
        Assert.Equal(literals, pattern.Literals);
    }

    [Theory]
    [InlineData("488B")]   // CSS discards the whole pattern, it does not read a number
    [InlineData("48 8")]
    [InlineData("48 GG")]
    [InlineData("48 ???")]
    [InlineData("")]
    public void RejectsWhatHexToByteRejects(string text) => Assert.Null(Pattern.Parse(text));

    [Fact]
    public void AnchorsOnTheFirstLongestLiteralRun()
    {
        var pattern = Pattern.Parse("48 ? 8B 05 ? 11 22 ? 33 44")!;
        Assert.Equal((2, 2), pattern.Anchor);
    }

    [Fact]
    public void KeyValueEscapesTreat2AAsWildcard() =>
        Assert.Equal("48 ?? 8B ??", GameData.KeyValueWildcards(@"\x48\x2A\x8b\x2a"));
}

public class GameDataTests
{
    private static Entry Single(string text)
    {
        var (entries, note) = GameData.Load(text);
        Assert.Null(note);
        return Assert.Single(entries);
    }

    [Fact]
    public void CounterStrikeSharpShape()
    {
        var entry = Single("""{"CCSPlayer_Foo": {"signatures": {"library": "engine", "linux": "55 48", "windows": "40 53"}}}""");
        Assert.Equal(("CCSPlayer_Foo", "signature", "engine"), (entry.Name, entry.Kind, entry.Module));
        Assert.Equal("55 48", entry.Values["linux"]);
    }

    [Fact]
    public void KindWordAboveTheNameStillMarksAPatch() =>
        Assert.Equal("patch", Single("""{"Patches": {"Fix": {"linux": "90 90", "windows": "90"}}}""").Kind);

    [Theory]
    [InlineData("""{"Offsets": {"m_x": {"linux": 12, "windows": 13}}}""")]
    [InlineData("""{"m_x": {"offsets": {"linux": " 12 ", "windows": "13"}}}""")]
    public void NumbersAndDigitStringsAreOffsets(string text) => Assert.Equal("offset", Single(text).Kind);

    [Fact]
    public void JsoncCommentsAndTrailingCommas()
    {
        var entry = Single("""
            // header
            { "A": { "linux": "55 48 89 E5", /* why */ "windows": "40 53", }, }
            """);
        Assert.Equal("A", entry.Name);
    }

    [Fact]
    public void PlatformAliasesAndLib()
    {
        var entry = Single("""{"A": {"lib": "server", "linuxsteamrt64": "55", "win64": "40"}}""");
        Assert.Equal("55", entry.Values["linux"]);
        Assert.Equal("40", entry.Values["windows"]);
    }

    [Fact]
    public void KeyValuesFileWithEscapedSignature()
    {
        var entry = Single("""
            "Games"
            {
                "csgo"
                {
                    "Signatures"
                    {
                        "Foo"
                        {
                            "library"  "server"
                            "linux"    "\x55\x48\x2A\x89"
                        }
                    }
                }
            }
            """);
        Assert.Equal("Foo", entry.Name);
        Assert.Equal("55 48 ?? 89", entry.Values["linux"]);
    }

    [Fact]
    public void FirstEntryOfANameWins()
    {
        var (entries, _) = GameData.Load("""{"Signatures": {"A": {"linux": "11 22"}}, "Offsets": {"A": {"linux": 3}}}""");
        Assert.Equal("signature", Assert.Single(entries).Kind);
    }

    [Theory]
    [InlineData("[1, 2]", "unrecognised")]
    [InlineData("Foo_linux = 12\nBar_windows = 3\n", "key=value")]
    [InlineData("""{"a": {"b": 1}}""", "no entry")]
    public void FilesWithNothingToCheckSayWhy(string text, string reason)
    {
        var (entries, note) = GameData.Load(text);
        Assert.Empty(entries);
        Assert.Contains(reason, note);
    }
}

public class ScannerTests
{
    private const string Head = "55 48 89 E5 41 57 41 56";

    // 0x00: function head (16-aligned)  0x13: an instruction mid-function  0x20: a second copy
    private static byte[] Code(bool twice = false)
    {
        var code = Enumerable.Repeat((byte)0xCC, 0x40).ToArray();
        Bytes(Head).CopyTo(code, 0);
        Bytes("01 02 03 04 05").CopyTo(code, 0x12);
        Bytes("48 8D 05 AA BB CC DD").CopyTo(code, 0x13);
        if (twice)
            Bytes(Head).CopyTo(code, 0x20);
        return code;
    }

    private static Dictionary<string, object?> Scan(byte[] file, string pattern) =>
        Scanner.CheckSignature(Image.Parse(file), pattern);

    [Fact]
    public void UniqueHitAtAFunctionHead()
    {
        var info = Scan(Elf(Code(), new byte[16]), Head);
        Assert.Equal("ok", info["status"]);
        Assert.Equal($"0x{ElfBase + ElfCode:x}", info["at"]);
    }

    [Fact]
    public void UniqueHitInsideAFunction() =>
        Assert.Equal("ok-midfunction", Scan(Elf(Code(), new byte[16]), "48 8D 05 ? ? ? DD")["status"]);

    [Fact]
    public void TwoHitsAreAmbiguous()
    {
        var info = Scan(Elf(Code(twice: true), new byte[16]), Head);
        Assert.Equal("ambiguous", info["status"]);
        Assert.Equal(2, info["count"]);
    }

    [Fact]
    public void AHitOnlyInDataDoesNotResolve()
    {
        var info = Scan(Elf(new byte[16], Bytes("00 " + Head)), Head);
        Assert.Equal("broken", info["status"]);
        Assert.Equal(1, info["outside_code"]);
    }

    [Fact]
    public void AHitInALinkerStubIsSkipped()
    {
        var plt = Enumerable.Repeat((byte)0xCC, 0x40).ToArray();
        Bytes(Head).CopyTo(plt, 0x10);
        Assert.Equal("ok", Scan(Elf(Code(), new byte[16], plt), Head)["status"]);
    }

    [Theory]
    [InlineData("55 ? ? 89", "too-few-literals")]
    [InlineData("5548 89E5", "unparsable")]
    [InlineData("@_ZN3FooEv", "symbol-name")]
    [InlineData("11 22 33 44 55", "broken")]
    public void Refusals(string pattern, string status) =>
        Assert.Equal(status, Scan(Elf(Code(), new byte[16]), pattern)["status"]);

    [Fact]
    public void PeTextResolvesAndRdataDoesNot()
    {
        var pe = Pe(Code(), Bytes("00 00 00 00 99 88 77 66 55"));
        var info = Scan(pe, Head);
        Assert.Equal("ok", info["status"]);
        Assert.Equal($"0x{PeBase + 0x1000:x}", info["at"]);
        Assert.Equal("broken", Scan(pe, "99 88 77 66 55")["status"]);
    }

    [Fact]
    public void EntriesRouteToTheirModuleBinary()
    {
        var dir = Directory.CreateTempSubdirectory("gdc-");
        try
        {
            Directory.CreateDirectory(Path.Combine(dir.FullName, "engine"));
            File.WriteAllBytes(Path.Combine(dir.FullName, "engine", "libengine2.so"), Elf(Code(), new byte[16]));
            var scanner = new Scanner(dir.FullName);
            var (entries, _) = GameData.Load(
                "{\"A\": {\"library\": \"engine\", \"linux\": \"" + Head + "\", \"windows\": \"" + Head + "\"},"
                + " \"B\": {\"offsets\": {\"linux\": 4}}}");
            Assert.Equal("ok", scanner.Check(entries[0], "linux")["status"]);
            Assert.Equal("no-binary", scanner.Check(entries[0], "windows")["status"]);
            Assert.Equal("skipped", scanner.Check(entries[1], "linux")["status"]);
            Assert.Equal("not-shipped", scanner.Check(entries[1], "windows")["status"]);
        }
        finally
        {
            dir.Delete(recursive: true);
        }
    }
}

public class ImageTests
{
    [Fact]
    public void RefusesWhatIsNotABinary() =>
        Assert.Throws<InvalidDataException>(() => Image.Parse(new byte[128]));

    [Fact]
    public void ATruncatedHeaderIsAnErrorNotACrash()
    {
        var elf = Elf(new byte[16], new byte[16]);
        Assert.Throws<InvalidDataException>(() => Image.Parse(elf[..80]));
    }
}
