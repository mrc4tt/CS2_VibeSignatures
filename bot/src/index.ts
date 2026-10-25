import { Client, Events, GatewayIntentBits, MessageFlags } from "discord.js";
import { AdminPanel } from "./admin.ts";
import { Announcer } from "./announce.ts";
import { Commands } from "./commands.ts";
import { updatePresence } from "./presence.ts";
import { config } from "./config.ts";
import { Repo } from "./repo.ts";
import { startServer } from "./server.ts";

// Slash commands need no privileged intent; the bot never reads messages.
// No mention in any text the bot relays (autopilot detail, file contents) can ping anyone.
const client = new Client({ intents: [GatewayIntentBits.Guilds], allowedMentions: { parse: [] } });
const repo = new Repo(config.repoRoot);
const commands = new Commands(repo);
const announcer = new Announcer(client, repo);
const admin = new AdminPanel(repo, announcer);

client.once(Events.ClientReady, (ready) => {
    console.log(`logged in as ${ready.user.tag}, reading ${config.repoRoot}`);
    startServer(config.httpPort, config.eventSecret, (event) => announcer.handle(event));
    // The status follows each event at once, and the repository every few minutes
    // (a build published by hand, or history.json regenerated after a run).
    announcer.onApplied = () => updatePresence(client, repo);
    updatePresence(client, repo);
    setInterval(() => updatePresence(client, repo), 5 * 60 * 1000).unref();
    console.log(`event endpoint on http://127.0.0.1:${config.httpPort}/event`);
});

client.on(Events.InteractionCreate, async (interaction) => {
    try {
        if (interaction.isAutocomplete()) await commands.autocomplete(interaction);
        else if (interaction.isChatInputCommand() && interaction.commandName === "settings") await admin.command(interaction);
        else if (interaction.isChatInputCommand()) await commands.run(interaction);
        else if ((interaction.isStringSelectMenu() || interaction.isButton()) && interaction.customId.startsWith("settings:")) {
            await admin.component(interaction);
        }
    } catch (error) {
        console.error("interaction failed:", error);
        if (interaction.isRepliable() && !interaction.replied) {
            await interaction.reply({ content: "Something went wrong.", flags: MessageFlags.Ephemeral }).catch(() => undefined);
        }
    }
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => {
        client.destroy().finally(() => process.exit(0));
    });
}

await client.login(config.token);
