import crypto from "node:crypto";
import path from "node:path";
import {
    AttachmentBuilder, EmbedBuilder, MessageFlags, PermissionFlagsBits, SlashCommandBuilder,
    type AutocompleteInteraction, type ChatInputCommandInteraction,
} from "discord.js";
import { settingsDefinition } from "./admin.ts";
import { latestEvent } from "./announce.ts";
import { config } from "./config.ts";
import { BINARIES, GAMEVER_RE, type Repo } from "./repo.ts";
import { changesEmbed, checkEmbed, fileChangesEmbed, fileEmbed, fileLabel, keyEmbed, statusEmbed, verifyEmbed } from "./render.ts";
import { loadImage, scan, type Image } from "./scan.ts";

// A Discord option is capped at 6000 characters; a real signature is far shorter.
const MAX_PATTERN = 600;

export const definitions = [
    new SlashCommandBuilder().setName("help").setDescription("What this bot can do"),
    new SlashCommandBuilder().setName("status").setDescription("Newest build, the running autopilot and the health of every shipped file"),
    new SlashCommandBuilder()
        .setName("changes")
        .setDescription("Which plugins need a new gamedata file for a build, or one file's changed keys")
        .addStringOption((o) => o.setName("build").setDescription("Game build (default: newest)").setAutocomplete(true))
        .addStringOption((o) => o.setName("file").setDescription("Show the keys this file changed").setAutocomplete(true)),
    new SlashCommandBuilder()
        .setName("gamedata")
        .setDescription("Download a plugin's generated gamedata file")
        .addStringOption((o) => o.setName("file").setDescription("Plugin file").setRequired(true).setAutocomplete(true))
        .addStringOption((o) => o.setName("build").setDescription("Game build (default: newest)").setAutocomplete(true)),
    new SlashCommandBuilder()
        .setName("key")
        .setDescription("Current signature/offset of one key and the builds it changed in")
        .addStringOption((o) => o.setName("key").setDescription("Key name").setRequired(true).setAutocomplete(true)),
    new SlashCommandBuilder()
        .setName("verify")
        .setDescription("Does every key of a plugin's gamedata file resolve on a build, and where")
        .addStringOption((o) => o.setName("file").setDescription("Plugin file").setRequired(true).setAutocomplete(true))
        .addStringOption((o) => o.setName("build").setDescription("Game build (default: newest)").setAutocomplete(true)),
    new SlashCommandBuilder()
        .setName("check")
        .setDescription("Scan a signature against a build's binary: 1 hit is good, 0 is broken, 2+ is ambiguous")
        .addStringOption((o) => o.setName("signature").setDescription("Hex bytes with ? wildcards, or \\x escapes").setRequired(true).setMaxLength(MAX_PATTERN))
        .addStringOption((o) => o.setName("platform").setDescription("Binary platform").setRequired(true)
            .addChoices({ name: "linux", value: "linux" }, { name: "windows", value: "windows" }))
        .addStringOption((o) => o.setName("module").setDescription("Binary (default: server)")
            .addChoices(...Object.keys(BINARIES).map((m) => ({ name: m, value: m }))))
        .addStringOption((o) => o.setName("build").setDescription("Game build (default: newest)").setAutocomplete(true)),
]
    // Answers are visible to the asker only unless they choose to share, so a
    // channel does not fill up with everyone's lookups.
    .map((c) => c.addBooleanOption((o) => o.setName("share").setDescription("Post the answer for everyone (not in the updates channel)")))
    .map((c) => c.toJSON())
    .concat(settingsDefinition.toJSON());

