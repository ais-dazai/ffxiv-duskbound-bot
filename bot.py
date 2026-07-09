"""
Discord bot that:
1. /register      -> links an FFXIV character to your Discord account
2. /verify        -> confirms the character really is yours (code in Lodestone bio)
3. /update-roles  -> checks FFLogs for cleared Ultimates and assigns matching roles

Required environment variables are explained in README.md and .env.example.
"""

import json
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

with open("roles_config.json", "r", encoding="utf-8") as f:
    ROLES_CONFIG = json.load(f)

with open("reaction_roles.json", "r", encoding="utf-8") as f:
    REACTION_ROLES_CONFIG = json.load(f)


def resolve_role_name(encounter_name):
    """Turns an FFLogs encounter name into the Discord role name to use,
    based on roles_config.json. Falls back to a generic 'Cleared - X' name
    for any Ultimate not listed in the config file."""
    for keyword, custom_name in ROLES_CONFIG.get("role_names", {}).items():
        if keyword.lower() in encounter_name.lower():
            return custom_name
    prefix = ROLES_CONFIG.get("default_prefix", "Cleared - ")
    return f"{prefix}{encounter_name}"

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
    try:
        char = lodestone.search_character(name, server)
    except Exception as e:
        await interaction.followup.send(
            f"Error contacting Lodestone: {e}\n"
            f"This can happen if Lodestone is temporarily blocking automated requests. Try again in a minute.",
            ephemeral=True,
        )
        return
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

    try:
        bio = lodestone.get_character_bio(pending["character"]["id"])
    except Exception as e:
        await interaction.followup.send(
            f"Error reading your Lodestone profile: {e}\n"
            f"This can happen if Lodestone is temporarily blocking automated requests. Try again in a minute.",
            ephemeral=True,
        )
        return
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
    errors = []

    for enc in encounters:
        try:
            cleared = fflogs.has_clear(char["name"], server_slug, server_region, enc["id"])
        except Exception as e:
            print(f"Error checking {enc['name']} (id {enc['id']}): {e}")
            errors.append(f"{enc['name']} (id {enc['id']}): {e}")
            continue

        if cleared:
            role_name = resolve_role_name(enc["name"])
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
            assigned.append(f"{enc['name']} (id {enc['id']})")

    lines = []
    if assigned:
        lines.append("Roles assigned for:\n" + "\n".join(f"• {a}" for a in assigned))
    else:
        lines.append("No cleared Ultimates found on FFLogs for this character.")
    if errors:
        lines.append("\n⚠️ Couldn't check these (error below), so they were skipped:\n" + "\n".join(f"• {e}" for e in errors))

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="debug-ultimates", description="[Admin] List every Ultimate zone/encounter FFLogs returns, for troubleshooting")
@app_commands.checks.has_permissions(manage_roles=True)
async def debug_ultimates(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        encounters = fflogs.get_ultimate_encounters()
    except Exception as e:
        await interaction.followup.send(f"Error contacting FFLogs: {e}", ephemeral=True)
        return

    if not encounters:
        await interaction.followup.send("FFLogs returned no Ultimate encounters at all.", ephemeral=True)
        return

    lines = [f"id={e['id']} — {e['name']}  (zone: {e['zone']})" for e in encounters]
    await interaction.followup.send("Encounters found:\n" + "\n".join(lines), ephemeral=True)


@debug_ultimates.error
async def debug_ultimates_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need the 'Manage Roles' permission to use this command.", ephemeral=True
        )
    else:
        raise error


async def get_or_create_role(guild, role_name):
    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        role = await guild.create_role(name=role_name, reason="Reaction role setup")
    return role


@bot.tree.command(name="setup-reaction-roles", description="[Admin] Post a reaction-roles message in this channel")
@app_commands.describe(group="Which group of roles to post (see reaction_roles.json)")
@app_commands.choices(group=[
    app_commands.Choice(name=key, value=key) for key in REACTION_ROLES_CONFIG.get("groups", {})
])
@app_commands.checks.has_permissions(manage_roles=True)
async def setup_reaction_roles(interaction: discord.Interaction, group: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)

    group_data = REACTION_ROLES_CONFIG["groups"].get(group.value)
    if not group_data:
        await interaction.followup.send("Unknown group.", ephemeral=True)
        return

    lines = [f"{r['emoji']}  —  {r['role_name']}" for r in group_data["roles"]]
    description = group_data.get("description", "")
    text = f"**{group_data['title']}**\n{description}\n\n" + "\n".join(lines)

    try:
        message = await interaction.channel.send(text)
        for r in group_data["roles"]:
            await message.add_reaction(r["emoji"])
    except discord.Forbidden:
        await interaction.followup.send(
            "I don't have permission to post or react in this channel. Check my permissions "
            "('Send Messages', 'Add Reactions') and try again.",
            ephemeral=True,
        )
        return

    storage.set_reaction_message(message.id, group.value)
    await interaction.followup.send("Reaction-roles message posted! ✅", ephemeral=True)


@setup_reaction_roles.error
async def setup_reaction_roles_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need the 'Manage Roles' permission to use this command.", ephemeral=True
        )
    else:
        raise error


@bot.event
async def on_raw_reaction_add(payload):
    if payload.member is None or payload.member.bot:
        return

    group_key = storage.get_reaction_group(payload.message_id)
    if not group_key:
        return

    group_data = REACTION_ROLES_CONFIG["groups"].get(group_key)
    if not group_data:
        return

    emoji = str(payload.emoji)
    for r in group_data["roles"]:
        if r["emoji"] == emoji:
            guild = bot.get_guild(payload.guild_id)
            if guild is None:
                return
            role = await get_or_create_role(guild, r["role_name"])
            try:
                await payload.member.add_roles(role, reason="Reaction role")
            except discord.Forbidden:
                pass
            return


@bot.event
async def on_raw_reaction_remove(payload):
    group_key = storage.get_reaction_group(payload.message_id)
    if not group_key:
        return

    group_data = REACTION_ROLES_CONFIG["groups"].get(group_key)
    if not group_data:
        return

    emoji = str(payload.emoji)
    for r in group_data["roles"]:
        if r["emoji"] == emoji:
            guild = bot.get_guild(payload.guild_id)
            if guild is None:
                return
            member = guild.get_member(payload.user_id)
            if member is None:
                return
            role = discord.utils.get(guild.roles, name=r["role_name"])
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Reaction role removed")
                except discord.Forbidden:
                    pass
            return


bot.run(DISCORD_TOKEN)
