import path from "node:path";
import { EmbedBuilder } from "discord.js";
import { config } from "./config.ts";
import { pluginOf, type DiagnosticsFile, type KeyVerdict, type PlatformVerification, type Repo } from "./repo.ts";
import type { ScanResult } from "./scan.ts";

export function fileLabel(file: string): string {
    return `${pluginOf(file)} · ${path.basename(file)}`;
}

function clip(text: string, limit: number): string {
    return text.length > limit ? `${text.slice(0, limit - 2)}\n…` : text;
}

function verificationLine(file: DiagnosticsFile | undefined): string {
    if (!file?.verification) return "not verified";
    const side = (name: string, v?: PlatformVerification) => {
        if (!v) return null;
        const total = v.verified + v.contradicted + v.unverified + v.upstream;
        const bad = v.contradicted ? `, **${v.contradicted} contradicted**` : "";
        return `${name} ${v.verified}/${total}${bad}`;
    };
    const parts = [side("linux", file.verification.linux), side("windows", file.verification.windows)].filter(Boolean);
    const health = file.unhealthy ? `**${file.unhealthy} unhealthy**` : "healthy";
    return `${health} · ${parts.join(" · ")}`;
}

function compactVerification(file: DiagnosticsFile | undefined): string {
    const l = file?.verification?.linux, w = file?.verification?.windows;
    if (!l || !w) return "not verified";
    const total = (v: PlatformVerification) => v.verified + v.contradicted + v.unverified + v.upstream;
    const sides = l.verified === w.verified && total(l) === total(w)
        ? `${l.verified}/${total(l)} verified`
        : `linux ${l.verified}/${total(l)} · windows ${w.verified}/${total(w)}`;
    const bad = (file?.unhealthy ?? 0) + l.contradicted + w.contradicted;
    return bad ? `${sides} · **${bad} problem(s)**` : sides;
}

// The answer a server owner wants, one line per plugin: which need the new
// file, which do not. The keys themselves are one /changes file: away.
export function changesEmbed(repo: Repo, gamever: string): EmbedBuilder {
    const diagnostics = repo.diagnostics(gamever);
    const byPath = new Map((diagnostics?.plugins.files ?? []).map((f) => [f.path, f]));
    const changed = repo.changes(gamever);
    const changedPaths = new Set(changed.map((c) => c.file));

    const embed = new EmbedBuilder()
        .setTitle(`CS2 ${gamever} - what changed per plugin`)
        .setURL(`${config.siteUrl}/game-data`)
        .setColor(changed.length ? 0x2ecc71 : 0x95a5a6);

    if (!diagnostics) {
        return embed.setDescription("No diagnostics for this build yet - the site publish has not run.");
    }

    const lines: string[] = [];
    if (changed.length) {
        lines.push("**Update these**");
        for (const fileChanges of changed) {
            const keys = new Set(fileChanges.changes.map((c) => c.key)).size;
            lines.push(`${fileLabel(fileChanges.file)} - ${keys} key(s) · ${compactVerification(byPath.get(fileChanges.file))}`);
        }
    }
    const unchanged = [...byPath.keys()].filter((p) => !changedPaths.has(p));
    if (unchanged.length) {
        if (lines.length) lines.push("");
        lines.push("**No change - nothing to do**");
        lines.push(unchanged.map(fileLabel).join(", "));
    }
    embed.setDescription(clip(lines.join("\n"), 4096));
    embed.setFooter({ text: `Keys per file: /changes file:<plugin> · check your own file: ${config.siteUrl}/check` });
    return embed;
}

