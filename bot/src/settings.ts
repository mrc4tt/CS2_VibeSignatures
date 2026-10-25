// What admins choose from Discord (/settings), read on every use so a change
// applies to the next build without a restart or an edit of .env.
import fs from "node:fs";
import path from "node:path";
import { config } from "./config.ts";

export type AttachMode = "changed" | "always";
export type Settings = {
    // Shipped file paths (as diagnostics lists them) attached to the build message.
    attachFiles: string[];
    // "changed": only the selected files this build changed. "always": every selected file.
    attachMode: AttachMode;
};

// Discord allows 10 attachments per message.
export const MAX_ATTACHMENTS = 10;
const DEFAULTS: Settings = { attachFiles: [], attachMode: "changed" };

export function loadSettings(): Settings {
    try {
        const raw = JSON.parse(fs.readFileSync(config.settingsPath, "utf8")) as Partial<Settings>;
        return {
            attachFiles: Array.isArray(raw.attachFiles) ? raw.attachFiles.filter((f) => typeof f === "string").slice(0, MAX_ATTACHMENTS) : [],
            attachMode: raw.attachMode === "always" ? "always" : "changed",
        };
    } catch {
        return { ...DEFAULTS };
    }
}

export function saveSettings(settings: Settings): void {
    fs.mkdirSync(path.dirname(config.settingsPath), { recursive: true });
    const tmp = `${config.settingsPath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(settings, null, 2));
    fs.renameSync(tmp, config.settingsPath);
}
