"""
Discord bot that:
1. /register      -> links an FFXIV character to your Discord account (no verification code, trust-based)
2. /update-roles  -> checks FFLogs for cleared Ultimates and assigns matching roles

Required environment variables are explained in README.md and .env.example.
"""

import json
import os

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


def build_ultimate_groups():
    """Groups every FFLogs encounter into 'Ultimate groups' to check.

    Primary source: the keywords already defined in roles_config.json
    (reliable, and lets an admin control exactly what counts as an Ultimate).
    Fallback: any additional encounter sitting in a zone whose name contains
    'ultimate' but that isn't already covered by a keyword above - this
    catches a brand new Ultimate automatically even before someone adds it
    to roles_config.json, using a generic role name.

    Each group can contain more than one FFLogs encounter id, because the
    same fight sometimes exists under several zones (e.g. a current zone
    and a retrospective 'Ultimates (Legacy)' zone). A character only needs
    a clear under ANY of those ids to count.
    """
    all_encounters = fflogs.get_all_encounters()
    groups = []
    covered_ids = set()

    for keyword, role_name in ROLES_CONFIG.get("role_names", {}).items():
        ids = [e["id"] for e in all_encounters if keyword.lower() in e["name"].lower()]
        if ids:
            groups.append({"label": keyword, "role_name": role_name, "ids": ids})
            covered_ids.update(ids)

    prefix = ROLES_CONFIG.get("default_prefix", "Cleared - ")
    seen_fallback_names = set()
    for e in all_encounters:
        if e["id"] in covered_ids:
            continue
        if "ultimate" in e["zone"].lower() and e["name"] not in seen_fallback_names:
            groups.append({"label": e["name"], "role_name": f"{prefix}{e['name']}", "ids": [e["id"]]})
            seen_fallback_names.add(e["name"])

    return groups

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


class PostMessageModal(discord.ui.Modal, title="Post a message"):
    content = discord.ui.TextInput(
        label="Message content",
        style=discord.TextStyle.paragraph,
        placeholder="Type or paste the message here (supports multiple lines)...",
        max_length=4000,
        required=True,
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.send(str(self.content))
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to send messages in that channel.", ephemeral=True
            )
            return
        await interaction.response.send_message("Message posted ✅", ephemeral=True)


@bot.tree.command(name="post-message", description="[Admin] Post a message as the bot in this channel")
@app_commands.checks.has_permissions(manage_messages=True)
async def post_message(interaction: discord.Interaction):
    await interaction.response.send_modal(PostMessageModal(interaction.channel))


@post_message.error
async def post_message_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need the 'Manage Messages' permission to use this command.", ephemeral=True
        )
    else:
        raise error


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

    storage.set_verified(
        interaction.user.id,
        {"id": char["ID"], "name": char["Name"], "server": char["Server"]},
    )
    await interaction.followup.send(
        f"Linked **{char['Name']}** on **{char['Server']}** to your account.\n"
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
            "You need to register a character first with `/register`.",
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
        groups = build_ultimate_groups()
    except Exception as e:
        await interaction.followup.send(f"Error contacting FFLogs: {e}", ephemeral=True)
        return

    guild = interaction.guild
    member = guild.get_member(interaction.user.id)
    assigned = []
    errors = []

    for group in groups:
        try:
            cleared = fflogs.has_clear_any(char["name"], server_slug, server_region, group["ids"])
        except Exception as e:
            print(f"Error checking {group['label']} (ids {group['ids']}): {e}")
            errors.append(f"{group['label']}: {e}")
            continue

        if cleared:
            role_name = group["role_name"]
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
            assigned.append(role_name)

    lines = []
    if assigned:
        lines.append("Roles assigned for:\n" + "\n".join(f"• {a}" for a in assigned))
    else:
        lines.append("No cleared Ultimates found on FFLogs for this character.")
    if errors:
        lines.append("\n⚠️ Couldn't check these (error below), so they were skipped:\n" + "\n".join(f"• {e}" for e in errors))

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="debug-ultimates", description="[Admin] List every Ultimate group FFLogs returns, for troubleshooting")
@app_commands.checks.has_permissions(manage_roles=True)
async def debug_ultimates(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        groups = build_ultimate_groups()
    except Exception as e:
        await interaction.followup.send(f"Error contacting FFLogs: {e}", ephemeral=True)
        return

    if not groups:
        await interaction.followup.send("FFLogs returned no Ultimate groups at all.", ephemeral=True)
        return

    lines = [f"**{g['label']}** → role \"{g['role_name']}\" — ids: {g['ids']}" for g in groups]
    await interaction.followup.send("Groups found:\n" + "\n".join(lines), ephemeral=True)


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
