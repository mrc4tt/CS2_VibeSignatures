using System.Buffers.Binary;

namespace Gdc;

/// <summary>One mapped stretch of the file: where it sits on disk and where it loads.</summary>
internal readonly record struct Segment(long FileOffset, ulong Address, long Size, bool Executable);

/// <summary>
/// A PE32+ or ELF64 game binary, read as bytes and never loaded.
///
/// CounterStrikeSharp/GamedataChecker resolves exports with NativeLibrary.TryLoad,
/// which runs the library's initialisers on the checking machine. Here the file is
/// only parsed: the headers say which stretches are code, and that is all a
/// signature scan needs.
/// </summary>
internal sealed class Image
{
    // CounterStrikeSharp's CModule::IsStubAddress: a hit in one of these ELF sections is
    // a linker stub, so the runtime scanner skips it and keeps looking.
    private static readonly HashSet<string> StubSections =
        [".init", ".plt", ".plt.got", ".plt.sec", ".fini", ".got", ".got.plt"];

    public byte[] Bytes { get; }
    public string Kind { get; }
    public IReadOnlyList<Segment> Segments { get; }
    public IReadOnlyList<(long Start, long Size)> Stubs { get; }

    private Image(byte[] bytes, string kind, List<Segment> segments, List<(long, long)> stubs)
    {
        Bytes = bytes;
        Kind = kind;
        Segments = segments;
        Stubs = stubs;
    }

    public static Image Load(string path) => Parse(File.ReadAllBytes(path));

    public static Image Parse(byte[] bytes)
    {
        if (bytes.Length >= 64 && bytes[0] == 0x7F && bytes[1] == (byte)'E' && bytes[2] == (byte)'L' && bytes[3] == (byte)'F')
            return ParseElf(bytes);
        if (bytes.Length >= 64 && bytes[0] == (byte)'M' && bytes[1] == (byte)'Z')
            return ParsePe(bytes);
        throw new InvalidDataException("neither ELF nor PE");
    }

    public bool IsExecutable(long offset)
    {
        foreach (var segment in Segments)
            if (segment.Executable && offset >= segment.FileOffset && offset < segment.FileOffset + segment.Size)
                return true;
        return false;
    }

    public bool InStub(long offset)
    {
        foreach (var (start, size) in Stubs)
            if (offset >= start && offset < start + size)
                return true;
        return false;
    }

    public ulong? AddressOf(long offset)
    {
        foreach (var segment in Segments)
            if (offset >= segment.FileOffset && offset < segment.FileOffset + segment.Size)
                return segment.Address + (ulong)(offset - segment.FileOffset);
        return null;
    }

    private static ReadOnlySpan<byte> At(byte[] bytes, long offset, int length)
    {
        if (offset < 0 || offset + length > bytes.Length)
            throw new InvalidDataException($"header field at 0x{offset:x} runs past the end of the file");
        return bytes.AsSpan((int)offset, length);
    }

    private static ushort U16(byte[] b, long o) => BinaryPrimitives.ReadUInt16LittleEndian(At(b, o, 2));
    private static uint U32(byte[] b, long o) => BinaryPrimitives.ReadUInt32LittleEndian(At(b, o, 4));
    private static ulong U64(byte[] b, long o) => BinaryPrimitives.ReadUInt64LittleEndian(At(b, o, 8));

    private static Image ParseElf(byte[] bytes)
    {
        if (bytes[4] != 2 || bytes[5] != 1)
            throw new InvalidDataException("only little-endian ELF64 is supported");

        var segments = new List<Segment>();
        ulong phoff = U64(bytes, 0x20);
        ushort phentsize = U16(bytes, 0x36), phnum = U16(bytes, 0x38);
        for (var i = 0; i < phnum; i++)
        {
            var at = (long)phoff + (long)i * phentsize;
            if (U32(bytes, at) != 1) // PT_LOAD
                continue;
            uint flags = U32(bytes, at + 4);
            ulong offset = U64(bytes, at + 8), vaddr = U64(bytes, at + 16), filesz = U64(bytes, at + 32);
            segments.Add(new Segment((long)offset, vaddr, Clamp(bytes, offset, filesz), (flags & 1) != 0));
        }

        var stubs = new List<(long, long)>();
        ulong shoff = U64(bytes, 0x28);
        ushort shentsize = U16(bytes, 0x3A), shnum = U16(bytes, 0x3C), shstrndx = U16(bytes, 0x3E);
        if (shoff != 0 && shnum != 0 && shstrndx < shnum && (long)shoff + (long)shnum * shentsize <= bytes.Length)
        {
            var strtab = (long)U64(bytes, (long)shoff + (long)shstrndx * shentsize + 24);
            for (var i = 0; i < shnum; i++)
            {
                var at = (long)shoff + (long)i * shentsize;
                var name = CString(bytes, strtab + U32(bytes, at));
                ulong offset = U64(bytes, at + 24), size = U64(bytes, at + 32);
                if (size != 0 && StubSections.Contains(name))
                    stubs.Add(((long)offset, (long)size));
            }
        }
        return new Image(bytes, "elf", segments, stubs);
    }

    private static Image ParsePe(byte[] bytes)
    {
        var pe = U32(bytes, 0x3C);
        if (U32(bytes, pe) != 0x00004550) // "PE\0\0"
            throw new InvalidDataException("no PE signature");
        ushort sections = U16(bytes, pe + 6), optionalSize = U16(bytes, pe + 20);
        var optional = pe + 24L;
        if (U16(bytes, optional) != 0x20B)
            throw new InvalidDataException("only PE32+ is supported");
        ulong imageBase = U64(bytes, optional + 24);

        var segments = new List<Segment>();
        for (var i = 0; i < sections; i++)
        {
            var at = optional + optionalSize + i * 40L;
            uint vaddr = U32(bytes, at + 12), rawSize = U32(bytes, at + 16), rawPointer = U32(bytes, at + 20);
            uint characteristics = U32(bytes, at + 36);
            const uint MemExecute = 0x20000000;
            segments.Add(new Segment(rawPointer, imageBase + vaddr, Clamp(bytes, rawPointer, rawSize), (characteristics & MemExecute) != 0));
        }
        return new Image(bytes, "pe", segments, []);
    }

    private static long Clamp(byte[] bytes, ulong offset, ulong size) =>
        offset >= (ulong)bytes.Length ? 0 : (long)Math.Min(size, (ulong)bytes.Length - offset);

    private static string CString(byte[] bytes, long offset)
    {
        if (offset < 0 || offset >= bytes.Length)
            return "";
        var end = Array.IndexOf(bytes, (byte)0, (int)offset);
        return System.Text.Encoding.Latin1.GetString(bytes, (int)offset, (end < 0 ? bytes.Length : end) - (int)offset);
    }
}
