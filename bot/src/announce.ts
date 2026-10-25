// One message per build in the updates channel, edited as autopilot reports
// each stage, with a thread underneath for the per-plugin detail.
import fs from "node:fs";
import path from "node:path";
import {
    AttachmentBuilder, ChannelType, EmbedBuilder, MessageFlags, type Client, type Message, type NewsChannel, type TextChannel,
} from "discord.js";
import { config } from "./config.ts";
import { GAMEVER_RE, type Repo } from "./repo.ts";
import { changesEmbed } from "./render.ts";
import { loadSettings } from "./settings.ts";

export type AutopilotEvent = { outcome: string; gamever: string; detail: string; at: number };

type BuildState = {
    messageId: string;
    threadId?: string;
    summaryId?: string;
    events: { outcome: string; at: number }[];
};
type AdminState = { messageId: string; count: number; first: number; last: number };
type State = { builds: Record<string, BuildState>; admin?: Record<string, AdminState> };

// What reaches the public channel. Anything else autopilot sends (sdk-abi, an
// outcome added later) goes to the admin channel only.
const OUTCOMES: Record<string, { title: string; color: number; final: boolean; summary: boolean }> = {
    started: { title: "detected, analysis running", color: 0xf1c40f, final: false, summary: false },
    "linux-deployed": { title: "linux deployed, windows next", color: 0x3498db, final: false, summary: true },
    "linux-held": { title: "linux analysed, held for review, windows next", color: 0xe67e22, final: false, summary: true },
    "linux-analysed": { title: "linux analysed, windows next", color: 0x3498db, final: false, summary: true },
    "linux-failed": { title: "linux early release stopped, windows goes ahead", color: 0xe67e22, final: false, summary: false },
    deployed: { title: "analysed and deployed", color: 0x2ecc71, final: true, summary: true },
    held: { title: "analysed, deploy held for review", color: 0xe67e22, final: true, summary: true },
    analysed: { title: "analysed", color: 0x3498db, final: true, summary: true },
    failed: { title: "failed - previous gamedata stays in place", color: 0xe74c3c, final: true, summary: false },
};

const OUTCOME_RE = /^[a-z][a-z0-9-]{0,31}$/;
// The same failure repeated within this window edits one admin message
// instead of posting again (a preflight refusal recurs on every timer tick).
const ADMIN_REPEAT_MS = 12 * 3600 * 1000;
const ADMIN_FORGET_MS = 7 * 24 * 3600 * 1000;
const RERUN_NEW_MESSAGE_MS = 6 * 3600 * 1000;
const TIMELINE_KEEP = 30;
const TIMELINE_SHOW = 12;

export function isKnownOutcome(outcome: string): boolean {
    return OUTCOME_RE.test(outcome);
}

function loadState(): State {
    try {
        return JSON.parse(fs.readFileSync(config.statePath, "utf8")) as State;
    } catch {
        return { builds: {} };
    }
}

