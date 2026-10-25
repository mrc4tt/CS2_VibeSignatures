import path from "node:path";

function required(name: string): string {
    const value = process.env[name]?.trim();
    if (!value) throw new Error(`${name} is not set (see bot/.env.example)`);
    return value;
}

function optional(name: string, fallback = ""): string {
    return process.env[name]?.trim() || fallback;
}

export const config = {
    token: required("DISCORD_TOKEN"),
    applicationId: required("DISCORD_APPLICATION_ID"),
    guildId: required("DISCORD_GUILD_ID"),
    updatesChannelId: required("DISCORD_UPDATES_CHANNEL_ID"),
    adminChannelId: optional("DISCORD_ADMIN_CHANNEL_ID"),
    httpPort: Number(optional("BOT_HTTP_PORT", "13410")),
    eventSecret: required("BOT_EVENT_SECRET"),
    repoRoot: path.resolve(optional("REPO_ROOT", path.resolve(import.meta.dirname, "..", ".."))),
    siteUrl: optional("SITE_URL", "https://sig.miksen.me").replace(/\/+$/, ""),
    statePath: path.resolve(optional("BOT_STATE_PATH", path.resolve(import.meta.dirname, "..", "state.json"))),
    settingsPath: path.resolve(optional("BOT_SETTINGS_PATH", path.resolve(import.meta.dirname, "..", "settings.json"))),
};
