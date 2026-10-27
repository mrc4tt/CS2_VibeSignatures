namespace Gdc;

/// <summary>A byte pattern: null is a wildcard byte.</summary>
internal sealed class Pattern
{
    // Below this many literal bytes CounterStrikeSharp's CModule::ScanSignature refuses
    // the pattern instead of resolving its first hit.
    public const int MinLiteralBytes = 4;

    public byte?[] Bytes { get; }
    public int Literals { get; }
    /// <summary>The longest wildcard-free run: what is searched for, the rest is checked by hand.</summary>
    public (int Start, int Length) Anchor { get; }

    private Pattern(byte?[] bytes)
    {
        Bytes = bytes;
        Literals = bytes.Count(b => b is not null);
        int run = 0;
        for (var i = 0; i < bytes.Length; i++)
        {
            run = bytes[i] is null ? 0 : run + 1;
            if (run > Anchor.Length)
                Anchor = (i - run + 1, run);
        }
    }

    /// <summary>
    /// Read the way CounterStrikeSharp's CGameConfig::HexToByte reads it: every token is
    /// exactly two hex digits or a ? / ?? wildcard, otherwise the WHOLE pattern is
    /// discarded. KeyValues \xAA spelling is converted before it gets here (GameData).
    /// </summary>
    public static Pattern? Parse(string text)
    {
        var tokens = text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length == 0)
            return null;
        var bytes = new byte?[tokens.Length];
        for (var i = 0; i < tokens.Length; i++)
        {
            var token = tokens[i];
            if (token is "?" or "??")
                bytes[i] = null;
            else if (token.Length == 2 && Uri.IsHexDigit(token[0]) && Uri.IsHexDigit(token[1]))
                bytes[i] = Convert.ToByte(token, 16);
            else
                return null;
        }
        return new Pattern(bytes);
    }

    public bool MatchesAt(ReadOnlySpan<byte> data, long offset)
    {
        if (offset < 0 || offset + Bytes.Length > data.Length)
            return false;
        var at = (int)offset;
        for (var i = 0; i < Bytes.Length; i++)
            if (Bytes[i] is byte b && data[at + i] != b)
                return false;
        return true;
    }
}
