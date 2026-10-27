// /check's scanner: the parsing and verdict rules of verify_plugin_gamedata.check_signature.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { loadImage, parsePattern, scan, type Image } from "../src/scan.ts";

// One executable segment at VA 0x1000 holding `code`, behind 16 bytes of data.
function fakeImage(code: number[]): Image {
    const blob = Buffer.from([...new Array(16).fill(0), ...code]);
    return {
        blob,
        segments: [
            { offset: 0, va: 0n, size: 16, exec: false },
            { offset: 16, va: 0x1000n, size: code.length, exec: true },
        ],
        stubs: [],
    };
}

test("patterns parse the way CounterStrikeSharp reads them", () => {
    assert.deepEqual(parsePattern("55 48 ? ?? E5"), [0x55, 0x48, null, null, 0xe5]);
    assert.deepEqual(parsePattern("\\x55\\x2A\\x89"), [0x55, null, 0x89]);
    assert.equal(parsePattern("5548 89"), null);
    assert.equal(parsePattern("55 4"), null);
    assert.equal(parsePattern(""), null);
});

test("one hit on a function head resolves", () => {
    const image = fakeImage([0xcc, 0x55, 0x48, 0x89, 0xe5, 0x41, 0x57]);
    assert.deepEqual(scan(image, "55 48 89 E5 ? 57"), { status: "ok", at: "0x1001" });
});

test("a hit mid-function still resolves but is flagged", () => {
    const image = fakeImage([0x00, 0x55, 0x48, 0x89, 0xe5, 0x41]);
    assert.deepEqual(scan(image, "55 48 89 E5"), { status: "ok-midfunction", at: "0x1001" });
});

test("two hits are ambiguous, none is broken, data hits do not count", () => {
    const image = fakeImage([0x55, 0x48, 0x89, 0xe5, 0xcc, 0x55, 0x48, 0x89, 0xe5]);
    assert.deepEqual(scan(image, "55 48 89 E5"), { status: "ambiguous", count: 2, at: ["0x1000", "0x1005"] });
    assert.deepEqual(scan(image, "55 48 89 E6"), { status: "broken", outsideCode: 0 });
    image.blob[0] = 0x41; image.blob[1] = 0x57; image.blob[2] = 0x41; image.blob[3] = 0x56;
    assert.deepEqual(scan(image, "41 57 41 56"), { status: "broken", outsideCode: 1 });
});

test("fewer than 4 literal bytes is refused", () => {
    assert.deepEqual(scan(fakeImage([0x55, 0x48, 0x89]), "55 ? 48 89"), { status: "too-few-literals", literals: 3 });
});

// A real ELF when one is on disk (the depot copy is not committed, so this skips in CI).
const depot = path.resolve(import.meta.dirname, "..", "..", "cs2_depot/game/csgo/bin/linuxsteamrt64/libserver.so");
test("parses a real libserver.so", { skip: !fs.existsSync(depot) }, () => {
    const image = loadImage(depot)!;
    assert.ok(image.segments.some((s) => s.exec));
    assert.ok(image.stubs.length > 0);
    // Every image starts with the ELF magic, which is not code.
    assert.equal(scan(image, "7F 45 4C 46").status, "broken");
});
