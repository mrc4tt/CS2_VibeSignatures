// Registers the slash commands on the one guild (instant, unlike global ones).
// Run after changing a definition: npm run register
import { REST, Routes } from "discord.js";
import { definitions } from "./commands.ts";
import { config } from "./config.ts";

const rest = new REST().setToken(config.token);
const result = await rest.put(Routes.applicationGuildCommands(config.applicationId, config.guildId), { body: definitions });
console.log(`registered ${(result as unknown[]).length} commands on guild ${config.guildId}`);