// The keys one file changed in a build, with the platforms each changed on.
export function fileChangesEmbed(repo: Repo, gamever: string, file: string): EmbedBuilder {
    const diagnostics = repo.diagnostics(gamever)?.plugins.files.find((f) => f.path === file);
    const changes = repo.changes(gamever).find((c) => c.file === file)?.changes ?? [];
    const keys = new Map<string, Set<string>>();
    for (const change of changes) {
        if (!keys.has(change.key)) keys.set(change.key, new Set());
        keys.get(change.key)!.add(change.platform);
    }
    const lines = [...keys].map(([key, platforms]) => {
        const sides = [...platforms].filter(Boolean).sort();
        return sides.length ? `\`${key}\` (${sides.join(", ")})` : `\`${key}\``;
    });
    return new EmbedBuilder()
        .setTitle(`${fileLabel(file)} - CS2 ${gamever}`)
        .setURL(`${config.siteUrl}/game-data`)
        .setColor(keys.size ? 0x2ecc71 : 0x95a5a6)
        .setDescription(clip(`${verificationLine(diagnostics)}\n\n${lines.length ? lines.join("\n") : "No key changed in this build."}`, 4096))
        .setFooter({ text: `${keys.size} key(s) changed` });
}

export function statusEmbed(repo: Repo, last: { gamever: string; outcome: string; at: number } | null): EmbedBuilder {
    const history = repo.history();
    const latest = history?.gameVersion ?? "unknown";
    const diagnostics = repo.diagnostics(latest);
    const embed = new EmbedBuilder().setTitle("CS2_VibeSignatures status").setURL(config.siteUrl).setColor(0x5865f2);

    embed.addFields({ name: "Newest published build", value: latest, inline: true });
    const build = history?.builds.find((b) => b.gameVersion === latest);
    if (build) {
        const published = Math.floor(Date.parse(build.publishedAt) / 1000);
        embed.addFields(
            { name: "Published", value: `<t:${published}:R>`, inline: true },
            { name: "Key changes", value: String(build.keyChanges), inline: true },
        );
    }
    if (last) {
        const running = last.outcome === "started" || last.outcome.startsWith("linux-");
        embed.addFields({
            name: running ? "Running now" : "Last autopilot run",
            value: `${last.gamever}: ${last.outcome} <t:${Math.floor(last.at / 1000)}:R>`,
        });
    }
    if (diagnostics) {
        const files = diagnostics.plugins.files;
        const healthy = files.filter((f) => !f.unhealthy).length;
        const v = diagnostics.validator;
        embed.addFields(
            { name: "Shipped files", value: `${healthy}/${files.length} healthy`, inline: true },
            { name: "Artifacts", value: `${v?.artifacts ?? "?"} (${v?.errors ?? "?"} errors)`, inline: true },
        );
    }
    return embed;
}

function codeValue(value: string | number | null): string {
    if (value === null) return "*none*";
    return clip(`\`\`\`\n${value}\n\`\`\``, 1024);
}

export function keyEmbed(repo: Repo, file: string, key: string): EmbedBuilder | null {
    const record = repo.history()?.files[file]?.[key];
    if (!record?.points.length) return null;
    const [build, linux, windows] = record.points.at(-1)!;
    const changes = record.changes.slice(-15).join(", ") || "never";
    return new EmbedBuilder()
        .setTitle(key)
        .setDescription(`${fileLabel(file)}\nCurrent since **${build}**`)
        .setURL(`${config.siteUrl}/game-data`)
        .setColor(0x5865f2)
        .addFields(
            { name: "linux", value: codeValue(linux) },
            { name: "windows", value: codeValue(windows) },
            { name: "Changed in", value: clip(changes, 1024) },
        );
}

export function fileEmbed(repo: Repo, gamever: string, file: string): EmbedBuilder {
    const diagnostics = repo.diagnostics(gamever)?.plugins.files.find((f) => f.path === file);
    const changed = repo.changes(gamever).find((c) => c.file === file);
    const keys = new Set(changed?.changes.map((c) => c.key));
    return new EmbedBuilder()
        .setTitle(`${fileLabel(file)} - CS2 ${gamever}`)
        .setDescription(`\`${file}\``)
        .setColor(0x5865f2)
        .addFields(
            { name: "Verification", value: verificationLine(diagnostics) },
            { name: "Changed in this build", value: keys.size ? clip([...keys].map((k) => `\`${k}\``).join(", "), 1024) : "nothing" },
        );
}

// verify_plugin_gamedata statuses that pass; the same set publish_site_data.py uses.
const PASS_STATUSES = new Set(["ok", "match", "ok-midfunction", "ok-globalref"]);