function saveState(state: State): void {
    const tmp = `${config.statePath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
    fs.renameSync(tmp, config.statePath);
}

export function latestEvent(): { gamever: string; outcome: string; at: number } | null {
    let best: { gamever: string; outcome: string; at: number } | null = null;
    for (const [gamever, build] of Object.entries(loadState().builds)) {
        const last = build.events.at(-1);
        if (last && (!best || last.at > best.at)) best = { gamever, ...last };
    }
    return best;
}

function label(events: BuildState["events"], index: number): string {
    const event = events[index];
    const title = OUTCOMES[event.outcome]?.title ?? event.outcome;
    const retry = event.outcome === "started" && index > 0;
    return retry ? "re-run started" : title;
}

function buildEmbed(gamever: string, events: BuildState["events"]): EmbedBuilder {
    const last = events.at(-1)!;
    const spec = OUTCOMES[last.outcome];
    // The run's duration counts from the latest start, not the first attempt.
    const from = events.findLastIndex((e) => e.outcome === "started");
    const shown = events.map((e, i) => `<t:${Math.floor(e.at / 1000)}:t> ${label(events, i)}`);
    const hidden = shown.length - TIMELINE_SHOW;
    const timeline = (hidden > 0 ? [`… ${hidden} earlier`, ...shown.slice(-TIMELINE_SHOW)] : shown).join("\n");
    const embed = new EmbedBuilder()
        .setTitle(`CS2 ${gamever} - ${spec.title}`)
        .setColor(spec.color)
        .setURL(`${config.siteUrl}/game-data`)
        .addFields({ name: "Timeline", value: timeline.slice(-1024) })
        .setTimestamp(last.at);
    if (spec.final && from >= 0) {
        const minutes = Math.round((last.at - events[from].at) / 60000);
        embed.setFooter({ text: `took ${Math.floor(minutes / 60)}h ${minutes % 60}m` });
    }
    return embed;
}

async function updatesChannel(client: Client): Promise<TextChannel | NewsChannel> {
    const channel = await client.channels.fetch(config.updatesChannelId);
    if (channel?.type !== ChannelType.GuildText && channel?.type !== ChannelType.GuildAnnouncement) {
        throw new Error(`DISCORD_UPDATES_CHANNEL_ID ${config.updatesChannelId} is not a text or announcement channel`);
    }
    return channel;
}

// Several plugins ship a file with the same basename (gamedata.json, matchzy.json),
// so an attachment is named after its plugin too.
export function attachmentName(file: string): string {
    const plugin = file.split("/")[0];
    return `${plugin}-${path.basename(file)}`.replace(/[^A-Za-z0-9._-]/g, "_");
}

function firstLine(text: string): string {
    return (text.split("\n").find((line) => line.trim() && !line.startsWith("took ")) ?? "").slice(0, 200);
}

export class Announcer {
    // Events are applied one at a time, so two arriving together cannot both
    // create a message for the same build.
    private queue: Promise<void> = Promise.resolve();
    private client: Client;
    private repo: Repo;
    // Called after every applied event (the bot's status line follows the run).
    onApplied: () => void = () => undefined;

    constructor(client: Client, repo: Repo) {
        this.client = client;
        this.repo = repo;
    }

    handle(event: AutopilotEvent): void {
        this.queue = this.queue
            .then(() => this.apply(event))
            .catch((error) => console.error(`event ${event.outcome} ${event.gamever} failed:`, error))
            .then(() => this.onApplied());
    }

    private async apply(event: AutopilotEvent): Promise<void> {
        const state = loadState();
        try {
            const spec = OUTCOMES[event.outcome];
            const last = state.builds[event.gamever]?.events.at(-1);
            // Not a build stage, no real build, or a refusal while no run of this
            // build is open (low disk, dirty tree - repeated on every timer tick):
            // nothing for the public channel.
            const running = last !== undefined && !OUTCOMES[last.outcome]?.final;
            const preflight = event.outcome.endsWith("failed") && !running;
            if (!spec || !GAMEVER_RE.test(event.gamever) || preflight) {
                await this.admin(state, event);
                return;
            }
            await this.publish(state, event, spec.summary);
            if (event.outcome.endsWith("failed")) await this.admin(state, event);
        } finally {
            saveState(state);
        }
    }

    private async publish(state: State, event: AutopilotEvent, summary: boolean): Promise<void> {
        const channel = await updatesChannel(this.client);
        let known: BuildState | undefined = state.builds[event.gamever];
        // A retry continues the build's one message. A re-run started long after
        // the last event gets a new one, since an edit that far up goes unseen.
        if (known && event.outcome === "started" && event.at - known.events.at(-1)!.at > RERUN_NEW_MESSAGE_MS) {
            known = undefined;
        }
        const events = [...(known?.events ?? []), { outcome: event.outcome, at: event.at }].slice(-TIMELINE_KEEP);
        const embed = buildEmbed(event.gamever, events);

        // The files ride on the build message itself, so servers following the
        // channel get them too; each summary outcome replaces the previous set.
        const files = summary ? this.attachments(event.gamever) : undefined;
        let message: Message | null = null;
        if (known) message = await channel.messages.fetch(known.messageId).catch(() => null);
        if (message) {
            await message.edit(files ? { embeds: [embed], files, attachments: [] } : { embeds: [embed] });
        } else {
            // "started" says nothing a reader must act on yet: posted silently, so
            // nobody's phone buzzes for a run that may end in "nothing changed".
            const silent = event.outcome === "started" ? MessageFlags.SuppressNotifications : undefined;
            message = await channel.send({ embeds: [embed], files, flags: silent });
            // Publishing pushes the message to every server following the channel;
            // later edits reach them too.
            if (channel.type === ChannelType.GuildAnnouncement) await message.crosspost().catch(() => undefined);
        }
        const build: BuildState = { ...known, messageId: message.id, events };
        if (message.id !== known?.messageId) {
            build.threadId = undefined;
            build.summaryId = undefined;
        }
        state.builds[event.gamever] = build;

        if (!summary) return;
        // One summary per build, edited by linux-* and again by the final outcome.
        const thread = await this.thread(message, build, event.gamever);
        build.threadId = thread.id;
        const content = { embeds: [changesEmbed(this.repo, event.gamever)] };
        const previous = build.summaryId ? await thread.messages.fetch(build.summaryId).catch(() => null) : null;
        if (previous) await previous.edit(content);
        else build.summaryId = (await thread.send({ ...content, flags: MessageFlags.SuppressNotifications })).id;
    }

    // The files /settings selected, of those this build ships.
    private attachments(gamever: string): AttachmentBuilder[] {
        const settings = loadSettings();
        const changed = new Set(this.repo.changes(gamever).map((c) => c.file));
        const out: AttachmentBuilder[] = [];
        for (const file of settings.attachFiles) {
            if (settings.attachMode === "changed" && !changed.has(file)) continue;
            const full = this.repo.filePath(gamever, file);
            if (full) out.push(new AttachmentBuilder(full, { name: attachmentName(file) }));
        }
        return out;
    }

    // Re-attach after /settings changed, without waiting for the next build.
    // Resolves to the number of files attached, or null when the build has no message.
    refreshFiles(gamever: string): Promise<number | null> {
        const run = this.queue.then(async () => {
            const build = loadState().builds[gamever];
            if (!build) return null;
            const channel = await updatesChannel(this.client);
            const message = await channel.messages.fetch(build.messageId).catch(() => null);
            if (!message) return null;
            const files = this.attachments(gamever);
            await message.edit({ files, attachments: [] });
            return files.length;
        });
        this.queue = run.then(() => undefined, () => undefined);
        return run;
    }

    private async thread(message: Message, build: BuildState, gamever: string) {
        if (build.threadId) {
            const existing = await this.client.channels.fetch(build.threadId).catch(() => null);
            if (existing?.isThread()) return existing;
        }
        // state.json lost or stale: the message may already carry its thread.
        if (message.thread) return message.thread;
        return message.startThread({ name: `CS2 ${gamever} gamedata`, autoArchiveDuration: 10080 });
    }

    // Failure text carries hint commands and server log paths: admin channel only.
    // A repeat of the same failure edits its message with a counter.
    private async admin(state: State, event: AutopilotEvent): Promise<void> {
        if (!config.adminChannelId) return;
        const channel = await this.client.channels.fetch(config.adminChannelId).catch(() => null);
        if (!channel?.isSendable()) return;

        const admin = (state.admin ??= {});
        for (const [key, entry] of Object.entries(admin)) {
            if (event.at - entry.last > ADMIN_FORGET_MS) delete admin[key];
        }
        const key = `${event.gamever}|${event.outcome}|${firstLine(event.detail)}`;
        const detail = event.detail.length > 1700 ? `${event.detail.slice(0, 1700)}\n...` : event.detail;
        const body = (count: number, first: number) => {
            const repeat = count > 1 ? `\n-# seen ${count}× since <t:${Math.floor(first / 1000)}:f>, last <t:${Math.floor(event.at / 1000)}:R>` : "";
            return `**CS2 ${event.gamever} ${event.outcome}**\n\`\`\`\n${detail}\n\`\`\`${repeat}`;
        };

        const entry = admin[key];
        if (entry && event.at - entry.last < ADMIN_REPEAT_MS) {
            const message = await channel.messages.fetch(entry.messageId).catch(() => null);
            if (message) {
                entry.count += 1;
                entry.last = event.at;
                await message.edit({ content: body(entry.count, entry.first) });
                return;
            }
        }
        const message = await channel.send({ content: body(1, event.at) });
        admin[key] = { messageId: message.id, count: 1, first: event.at, last: event.at };
    }
}
