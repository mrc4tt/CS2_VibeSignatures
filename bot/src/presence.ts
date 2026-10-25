// The bot's status line under its name: the newest build it has gamedata for,
// or the build being analysed right now.
import { ActivityType, type Client } from "discord.js";
import { latestEvent } from "./announce.ts";
import { type Repo } from "./repo.ts";

export function presenceText(repo: Repo, last: { gamever: string; outcome: string } | null): string {
    const latest = repo.latestBuild();
    const running = last && (last.outcome === "started" || last.outcome.startsWith("linux-"));
    if (running) return latest && latest !== last.gamever
        ? `Analysing CS2 ${last.gamever}… · gamedata ${latest} · /help`
        : `Analysing CS2 ${last.gamever}… · /help`;
    return latest ? `Gamedata for CS2 ${latest} · /help` : "/help";
}

export function updatePresence(client: Client, repo: Repo): void {
    const text = presenceText(repo, latestEvent());
    // Setting the same activity again is cheap but still a gateway call: skip it.
    if (client.user?.presence.activities[0]?.state === text) return;
    client.user?.setPresence({ status: "online", activities: [{ type: ActivityType.Custom, name: "custom", state: text }] });
}
