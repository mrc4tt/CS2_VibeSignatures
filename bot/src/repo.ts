// Read-only views of what the pipeline already wrote. Nothing here runs the
// pipeline or writes to the repository; every path is built from values the
// repository itself lists, never from user input.
import fs from "node:fs";
import path from "node:path";

export const GAMEVER_RE = /^\d{5}[a-z]?$/;

export type HistoryBuild = { gameVersion: string; keyChanges: number; publishedAt: string };
// [build, linux, windows] - a side is null when the key has no value there.
export type HistoryPoint = [string, string | number | null, string | number | null];
export type History = {
    gameVersion: string;
    builds: HistoryBuild[];
    files: Record<string, Record<string, { changes: string[]; points: HistoryPoint[] }>>;
};

export type PlatformVerification = {
    verified: number; contradicted: number; unverified: number; upstream: number; instructionOnly: number;
};
// One entry's verdict on one platform. `keys` is absent in diagnostics published
// before publish_site_data.py kept every verdict (only `problems` were stored).
export type KeyVerdict = { name: string; platform: string; status: string; at?: string; count?: number; verification?: string };
export type DiagnosticsFile = {
    path: string; plugin: string; entries: number; unhealthy: number;
    verification?: { linux?: PlatformVerification; windows?: PlatformVerification };
    problems?: KeyVerdict[];
    keys?: KeyVerdict[];
};
export type Diagnostics = {
    gameVersion: string;
    plugins: { files: DiagnosticsFile[] };
    validator?: { artifacts?: number; errors?: number; warnings?: number };
};

// The binaries a signature can name, by module (the "library" a gamedata entry
// names). Same table as verify_plugin_gamedata.py's BIN_LINUX / BIN_WIN.
export const BINARIES: Record<string, { linux: string; windows: string }> = {
    server: { linux: "libserver.so", windows: "server.dll" },
    engine: { linux: "libengine2.so", windows: "engine2.dll" },
    client: { linux: "libclient.so", windows: "client.dll" },
    networksystem: { linux: "libnetworksystem.so", windows: "networksystem.dll" },
    scenesystem: { linux: "libscenesystem.so", windows: "scenesystem.dll" },
    matchmaking: { linux: "libmatchmaking.so", windows: "matchmaking.dll" },
    vphysics2: { linux: "libvphysics2.so", windows: "vphysics2.dll" },
    tier0: { linux: "libtier0.so", windows: "tier0.dll" },
    schemasystem: { linux: "libschemasystem.so", windows: "schemasystem.dll" },
    filesystem_stdio: { linux: "libfilesystem_stdio.so", windows: "filesystem_stdio.dll" },
    soundsystem: { linux: "libsoundsystem.so", windows: "soundsystem.dll" },
    worldrenderer: { linux: "libworldrenderer.so", windows: "worldrenderer.dll" },
};

export type KeyChange = { key: string; platform: string; before: unknown; after: unknown };
export type FileChanges = { file: string; plugin: string; changes: KeyChange[] };

function readJson<T>(file: string): T | null {
    try {
        return JSON.parse(fs.readFileSync(file, "utf8")) as T;
    } catch {
        return null;
    }
}

export class Repo {
    readonly root: string;

    constructor(root: string) {
        this.root = root;
    }

    history(): History | null {
        return readJson<History>(path.join(this.root, "gamedata", "history.json"));
    }

    latestBuild(): string | null {
        return this.history()?.gameVersion ?? null;
    }

    builds(): string[] {
        return (this.history()?.builds ?? []).map((b) => b.gameVersion);
    }

    diagnostics(gamever: string): Diagnostics | null {
        if (!GAMEVER_RE.test(gamever)) return null;
        return readJson<Diagnostics>(path.join(this.root, "diagnostics", `${gamever}.json`));
    }

    // The shipped files of a build: diagnostics lists exactly the enabled
    // plugins' files, so a disabled generator's leftover directory never shows.
    shippedFiles(gamever: string): string[] {
        return (this.diagnostics(gamever)?.plugins.files ?? []).map((f) => f.path);
    }

    // Absolute path of a shipped file, or null when `file` is not one of them.
    filePath(gamever: string, file: string): string | null {
        if (!this.shippedFiles(gamever).includes(file)) return null;
        const full = path.join(this.root, "gamedata", gamever, file);
        return fs.existsSync(full) ? full : null;
    }

    // The binary the pipeline analysed for a build (bin/<build>/<module>/<file>), or
    // null when it is not on disk: bin/ is a cache, so older builds may be gone.
    binaryPath(gamever: string, module: string, platform: "linux" | "windows"): string | null {
        if (!GAMEVER_RE.test(gamever) || !Object.hasOwn(BINARIES, module)) return null;
        const names = BINARIES[module];
        const full = path.join(this.root, "bin", gamever, module, names[platform]);
        return fs.existsSync(full) ? full : null;
    }

    // What each shipped file changed against the previous build, per key and
    // platform. Read from history.json, which records a key only when its value
    // differs from the build before. NOT from the generator's *.metadata.json:
    // its "before" is the plugin's own template, so every key the template
    // spells differently shows as changed on every build (14191's matchzy file
    // is byte-identical to 14190's and its metadata lists 8 changes).
    changes(gamever: string): FileChanges[] {
        const history = this.history();
        const out: FileChanges[] = [];
        for (const file of this.shippedFiles(gamever)) {
            const changes: KeyChange[] = [];
            for (const [key, record] of Object.entries(history?.files[file] ?? {})) {
                if (!record.changes.includes(gamever)) continue;
                const index = record.points.findIndex((p) => p[0] === gamever);
                const after = record.points[index];
                const before = index > 0 ? record.points[index - 1] : undefined;
                if (!after) continue;
                const sides = (["linux", "windows"] as const).filter((_, i) => before?.[i + 1] !== after[i + 1]);
                for (const platform of sides.length ? sides : ["linux", "windows"] as const) {
                    const i = platform === "linux" ? 1 : 2;
                    changes.push({ key, platform, before: before?.[i] ?? null, after: after[i] });
                }
            }
            if (changes.length) out.push({ file, plugin: pluginOf(file), changes });
        }
        return out;
    }
}

export function pluginOf(file: string): string {
    return file.split("/")[0];
}
