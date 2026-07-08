"""
Discord bot that:
1. /register      -> links an FFXIV character to your Discord account
2. /verify        -> confirms the character really is yours (code in Lodestone bio)
3. /update-roles  -> checks FFLogs for cleared Ultimates and assigns matching roles

Required environment variables are explained in README.md and .env.example.
"""

import os
import random
import string

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from ffxiv_api import FFLogsClient, LodestoneClient
from storage import Storage

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
FFLOGS_CLIENT_ID = os.environ["FFLOGS_CLIENT_ID"]
FFLOGS_CLIENT_SECRET = os.environ["FFLOGS_CLIENT_SECRET"]

fflogs = FFLogsClient(FFLOGS_CLIENT_ID, FFLOGS_CLIENT_SECRET)
lodestone = LodestoneClient()
storage = Storage()

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


def gen_code():
    return "FFXIV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot logged in as {bot.user}")


@bot.tree.command(name="register", description="Link your FFXIV character to your Discord account")
@app_commands.describe(name="Character first and last name", server="Server/world name (e.g. Odin)")
async def register(interaction: discord.Interaction, name: str, server: str):
    await interaction.response.defer(ephemeral=True)
    char = lodestone.search_character(name, server)
    if not char:
        await interaction.followup.send(
            "I couldn't find any character with that name on that server. "
            "Check the spelling (first and last name) and try again.",
            ephemeral=True,
        )
        return

    code = gen_code()
    storage.set_pending(
        interaction.user.id,
        {"id": char["ID"], "name": char["Name"], "server": char["Server"]},
        code,
    )
    await interaction.followup.send(
        f"Found **{char['Name']}** on **{char['Server']}**.\n\n"
        f"To verify this character is yours:\n"
        f"1. Go to your Lodestone profile\n"
        f"2. Edit the **Self-Introduction** section\n"
        f"3. Temporarily paste this code:\n\n`{code}`\n\n"
        f"4. Save, wait a couple of minutes, then come back here and use `/verify`.\n\n"
        f"You can remove the code from your bio after verifying.",
        ephemeral=True,
    )


@bot.tree.command(name="verify", description="Confirm verification after adding the code to your Lodestone bio")
async def verify(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    pending = storage.get_pending(interaction.user.id)
    if not pending:
        await interaction.followup.send("You don't have a pending registration. Use `/register` first.", ephemeral=True)
        return

    bio = lodestone.get_character_bio(pending["character"]["id"])
    if pending["code"] not in bio:
        await interaction.followup.send(
            "I couldn't find the code in your Lodestone bio. Make sure you saved it "
            "and waited a few minutes (Lodestone can be slow to update), then try again.",
            ephemeral=True,
        )
        return

    storage.set_verified(interaction.user.id, pending["character"])
    storage.clear_pending(interaction.user.id)
    await interaction.followup.send(
        f"Character **{pending['character']['name']}** verified! "
        f"Now use `/update-roles` to get roles based on your cleared Ultimates.",
        ephemeral=True,
    )


@bot.tree.command(name="update-roles", description="Check your cleared Ultimates on FFLogs and assign matching roles")
async def update_roles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if interaction.guild is None:
        await interaction.followup.send("This command must be used inside a server, not in DMs.", ephemeral=True)
        return

    char = storage.get_verified(interaction.user.id)
    if not char:
        await interaction.followup.send(
            "You need to register and verify a character first with `/register` and `/verify`.",
            ephemeral=True,
        )
        return

    server_slug, server_region = fflogs.get_server_info(char["server"])
    if not server_slug:
        await interaction.followup.send(
            f"I can't find the server **{char['server']}** on FFLogs. Contact a Discord server admin.",
            ephemeral=True,
        )
        return

    try:
        encounters = fflogs.get_ultimate_encounters()
    except Exception as e:
        await interaction.followup.send(f"Error contacting FFLogs: {e}", ephemeral=True)
        return

    guild = interaction.guild
    member = guild.get_member(interaction.user.id)
    assigned = []

    for enc in encounters:
        try:
            cleared = fflogs.has_clear(char["name"], server_slug, server_region, enc["id"])
        except Exception as e:
            print(f"Error checking {enc['name']}: {e}")
            continue

        if cleared:
            role_name = f"Cleared - {enc['name']}"
            role = discord.utils.get(guild.roles, name=role_name)
            if role is None:
                try:
                    role = await guild.create_role(name=role_name, reason="Automatic Ultimate clear role")
                except discord.Forbidden:
                    await interaction.followup.send(
                        "I don't have permission to create roles. Make sure the bot's role has "
                        "'Manage Roles' permission and is positioned high enough in the role hierarchy.",
                        ephemeral=True,
                    )
                    return
            if role not in member.roles:
                await member.add_roles(role, reason="Ultimate clear verified on FFLogs")
            assigned.append(enc["name"])

    if assigned:
        await interaction.followup.send(f"Roles assigned for: {', '.join(assigned)} 🎉", ephemeral=True)
    else:
        await interaction.followup.send("No cleared Ultimates found on FFLogs for this character.", ephemeral=True)


bot.run(DISCORD_TOKEN)
