// Event "server-reports": which gamedata keys CounterStrikeSharp servers report
// broken on a build (plugin_reports.py's tally, counts only - no server ids).
// Admin channel only; one message per build, edited as the numbers change.
import { EmbedBuilder } from "discord.js";

export type ReportKey = { key: string; servers: number; linux: number; windows: number };
export type ReportFile = {
    file: string; status: string; servers: number; broken_servers: number; broken: ReportKey[]; more_keys: number;
};
export type ServerReports = {
    servers: number; files_seen: number; files_broken: number; files: ReportFile[]; more_files: number; last_seen: number;
};

const MAX_FILES = 50;
const MAX_KEYS = 50;
const DESCRIPTION_LIMIT = 3900;

const count = (value: unknown): number =>
    typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.min(Math.floor(value), 1e9) : 0;
// Shown inside a code span: a backtick would end it early.
const text = (value: unknown, limit: number): string =>
    (typeof value === "string" ? value : "?").replace(/[`\r\n]/g, "").slice(0, limit) || "?";

// Only the shape the renderer uses survives; anything else in the body is dropped.
export function parseReports(data: unknown): ServerReports | null {
    if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
    const raw = data as Record<string, unknown>;
    if (!Array.isArray(raw.files)) return null;
    const files: ReportFile[] = raw.files.slice(0, MAX_FILES).flatMap((f): ReportFile[] => {
        if (typeof f !== "object" || f === null) return [];
        const file = f as Record<string, unknown>;
        const broken = (Array.isArray(file.broken) ? file.broken : []).slice(0, MAX_KEYS).flatMap((k): ReportKey[] => {
            if (typeof k !== "object" || k === null) return [];
            const key = k as Record<string, unknown>;
            return [{ key: text(key.key, 100), servers: count(key.servers), linux: count(key.linux), windows: count(key.windows) }];
        });
        return [{
            file: text(file.file, 120), status: text(file.status, 16), servers: count(file.servers),
            broken_servers: count(file.broken_servers), broken, more_keys: count(file.more_keys),
        }];
    });
    return {
        servers: count(raw.servers), files_seen: count(raw.files_seen), files_broken: count(raw.files_broken),
        files, more_files: count(raw.more_files) + Math.max(0, raw.files.length - MAX_FILES), last_seen: count(raw.last_seen),
    };
}

function keyLine(key: ReportKey): string {
    const split = [key.linux ? `linux ${key.linux}` : "", key.windows ? `windows ${key.windows}` : ""].filter(Boolean).join(", ");
    return `\`${String(key.servers).padStart(4)}\` \`${key.key}\`${split ? ` - ${split}` : ""}`;
}

export function reportsEmbed(gamever: string, reports: ServerReports): EmbedBuilder {
    const head = `${reports.servers} server(s) reported, ${reports.files_broken} of ${reports.files_seen} file(s) with broken keys` +
        (reports.last_seen ? `, last <t:${reports.last_seen}:R>` : "");
    const lines = [head];
    let length = head.length;
    let hiddenFiles = reports.more_files;
    let hiddenKeys = 0;
    for (const [index, file] of reports.files.entries()) {
        const block = [
            "",
            `**${file.file}** - ${file.status}, ${file.broken_servers}/${file.servers} server(s) affected`,
            ...file.broken.map(keyLine),
            ...(file.more_keys ? [`-# ... ${file.more_keys} more key(s)`] : []),
        ];
        const size = block.join("\n").length + 1;
        if (length + size > DESCRIPTION_LIMIT) {
            hiddenFiles += reports.files.length - index;
            hiddenKeys += reports.files.slice(index).reduce((n, f) => n + f.broken.length + f.more_keys, 0);
            break;
        }
        lines.push(...block);
        length += size;
    }
    if (hiddenFiles) lines.push("", `-# ... ${hiddenFiles} more file(s)${hiddenKeys ? `, ${hiddenKeys} key(s)` : ""} not shown`);
    const worst = reports.files[0]?.broken_servers ?? 0;
    return new EmbedBuilder()
        .setTitle(`CS2 ${gamever} - gamedata keys broken on servers`)
        .setColor(worst >= 5 ? 0xe74c3c : worst > 0 ? 0xe67e22 : 0x2ecc71)
        .setDescription(lines.join("\n"))
        .setFooter({ text: `servers that opted in to GamedataReportEnabled · uv run plugin_reports.py broken ${gamever}` });
}
