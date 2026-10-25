// The anti-spam rules, against a fake Discord: how many messages each sequence
// of autopilot events posts, and where.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { beforeEach, test } from "node:test";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cs2vibe-bot-"));
Object.assign(process.env, {
    DISCORD_TOKEN: "test", DISCORD_APPLICATION_ID: "1", DISCORD_GUILD_ID: "1",
    DISCORD_UPDATES_CHANNEL_ID: "updates", DISCORD_ADMIN_CHANNEL_ID: "admin", BOT_EVENT_SECRET: "secret",
    REPO_ROOT: path.resolve(import.meta.dirname, "..", ".."), BOT_STATE_PATH: path.join(dir, "state.json"),
    BOT_SETTINGS_PATH: path.join(dir, "settings.json"),
});
const { ChannelType } = await import("discord.js");
const { Announcer } = await import("../src/announce.ts");
const { Repo } = await import("../src/repo.ts");
const { saveSettings } = await import("../src/settings.ts");

type Log = { sends: number; edits: number; files?: number };
let next = 0;
const counts = (log: Log) => ({ sends: log.sends, edits: log.edits });
const registry: Record<string, unknown> = {};

function fakeChannel(type: number, log: Log, threadLog?: Log) {
    const messages = new Map<string, object>();
    const make = (payload: unknown) => {
        const message = {
            id: `m${next++}`,
            payload,
            edit: async (p: { files?: unknown[] }) => { log.edits++; message.payload = p; if (p.files) log.files = p.files.length; },
            crosspost: async () => undefined,
            startThread: async () => fakeChannel(ChannelType.PublicThread, threadLog!, threadLog),
            thread: null,
        };
        messages.set(message.id, message);
        return message;
    };
    const channel = {
        id: `c${next++}`,
        type,
        isSendable: () => true,
        isThread: () => type === ChannelType.PublicThread,
        send: async (payload: { files?: unknown[] }) => { log.sends++; if (payload.files) log.files = payload.files.length; return make(payload); },
        messages: { fetch: async (id: string) => { if (!messages.has(id)) throw new Error("gone"); return messages.get(id); } },
    };
    registry[channel.id] = channel;
    return channel;
}

let pub: Log, thread: Log, admin: Log, announcer: InstanceType<typeof Announcer>;
let clock = Date.parse("2026-10-25T00:00:00Z");

beforeEach(() => {
    fs.rmSync(process.env.BOT_STATE_PATH!, { force: true });
    fs.rmSync(process.env.BOT_SETTINGS_PATH!, { force: true });
    pub = { sends: 0, edits: 0 }; thread = { sends: 0, edits: 0 }; admin = { sends: 0, edits: 0 };
    registry.updates = fakeChannel(ChannelType.GuildText, pub, thread);
    registry.admin = fakeChannel(ChannelType.GuildText, admin);
    const client = { channels: { fetch: async (id: string) => registry[id] ?? null } };
    announcer = new Announcer(client as never, new Repo(process.env.REPO_ROOT!));
});

async function send(outcome: string, gamever = "14192", detail = "x", minutes = 10) {
    clock += minutes * 60000;
    announcer.handle({ outcome, gamever, detail, at: clock });
    await (announcer as unknown as { queue: Promise<void> }).queue;
}

test("a whole linux-first run posts one message and one summary", async () => {
    await send("started");
    await send("linux-deployed");
    await send("deployed");
    assert.deepEqual(counts(pub), { sends: 1, edits: 2 });
    assert.deepEqual(counts(thread), { sends: 1, edits: 1 });
    assert.deepEqual(counts(admin), { sends: 0, edits: 0 });
});

test("a preflight refusal repeated every tick is one admin message and nothing public", async () => {
    for (let i = 0; i < 6; i++) await send("failed", "unknown", "took 0h 0m\nonly 3G free, need 60G", 5);
    for (let i = 0; i < 3; i++) await send("failed", "14193", "the working tree has uncommitted changes", 5);
    assert.deepEqual(counts(pub), { sends: 0, edits: 0 });
    assert.deepEqual(counts(admin), { sends: 2, edits: 7 });
});

test("a failed run then its retry stay in one public message", async () => {
    await send("started");
    await send("failed", "14192", "took 1h 0m\nstep x broke");
    await send("failed", "14192", "took 1h 0m\nstep x broke", 5); // refused tick: admin repeat only
    await send("started");
    await send("deployed");
    assert.deepEqual(counts(pub), { sends: 1, edits: 3 });
    assert.deepEqual(counts(admin), { sends: 1, edits: 1 });
    assert.deepEqual(counts(thread), { sends: 1, edits: 0 });
});

test("a re-run days later gets a new message", async () => {
    await send("started");
    await send("deployed");
    await send("started", "14192", "x", 3 * 24 * 60);
    assert.equal(pub.sends, 2);
});

test("outcomes that are not build stages go to admin only", async () => {
    await send("sdk-abi", "14192", "IVEngineServer2 slot moved");
    assert.deepEqual(counts(pub), { sends: 0, edits: 0 });
    assert.equal(admin.sends, 1);
});

test("files chosen in /settings ride on the build message, per mode, without a restart", async () => {
    const repo = new Repo(process.env.REPO_ROOT!);
    const build = "14191";
    const shipped = repo.shippedFiles(build).slice(0, 10);
    const changed = new Set(repo.changes(build).map((c) => c.file));
    const expectChanged = shipped.filter((f) => changed.has(f)).length;
    assert.ok(expectChanged < shipped.length, "need an unchanged shipped file in the fixture build");

    await send("started", build);
    assert.equal(pub.files, undefined);
    saveSettings({ attachFiles: shipped, attachMode: "changed" });
    await send("deployed", build);
    assert.equal(pub.files, expectChanged);

    saveSettings({ attachFiles: shipped, attachMode: "always" });
    assert.equal(await announcer.refreshFiles(build), shipped.length);
    assert.equal(pub.files, shipped.length);

    saveSettings({ attachFiles: [], attachMode: "always" });
    assert.equal(await announcer.refreshFiles(build), 0);
    assert.equal(pub.files, 0);
    assert.equal(await announcer.refreshFiles("14100"), null);
});

test("settings never name a file outside the shipped list", async () => {
    saveSettings({ attachFiles: ["../../etc/passwd", "history.json"], attachMode: "always" });
    await send("started");
    await send("deployed");
    assert.equal(pub.files, 0);
});
