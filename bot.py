"""
Bot Discord che:
1. /registra   -> collega un personaggio FFXIV al tuo account Discord
2. /verifica   -> conferma che il personaggio è davvero tuo (codice nella bio Lodestone)
3. /aggiorna-ruoli -> controlla su FFLogs quali Ultimate hai clearato e ti assegna i ruoli

Le variabili d'ambiente necessarie sono spiegate nel README.md e in .env.example.
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
XIVAPI_KEY = os.environ.get("XIVAPI_KEY")  # opzionale, dipende dal servizio XIVAPI

fflogs = FFLogsClient(FFLOGS_CLIENT_ID, FFLOGS_CLIENT_SECRET)
lodestone = LodestoneClient(XIVAPI_KEY)
storage = Storage()

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


def gen_code():
    return "FFXIV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot connesso come {bot.user}")


@bot.tree.command(name="registra", description="Collega il tuo personaggio FFXIV al tuo account Discord")
@app_commands.describe(nome="Nome e cognome del personaggio", server="Nome del server (es. Odin)")
async def registra(interaction: discord.Interaction, nome: str, server: str):
    await interaction.response.defer(ephemeral=True)
    char = lodestone.search_character(nome, server)
    if not char:
        await interaction.followup.send(
            "Non ho trovato nessun personaggio con questo nome su questo server. "
            "Controlla l'ortografia (nome e cognome) e riprova.",
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
        f"Trovato **{char['Name']}** su **{char['Server']}**.\n\n"
        f"Per verificare che sia tuo:\n"
        f"1. Vai sul tuo profilo Lodestone\n"
        f"2. Modifica la sezione **Autopresentazione**\n"
        f"3. Incolla temporaneamente questo codice:\n\n`{code}`\n\n"
        f"4. Salva, aspetta un paio di minuti, poi torna qui e usa `/verifica`.\n\n"
        f"Dopo la verifica puoi rimuovere il codice dalla bio.",
        ephemeral=True,
    )


@bot.tree.command(name="verifica", description="Conferma la verifica dopo aver inserito il codice sul Lodestone")
async def verifica(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    pending = storage.get_pending(interaction.user.id)
    if not pending:
        await interaction.followup.send("Non hai nessuna registrazione in corso. Usa prima `/registra`.", ephemeral=True)
        return

    bio = lodestone.get_character_bio(pending["character"]["id"])
    if pending["code"] not in bio:
        await interaction.followup.send(
            "Non ho trovato il codice nella tua bio Lodestone. Assicurati di averlo salvato "
            "e di aver aspettato qualche minuto (il Lodestone a volte è lento ad aggiornarsi), poi riprova.",
            ephemeral=True,
        )
        return

    storage.set_verified(interaction.user.id, pending["character"])
    storage.clear_pending(interaction.user.id)
    await interaction.followup.send(
        f"Personaggio **{pending['character']['name']}** verificato! "
        f"Ora usa `/aggiorna-ruoli` per ricevere i ruoli in base ai tuoi clear ultimate.",
        ephemeral=True,
    )


@bot.tree.command(name="aggiorna-ruoli", description="Controlla i tuoi clear ultimate su FFLogs e assegna i ruoli")
async def aggiorna_ruoli(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if interaction.guild is None:
        await interaction.followup.send("Questo comando va usato dentro al server, non in DM.", ephemeral=True)
        return

    char = storage.get_verified(interaction.user.id)
    if not char:
        await interaction.followup.send(
            "Devi prima registrare e verificare un personaggio con `/registra` e `/verifica`.",
            ephemeral=True,
        )
        return

    server_slug, server_region = fflogs.get_server_info(char["server"])
    if not server_slug:
        await interaction.followup.send(
            f"Non riesco a trovare il server **{char['server']}** su FFLogs. Contatta un admin del server Discord.",
            ephemeral=True,
        )
        return

    try:
        encounters = fflogs.get_ultimate_encounters()
    except Exception as e:
        await interaction.followup.send(f"Errore contattando FFLogs: {e}", ephemeral=True)
        return

    guild = interaction.guild
    member = guild.get_member(interaction.user.id)
    assigned = []

    for enc in encounters:
        try:
            cleared = fflogs.has_clear(char["name"], server_slug, server_region, enc["id"])
        except Exception as e:
            print(f"Errore controllando {enc['name']}: {e}")
            continue

        if cleared:
            role_name = f"Cleared - {enc['name']}"
            role = discord.utils.get(guild.roles, name=role_name)
            if role is None:
                try:
                    role = await guild.create_role(name=role_name, reason="Ruolo automatico ultimate clear")
                except discord.Forbidden:
                    await interaction.followup.send(
                        "Non ho i permessi per creare ruoli. Assicurati che il ruolo del bot abbia "
                        "il permesso 'Manage Roles' e sia posizionato in alto nella gerarchia.",
                        ephemeral=True,
                    )
                    return
            if role not in member.roles:
                await member.add_roles(role, reason="Clear ultimate verificato su FFLogs")
            assigned.append(enc["name"])

    if assigned:
        await interaction.followup.send(f"Ruoli assegnati per: {', '.join(assigned)} 🎉", ephemeral=True)
    else:
        await interaction.followup.send("Nessun clear ultimate trovato su FFLogs per questo personaggio.", ephemeral=True)


bot.run(DISCORD_TOKEN)