function verdictText(v: KeyVerdict): string {
    const where = v.at ? ` ${v.at}` : "";
    if (v.status === "ambiguous") return `**AMBIGUOUS** (${v.count ?? "2+"} hits)`;
    if (v.status === "broken") return "**BROKEN** (0 hits)";
    if (!PASS_STATUSES.has(v.status)) return `**${v.status}**`;
    const state = v.verification && v.verification !== "verified" ? ` (${v.verification})` : "";
    return `${v.status}${where}${state}`;
}

// Every entry of one shipped file and whether it resolves on each platform, so
// "is key X still good" needs no scan and no AI.
export function verifyEmbed(repo: Repo, gamever: string, file: string): EmbedBuilder {
    const diagnostics = repo.diagnostics(gamever)?.plugins.files.find((f) => f.path === file);
    const embed = new EmbedBuilder()
        .setTitle(`${fileLabel(file)} - verify on CS2 ${gamever}`)
        .setURL(`${config.siteUrl}/game-data`);
    if (!diagnostics) return embed.setColor(0x95a5a6).setDescription("No verification for this file and build.");

    const bad = (v: KeyVerdict) => !PASS_STATUSES.has(v.status) || v.verification === "contradicted";
    const summary = verificationLine(diagnostics);
    let body: string;
    if (diagnostics.keys) {
        const byKey = new Map<string, KeyVerdict[]>();
        for (const v of diagnostics.keys) {
            if (!byKey.has(v.name)) byKey.set(v.name, []);
            byKey.get(v.name)!.push(v);
        }
        // Broken keys first: they are what the asker is looking for.
        const rows = [...byKey].sort(([, a], [, b]) => Number(b.some(bad)) - Number(a.some(bad)));
        body = rows.map(([key, verdicts]) =>
            `\`${key}\`\n` + verdicts.map((v) => `  ${v.platform}: ${verdictText(v)}`).join("\n")).join("\n");
    } else {
        // Published before every verdict was kept: only the problems are known.
        const problems = diagnostics.problems ?? [];
        body = (problems.length
            ? problems.map((v) => `\`${v.name}\` ${v.platform}: ${verdictText(v)}`).join("\n")
            : "Every entry passed.")
            + "\n\n*Per-key detail starts with the next published build.*";
    }
    const broken = diagnostics.unhealthy || diagnostics.keys?.some(bad);
    return embed
        .setColor(broken ? 0xe74c3c : 0x2ecc71)
        .setDescription(clip(`${summary}\n\n${body}`, 4096))
        .setFooter({ text: "Scan any pattern yourself: /check" });
}

export function checkEmbed(gamever: string, module: string, platform: string, pattern: string, result: ScanResult): EmbedBuilder {
    let verdict: string, color: number;
    switch (result.status) {
        case "ok":
            [verdict, color] = [`**1 hit** at \`${result.at}\`, on a function head. Resolves.`, 0x2ecc71];
            break;
        case "ok-midfunction":
            [verdict, color] = [`**1 hit** at \`${result.at}\`, inside a function (not on its head). Resolves, but check it is meant to.`, 0xf1c40f];
            break;
        case "ambiguous":
            [verdict, color] = [`**${result.count}${result.count >= 64 ? "+" : ""} hits** - ambiguous, a plugin may resolve the wrong one: ${result.at.map((a) => `\`${a}\``).join(", ")}`, 0xe74c3c];
            break;
        case "broken":
            [verdict, color] = [`**0 hits** in code - broken.${result.outsideCode ? ` (${result.outsideCode} outside executable code, which plugins do not scan.)` : ""}`, 0xe74c3c];
            break;
        case "too-few-literals":
            [verdict, color] = [`Only ${result.literals} literal byte(s); CounterStrikeSharp refuses fewer than 4.`, 0xe74c3c];
            break;
        default:
            [verdict, color] = ["Not a pattern: use hex bytes with `?` wildcards (`55 48 89 E5 ? ?`) or `\\x55\\x2A` escapes.", 0xe74c3c];
    }
    return new EmbedBuilder()
        .setTitle(`Signature check - ${module} ${platform}, CS2 ${gamever}`)
        .setColor(color)
        .setDescription(clip(`${verdict}\n\n\`\`\`\n${pattern}\n\`\`\``, 4096));
}
