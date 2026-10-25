// /settings: an ephemeral panel where a server admin picks which gamedata
// files the build message carries. Saved to settings.json and read on every
// build, so nothing needs a restart.
import crypto from "node:crypto";
import {
    ActionRowBuilder, ButtonBuilder, ButtonStyle, InteractionContextType, MessageFlags, PermissionFlagsBits, SlashCommandBuilder,
    StringSelectMenuBuilder,
    type ButtonInteraction, type ChatInputCommandInteraction, type StringSelectMenuInteraction,
} from "discord.js";
import { type Announcer, attachmentName } from "./announce.ts";
import { type Repo } from "./repo.ts";
import { fileLabel } from "./render.ts";
import { type AttachMode, loadSettings, MAX_ATTACHMENTS, saveSettings } from "./settings.ts";

export const settingsDefinition = new SlashCommandBuilder()
    .setName("settings")
    .setDescription("Admin: choose which gamedata files the build message carries")
    // Hidden from everyone without Manage Server; checked again on every click.
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .setContexts(InteractionContextType.Guild);

const id = (file: string) => crypto.createHash("sha1").update(file).digest("hex").slice(0, 16);
const clip = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);

type Panelable = ChatInputCommandInteraction | StringSelectMenuInteraction | ButtonInteraction;

export class AdminPanel {
    private repo: Repo;
    private announcer: Announcer;

    constructor(repo: Repo, announcer: Announcer) {
        this.repo = repo;
        this.announcer = announcer;
    }

    private allowed(interaction: Panelable): boolean {
        return interaction.inGuild() && interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild) === true;
    }

    private panel() {
        const latest = this.repo.latestBuild() ?? "";
        const shipped = this.repo.shippedFiles(latest);
        const settings = loadSettings();
        const chosen = settings.attachFiles.filter((f) => shipped.includes(f));

        const files = new StringSelectMenuBuilder()
            .setCustomId("settings:files")
            .setPlaceholder("No files attached")
            .setMinValues(0)
            .setMaxValues(Math.min(MAX_ATTACHMENTS, shipped.length))
            .addOptions(shipped.slice(0, 25).map((f) => ({
                label: clip(fileLabel(f), 100),
                description: clip(attachmentName(f), 100),
                value: id(f),
                default: chosen.includes(f),
            })));
        const mode = new StringSelectMenuBuilder()
            .setCustomId("settings:mode")
            .addOptions(
                { label: "Only files the build changed", value: "changed", default: settings.attachMode === "changed",
                  description: "An unchanged plugin gets no attachment" },
                { label: "Every selected file, every build", value: "always", default: settings.attachMode === "always" },
            );
        const apply = new ButtonBuilder()
            .setCustomId("settings:apply")
            .setStyle(ButtonStyle.Primary)
            .setLabel(`Apply to CS2 ${latest} now`)
            .setDisabled(!latest);

        const list = chosen.length ? chosen.map((f) => `• ${fileLabel(f)}`).join("\n") : "none";
        return {
            content: `**Files on the build message** (max ${MAX_ATTACHMENTS})\n${list}\n` +
                `Mode: ${settings.attachMode === "changed" ? "only files the build changed" : "every selected file"}\n` +
                "-# Saved at once; the next build uses it. \"Apply now\" re-attaches to the newest build's message.",
            components: [
                new ActionRowBuilder<StringSelectMenuBuilder>().addComponents(files),
                new ActionRowBuilder<StringSelectMenuBuilder>().addComponents(mode),
                new ActionRowBuilder<ButtonBuilder>().addComponents(apply),
            ],
        };
    }

    async command(interaction: ChatInputCommandInteraction): Promise<void> {
        if (!this.allowed(interaction)) {
            await interaction.reply({ content: "Only members with Manage Server can change this.", flags: MessageFlags.Ephemeral });
            return;
        }
        await interaction.reply({ ...this.panel(), flags: MessageFlags.Ephemeral });
    }

    async component(interaction: StringSelectMenuInteraction | ButtonInteraction): Promise<void> {
        if (!this.allowed(interaction)) {
            await interaction.reply({ content: "Only members with Manage Server can change this.", flags: MessageFlags.Ephemeral });
            return;
        }
        const settings = loadSettings();
        if (interaction.isStringSelectMenu() && interaction.customId === "settings:files") {
            // Resolve the digests against the shipped list: nothing a client sends
            // becomes a path unless it names one of those files.
            const shipped = this.repo.shippedFiles(this.repo.latestBuild() ?? "");
            settings.attachFiles = shipped.filter((f) => interaction.values.includes(id(f))).slice(0, MAX_ATTACHMENTS);
            saveSettings(settings);
            await interaction.update(this.panel());
        } else if (interaction.isStringSelectMenu() && interaction.customId === "settings:mode") {
            settings.attachMode = (interaction.values[0] === "always" ? "always" : "changed") satisfies AttachMode;
            saveSettings(settings);
            await interaction.update(this.panel());
        } else if (interaction.isButton() && interaction.customId === "settings:apply") {
            await interaction.deferUpdate();
            const latest = this.repo.latestBuild() ?? "";
            const count = await this.announcer.refreshFiles(latest).catch(() => null);
            await interaction.followUp({
                content: count === null
                    ? `CS2 ${latest} has no build message from this bot to attach to.`
                    : `CS2 ${latest}: ${count} file(s) now attached.`,
                flags: MessageFlags.Ephemeral,
            });
        }
    }
}