// Built from the definitions, so a new command or option shows up here by itself.
export function helpEmbed(admin: boolean): EmbedBuilder {
    const usage = (c: (typeof definitions)[number]) => {
        const options = (c.options ?? []) as { name: string; required?: boolean }[];
        const args = options.filter((o) => o.name !== "share").map((o) => (o.required ? o.name : `[${o.name}]`));
        return `\`/${[c.name, ...args].join(" ")}\``;
    };
    const lines = definitions
        .filter((c) => c.name !== "settings" || admin)
        .map((c) => `${usage(c)}\n${c.description}`);
    return new EmbedBuilder()
        .setTitle("CS2 gamedata bot")
        .setColor(0x5865f2)
        .setURL(config.siteUrl)
        .setDescription(
            "Posts every CS2 build to the updates channel when its generated gamedata is ready, " +
            "with the plugin files an admin chose attached.\n\n" + lines.join("\n\n") +
            "\n\nAnswers are visible to you only; add `share:True` to post one for everyone.",
        )
        .setFooter({ text: `Browse every build and check your own file: ${config.siteUrl}` });
}

// Autocomplete values are capped at 100 characters and a file path plus a key
// can exceed that, so choices carry a short digest that is resolved back.
function digest(text: string): string {
    return crypto.createHash("sha1").update(text).digest("hex").slice(0, 16);
}

const COOLDOWN_MS = 3000;

// The last binary scanned (~40 MB). /check is usually asked several times in a
// row against the same build, so one cached image saves re-reading the file.
let cachedImage: { file: string; image: Image | null } | null = null;
function image(file: string): Image | null {
    if (cachedImage?.file !== file) cachedImage = { file, image: loadImage(file) };
    return cachedImage.image;
}
const lastUse = new Map<string, number>();

export class Commands {
    private repo: Repo;

    constructor(repo: Repo) {
        this.repo = repo;
    }

    private build(interaction: ChatInputCommandInteraction): string | null {
        const asked = interaction.options.getString("build");
        const builds = this.repo.builds();
        if (!asked) return this.repo.latestBuild();
        return GAMEVER_RE.test(asked) && builds.includes(asked) ? asked : null;
    }

    private keyRecords(): { file: string; key: string }[] {
        const files = this.repo.history()?.files ?? {};
        return Object.entries(files).flatMap(([file, keys]) => Object.keys(keys).map((key) => ({ file, key })));
    }

