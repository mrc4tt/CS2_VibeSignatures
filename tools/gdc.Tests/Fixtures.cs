using System.Buffers.Binary;
using System.Text;

namespace Gdc.Tests;

/// <summary>Smallest binaries that still have the shape gdc reads: no real game file is needed.</summary>
internal static class Fixtures
{
    public const ulong ElfBase = 0x10000;
    public const int ElfPlt = 0x100, ElfCode = 0x140;
    public const ulong PeBase = 0x180000000;
    public const int PeText = 0x400;

    /// <summary>
    /// ELF64 with an executable PT_LOAD holding a 0x40-byte .plt then `code`, and a
    /// read-only PT_LOAD holding `data`. Virtual address = ElfBase + file offset.
    /// </summary>
    public static byte[] Elf(byte[] code, byte[] data, byte[]? plt = null)
    {
        var dataAt = Align(ElfCode + code.Length);
        var strtab = Encoding.ASCII.GetBytes("\0.plt\0.shstrtab\0");
        var strtabAt = Align(dataAt + data.Length);
        var shoff = Align(strtabAt + strtab.Length);
        var file = new byte[shoff + 3 * 64];

        file[0] = 0x7F; file[1] = (byte)'E'; file[2] = (byte)'L'; file[3] = (byte)'F';
        file[4] = 2; file[5] = 1; file[6] = 1;
        U16(file, 0x10, 3); U16(file, 0x12, 0x3E);
        U64(file, 0x20, 0x40); U64(file, 0x28, (ulong)shoff);
        U16(file, 0x36, 56); U16(file, 0x38, 2);
        U16(file, 0x3A, 64); U16(file, 0x3C, 3); U16(file, 0x3E, 2);

        Load(file, 0x40, flags: 5, ElfPlt, 0x40 + code.Length);
        Load(file, 0x40 + 56, flags: 4, dataAt, data.Length);

        (plt ?? Enumerable.Repeat((byte)0xCC, 0x40).ToArray()).CopyTo(file, ElfPlt);
        code.CopyTo(file, ElfCode);
        data.CopyTo(file, dataAt);
        strtab.CopyTo(file, strtabAt);

        Section(file, shoff + 64, name: 1, ElfPlt, 0x40);
        Section(file, shoff + 128, name: 6, strtabAt, strtab.Length);
        return file;
    }

    /// <summary>PE32+ with an executable .text holding `code` and a read-only .rdata holding `data`.</summary>
    public static byte[] Pe(byte[] code, byte[] data)
    {
        var rdataAt = Align(PeText + code.Length, 0x200);
        var file = new byte[Align(rdataAt + data.Length, 0x200)];
        file[0] = (byte)'M'; file[1] = (byte)'Z';
        U32(file, 0x3C, 0x80);
        U32(file, 0x80, 0x00004550);
        U16(file, 0x84, 0x8664); U16(file, 0x86, 2); U16(file, 0x94, 0xF0);
        U16(file, 0x98, 0x20B);
        U64(file, 0x98 + 24, PeBase);
        PeSection(file, 0x188, ".text", 0x1000, code.Length, PeText, 0x60000020);
        PeSection(file, 0x188 + 40, ".rdata", 0x2000, data.Length, rdataAt, 0x40000040);
        code.CopyTo(file, PeText);
        data.CopyTo(file, rdataAt);
        return file;
    }

    public static byte[] Bytes(string hex) =>
        hex.Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(t => Convert.ToByte(t, 16)).ToArray();

    private static void Load(byte[] f, int at, uint flags, long offset, long size)
    {
        U32(f, at, 1); U32(f, at + 4, flags);
        U64(f, at + 8, (ulong)offset); U64(f, at + 16, ElfBase + (ulong)offset);
        U64(f, at + 24, ElfBase + (ulong)offset); U64(f, at + 32, (ulong)size); U64(f, at + 40, (ulong)size);
    }

    private static void Section(byte[] f, int at, uint name, long offset, long size)
    {
        U32(f, at, name);
        U64(f, at + 24, (ulong)offset); U64(f, at + 32, (ulong)size);
    }

    private static void PeSection(byte[] f, int at, string name, uint vaddr, int size, int raw, uint characteristics)
    {
        Encoding.ASCII.GetBytes(name).CopyTo(f, at);
        U32(f, at + 8, (uint)size); U32(f, at + 12, vaddr);
        U32(f, at + 16, (uint)Align(size, 0x200)); U32(f, at + 20, (uint)raw);
        U32(f, at + 36, characteristics);
    }

    private static int Align(int value, int to = 0x10) => (value + to - 1) / to * to;
    private static void U16(byte[] f, int at, ushort v) => BinaryPrimitives.WriteUInt16LittleEndian(f.AsSpan(at), v);
    private static void U32(byte[] f, int at, uint v) => BinaryPrimitives.WriteUInt32LittleEndian(f.AsSpan(at), v);
    private static void U64(byte[] f, int at, ulong v) => BinaryPrimitives.WriteUInt64LittleEndian(f.AsSpan(at), v);
}
