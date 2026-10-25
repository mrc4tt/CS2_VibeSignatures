import path from "node:path";
import { EmbedBuilder } from "discord.js";
import { config } from "./config.ts";
import { pluginOf, type DiagnosticsFile, type PlatformVerification, type Repo } from "./repo.ts";

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