    async run(interaction: ChatInputCommandInteraction): Promise<void> {
        const now = Date.now();
        if (now - (lastUse.get(interaction.user.id) ?? 0) < COOLDOWN_MS) {
            await interaction.reply({ content: "One moment - try again in a few seconds.", flags: MessageFlags.Ephemeral });
            return;
        }
        lastUse.set(interaction.user.id, now);
        // The updates channel holds build messages only: answers there are never public.
        const share = interaction.options.getBoolean("share") === true && interaction.channelId !== config.updatesChannelId;
        const flags = share ? undefined : MessageFlags.Ephemeral;

        switch (interaction.commandName) {
            case "help":
                await interaction.reply({ embeds: [helpEmbed(interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild) === true)], flags });
                return;
            case "status":
                await interaction.reply({ embeds: [statusEmbed(this.repo, latestEvent())], flags });
                return;
            case "changes": {
                const build = this.build(interaction);
                if (!build) return this.unknownBuild(interaction);
                const id = interaction.options.getString("file");
                const file = id ? this.repo.shippedFiles(build).find((f) => digest(f) === id || f === id) : undefined;
                if (id && !file) {
                    await interaction.reply({ content: `No such file in build ${build}.`, flags: MessageFlags.Ephemeral });
                    return;
                }
                const embed = file ? fileChangesEmbed(this.repo, build, file) : changesEmbed(this.repo, build);
                await interaction.reply({ embeds: [embed], flags });
                return;
            }
            case "gamedata": {
                const build = this.build(interaction);
                if (!build) return this.unknownBuild(interaction);
                const id = interaction.options.getString("file", true);
                const file = this.repo.shippedFiles(build).find((f) => digest(f) === id || f === id);
                const full = file ? this.repo.filePath(build, file) : null;
                if (!file || !full) {
                    await interaction.reply({ content: `No such file in build ${build}.`, flags: MessageFlags.Ephemeral });
                    return;
                }
                await interaction.reply({
                    flags,
                    embeds: [fileEmbed(this.repo, build, file)],
                    files: [new AttachmentBuilder(full, { name: path.basename(file) })],
                });
                return;
            }
            case "verify": {
                const build = this.build(interaction);
                if (!build) return this.unknownBuild(interaction);
                const id = interaction.options.getString("file", true);
                const file = this.repo.shippedFiles(build).find((f) => digest(f) === id || f === id);
                if (!file) {
                    await interaction.reply({ content: `No such file in build ${build}.`, flags: MessageFlags.Ephemeral });
                    return;
                }
                await interaction.reply({ embeds: [verifyEmbed(this.repo, build, file)], flags });
                return;
            }
            case "check":
                return this.check(interaction, flags);
            case "key": {
                const id = interaction.options.getString("key", true);
                const record = this.keyRecords().find((r) => digest(`${r.file}|${r.key}`) === id)
                    ?? this.keyRecords().find((r) => r.key === id);
                const embed = record && keyEmbed(this.repo, record.file, record.key);
                if (!embed) {
                    await interaction.reply({ content: "Unknown key - pick one from the list.", flags: MessageFlags.Ephemeral });
                    return;
                }
                await interaction.reply({ embeds: [embed], flags });
                return;
            }
        }
    }

    private async check(interaction: ChatInputCommandInteraction, flags: MessageFlags.Ephemeral | undefined): Promise<void> {
        const build = this.build(interaction);
        if (!build) return this.unknownBuild(interaction);
        const platform = interaction.options.getString("platform", true) as "linux" | "windows";
        const module = interaction.options.getString("module") ?? "server";
        // Shown back in a code block: no backticks, so it cannot close the block.
        const pattern = interaction.options.getString("signature", true).replaceAll("`", "").trim().slice(0, MAX_PATTERN);
        const file = this.repo.binaryPath(build, module, platform);
        if (!file) {
            await interaction.reply({ content: `The ${module} ${platform} binary of build ${build} is not on the server (only recent builds are kept).`, flags: MessageFlags.Ephemeral });
            return;
        }
        // Reading and scanning a cold 40 MB binary can pass Discord's 3 s reply window.
        await interaction.deferReply({ flags });
        const loaded = image(file);
        if (!loaded) {
            await interaction.editReply({ content: `Could not read the ${module} ${platform} binary of build ${build}.` });
            return;
        }
        await interaction.editReply({ embeds: [checkEmbed(build, module, platform, pattern, scan(loaded, pattern))] });
    }

    private async unknownBuild(interaction: ChatInputCommandInteraction): Promise<void> {
        await interaction.reply({ content: "Unknown build - pick one from the list.", flags: MessageFlags.Ephemeral });
    }

    async autocomplete(interaction: AutocompleteInteraction): Promise<void> {
        const focused = interaction.options.getFocused(true);
        const query = focused.value.toLowerCase();
        let choices: { name: string; value: string }[] = [];

        if (focused.name === "build") {
            choices = this.repo.builds().reverse().filter((b) => b.includes(query)).map((b) => ({ name: b, value: b }));
        } else if (focused.name === "file") {
            const build = interaction.options.getString("build") || this.repo.latestBuild() || "";
            choices = this.repo.shippedFiles(build)
                .filter((f) => f.toLowerCase().includes(query))
                .map((f) => ({ name: fileLabel(f), value: digest(f) }));
        } else if (focused.name === "key") {
            choices = this.keyRecords()
                .filter((r) => r.key.toLowerCase().includes(query))
                .map((r) => ({ name: `${r.key} - ${fileLabel(r.file)}`.slice(0, 100), value: digest(`${r.file}|${r.key}`) }));
        }
        await interaction.respond(choices.slice(0, 25));
    }
}
