// Runs the renderers against the repository's real data, with no Discord
// connection: every embed must fit Discord's limits for every published build.
import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";

Object.assign(process.env, {
    DISCORD_TOKEN: "test", DISCORD_APPLICATION_ID: "1", DISCORD_GUILD_ID: "1",
    DISCORD_UPDATES_CHANNEL_ID: "1", BOT_EVENT_SECRET: "secret",
    REPO_ROOT: path.resolve(import.meta.dirname, "..", ".."),
});
const { Repo } = await import("../src/repo.ts");
const { changesEmbed, fileEmbed, keyEmbed, statusEmbed } = await import("../src/render.ts");
const { parseEvent } = await import("../src/server.ts");

const repo = new Repo(process.env.REPO_ROOT!);

function size(embed: { toJSON(): object }): number {
    const json = embed.toJSON() as { title?: string; description?: string; fields?: { name: string; value: string }[]; footer?: { text: string } };
    for (const field of json.fields ?? []) {
        assert.ok(field.value.length <= 1024, `field ${field.name} is ${field.value.length} chars`);
        assert.ok(field.name.length <= 256, `field name ${field.name}`);
    }
    assert.ok((json.fields ?? []).length <= 25);
    return (json.title ?? "").length + (json.description ?? "").length + (json.footer?.text ?? "").length
        + (json.fields ?? []).reduce((n, f) => n + f.name.length + f.value.length, 0);
}

test("changes embed fits Discord's limits for every build with diagnostics", () => {
    const builds = repo.builds().filter((b) => repo.diagnostics(b));
    assert.ok(builds.length > 0);
    for (const build of builds) assert.ok(size(changesEmbed(repo, build)) <= 6000, build);
});

test("the newest build lists its shipped files and their changes", () => {
    const latest = repo.latestBuild()!;
    assert.ok(repo.shippedFiles(latest).length > 0);
    for (const file of repo.shippedFiles(latest)) {
        assert.ok(repo.filePath(latest, file), file);
        assert.ok(size(fileEmbed(repo, latest, file)) <= 6000);
    }
    assert.ok(size(statusEmbed(repo, null)) <= 6000);
});

test("a path outside the shipped list is refused", () => {
    const latest = repo.latestBuild()!;
    assert.equal(repo.filePath(latest, "../../etc/passwd"), null);
    assert.equal(repo.filePath(latest, "history.json"), null);
    assert.equal(repo.diagnostics("../x"), null);
});

test("every key in the history renders", () => {
    for (const [file, keys] of Object.entries(repo.history()!.files)) {
        for (const key of Object.keys(keys)) {
            const embed = keyEmbed(repo, file, key);
            if (embed) assert.ok(size(embed) <= 6000, key);
        }
    }
});

test("events are validated", () => {
    assert.equal(parseEvent("not json"), null);
    assert.equal(parseEvent(JSON.stringify({ outcome: "rm -rf", gamever: "14192" })), null);
    assert.equal(parseEvent(JSON.stringify({ outcome: "deployed", gamever: "../14192" })), null);
    assert.deepEqual(
        { ...parseEvent(JSON.stringify({ outcome: "deployed", gamever: "14192", detail: "x" })), at: 0 },
        { outcome: "deployed", gamever: "14192", detail: "x", at: 0 },
    );
});

test("changes are against the previous build, not the plugin's template", () => {
    // 14191's files are identical to 14190's while their metadata lists template diffs.
    assert.deepEqual(repo.changes("14191"), []);
    for (const build of repo.history()!.builds) {
        if (!repo.diagnostics(build.gameVersion)) continue;
        const keys = repo.changes(build.gameVersion).reduce((n, f) => n + new Set(f.changes.map((c) => c.key)).size, 0);
        // Old builds' diagnostics list fewer files than the history tracks (14181).
        if (build.gameVersion === repo.latestBuild()) assert.equal(keys, build.keyChanges, build.gameVersion);
        else assert.ok(keys <= build.keyChanges, build.gameVersion);
    }
});

test("/help lists every command, /settings only for admins", async () => {
    const { definitions, helpEmbed } = await import("../src/commands.ts");
    const everyone = helpEmbed(false).toJSON().description!;
    const admins = helpEmbed(true).toJSON().description!;
    for (const c of definitions) {
        if (c.name === "settings") continue;
        assert.ok(everyone.includes(`/${c.name}`), c.name);
    }
    assert.ok(!everyone.includes("/settings"));
    assert.ok(admins.includes("/settings"));
    assert.ok(size(helpEmbed(true)) <= 6000);
});

test("the status line names the newest build, or the one being analysed", async () => {
    const { presenceText } = await import("../src/presence.ts");
    const latest = repo.latestBuild()!;
    assert.equal(presenceText(repo, null), `Gamedata for CS2 ${latest} · /help`);
    assert.equal(presenceText(repo, { gamever: latest, outcome: "deployed" }), `Gamedata for CS2 ${latest} · /help`);
    assert.ok(presenceText(repo, { gamever: "99999", outcome: "started" }).startsWith("Analysing CS2 99999"));
    assert.ok(presenceText(repo, { gamever: "99999", outcome: "linux-deployed" }).length <= 128);
});
