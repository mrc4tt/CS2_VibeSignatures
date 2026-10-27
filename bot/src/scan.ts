// Scans a signature against one locked game binary, by the rules the plugin
// runtimes resolve it with - a port of verify_plugin_gamedata.check_signature,
// so /check answers what the pipeline's own verification would. Read-only.
import fs from "node:fs";

// CounterStrikeSharp's CModule::ScanSignature refuses a pattern with fewer literals.
export const MIN_LITERAL_BYTES = 4;
// CModule::IsStubAddress: a hit in a linker stub is skipped, not resolved.
const STUB_SECTIONS = new Set([".init", ".plt", ".plt.got", ".plt.sec", ".fini", ".got", ".got.plt"]);
const PADDING = new Set([0xcc, 0x90]);
const HIT_LIMIT = 64;

type Segment = { offset: number; va: bigint; size: number; exec: boolean };
export type Image = { blob: Buffer; segments: Segment[]; stubs: [number, number][] };

export type ScanResult =
    | { status: "unparsable" }
    | { status: "too-few-literals"; literals: number }
    | { status: "broken"; outsideCode: number }
    | { status: "ambiguous"; count: number; at: string[] }
    | { status: "ok" | "ok-midfunction"; at: string };

// Space-separated hex bytes with ?/?? wildcards (the gamedata JSON form), or Valve
// KeyValues escapes (\x55\x2A...) where \x2A is the wildcard. Every byte must be
// exactly two hex digits: CSS's HexToByte discards the whole pattern otherwise.
export function parsePattern(text: string): (number | null)[] | null {
    const trimmed = text.trim();
    if (trimmed.includes("\\x")) {
        const bytes = [...trimmed.matchAll(/\\x([0-9A-Fa-f]{2})/g)].map((m) => m[1].toUpperCase());
        return bytes.length ? bytes.map((b) => (b === "2A" ? null : parseInt(b, 16))) : null;
    }
    const tokens = trimmed.split(/\s+/).filter(Boolean);
    if (!tokens.length) return null;
    const out: (number | null)[] = [];
    for (const token of tokens) {
        if (token === "?" || token === "??") out.push(null);
        else if (/^[0-9A-Fa-f]{2}$/.test(token)) out.push(parseInt(token, 16));
        else return null;
    }
    return out;
}

function elfImage(blob: Buffer): Image {
    const segments: Segment[] = [];
    const phoff = Number(blob.readBigUInt64LE(32));
    const phentsize = blob.readUInt16LE(54), phnum = blob.readUInt16LE(56);
    for (let i = 0; i < phnum; i++) {
        const o = phoff + i * phentsize;
        if (blob.readUInt32LE(o) !== 1) continue; // PT_LOAD
        segments.push({
            offset: Number(blob.readBigUInt64LE(o + 8)),
            va: blob.readBigUInt64LE(o + 16),
            size: Number(blob.readBigUInt64LE(o + 32)),
            exec: (blob.readUInt32LE(o + 4) & 0x1) !== 0,
        });
    }
    const stubs: [number, number][] = [];
    const shoff = Number(blob.readBigUInt64LE(0x28));
    const shentsize = blob.readUInt16LE(0x3a), shnum = blob.readUInt16LE(0x3c), shstrndx = blob.readUInt16LE(0x3e);
    if (shoff && shnum && shstrndx < shnum && shoff + shnum * shentsize <= blob.length) {
        const header = (i: number) => {
            const o = shoff + i * shentsize;
            return { name: blob.readUInt32LE(o), offset: Number(blob.readBigUInt64LE(o + 24)), size: Number(blob.readBigUInt64LE(o + 32)) };
        };
        const strtab = header(shstrndx).offset;
        for (let i = 0; i < shnum; i++) {
            const h = header(i);
            const start = strtab + h.name;
            const name = blob.toString("latin1", start, blob.indexOf(0, start));
            if (STUB_SECTIONS.has(name) && h.size) stubs.push([h.offset, h.size]);
        }
    }
    return { blob, segments, stubs };
}

function peImage(blob: Buffer): Image {
    const lfanew = blob.readUInt32LE(0x3c);
    const sections = blob.readUInt16LE(lfanew + 6), optSize = blob.readUInt16LE(lfanew + 20);
    const opt = lfanew + 24;
    const base = blob.readBigUInt64LE(opt + 24);
    const segments: Segment[] = [];
    for (let i = 0; i < sections; i++) {
        const o = opt + optSize + i * 40;
        segments.push({
            offset: blob.readUInt32LE(o + 20),
            va: base + BigInt(blob.readUInt32LE(o + 12)),
            size: blob.readUInt32LE(o + 16),
            exec: (blob.readUInt32LE(o + 36) & 0x20000000) !== 0,
        });
    }
    return { blob, segments, stubs: [] };
}

export function loadImage(file: string): Image | null {
    const blob = fs.readFileSync(file);
    if (blob.readUInt32BE(0) === 0x7f454c46) return elfImage(blob);
    if (blob.readUInt16BE(0) === 0x4d5a) return peImage(blob);
    return null;
}

function segmentOf(image: Image, offset: number): Segment | undefined {
    return image.segments.find((s) => s.offset <= offset && offset < s.offset + s.size);
}

function vaOf(image: Image, offset: number): bigint {
    const s = segmentOf(image, offset)!;
    return s.va + BigInt(offset - s.offset);
}

// Every offset where the pattern matches, anchored on its longest literal run so
// Buffer.indexOf (memchr) does the walking instead of a byte-by-byte loop.
function findAll(blob: Buffer, pattern: (number | null)[]): number[] {
    let bestStart = 0, bestLength = 0;
    for (let i = 0; i < pattern.length;) {
        if (pattern[i] === null) { i++; continue; }
        let j = i;
        while (j < pattern.length && pattern[j] !== null) j++;
        if (j - i > bestLength) { bestStart = i; bestLength = j - i; }
        i = j;
    }
    if (!bestLength) return [];
    const needle = Buffer.from(pattern.slice(bestStart, bestStart + bestLength) as number[]);
    const hits: number[] = [];
    for (let i = blob.indexOf(needle); i !== -1 && hits.length < HIT_LIMIT; i = blob.indexOf(needle, i + 1)) {
        const offset = i - bestStart;
        if (offset < 0 || offset + pattern.length > blob.length) continue;
        if (pattern.every((b, k) => b === null || blob[offset + k] === b)) hits.push(offset);
    }
    return hits;
}

const hex = (va: bigint) => `0x${va.toString(16)}`;

export function scan(image: Image, text: string): ScanResult {
    const pattern = parsePattern(text);
    if (!pattern) return { status: "unparsable" };
    const literals = pattern.filter((b) => b !== null).length;
    if (literals < MIN_LITERAL_BYTES) return { status: "too-few-literals", literals };

    // Only executable memory is scanned at runtime, and a linker stub never resolves.
    const all = findAll(image.blob, pattern);
    const hits = all.filter((h) => segmentOf(image, h)?.exec && !image.stubs.some(([start, size]) => start <= h && h < start + size));
    if (!hits.length) return { status: "broken", outsideCode: all.length };
    if (hits.length > 1) return { status: "ambiguous", count: hits.length, at: hits.slice(0, 4).map((h) => hex(vaOf(image, h))) };
    const va = vaOf(image, hits[0]);
    // A function head has padding before it or sits on a 16-byte boundary.
    const head = hits[0] > 0 && (PADDING.has(image.blob[hits[0] - 1]) || va % 16n === 0n);
    return { status: head ? "ok" : "ok-midfunction", at: hex(va) };
}
