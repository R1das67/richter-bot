import discord
from discord import app_commands, TextChannel
from discord.ext import tasks
import aiohttp
import json
import time
import os

# ================== CONFIG ==================
TOKEN = os.getenv("DISCORD_TOKEN")
CHECK_INTERVAL = 30
DATA_FILE = "bounties.json"

# ================== DISCORD ==================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ================== DATA ==================
def reset_data_on_startup():
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def admin_only(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

def format_duration(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec//60}m"
    if sec < 86400:
        return f"{sec//3600}h"
    return f"{sec//86400}d"

# ================== ROBLOX API ==================
async def get_roblox_user(uid: int):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://users.roblox.com/v1/users/{uid}") as r:
            if r.status != 200:
                return None
            return await r.json()

async def get_presence(uid: int):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://presence.roblox.com/v1/presence/users",
            json={"userIds": [uid]}
        ) as r:
            if r.status != 200:
                return None
            data = await r.json()
            return data["userPresences"][0]

# ================== GAME NAME – MODERN API ==================
async def get_game_name_modern(place_id: int) -> str:
    """
    Liefert den Spielnamen mit allen modernen Roblox-APIs.
    Versucht zuerst Universe -> Games, dann direkt Place -> Games.
    """
    if not place_id:
        return "Unknown Game"

    try:
        async with aiohttp.ClientSession() as session:
            # 1️⃣ Place → Universe
            async with session.get(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe") as r1:
                if r1.status == 200:
                    data1 = await r1.json()
                    universe_id = data1.get("universeId")
                else:
                    universe_id = None

            # 2️⃣ Universe → Game Name
            if universe_id:
                async with session.get(f"https://games.roblox.com/v1/games?universeIds={universe_id}") as r2:
                    if r2.status == 200:
                        data2 = await r2.json()
                        game_data = data2.get("data")
                        if game_data and len(game_data) > 0:
                            return game_data[0].get("name", "Unknown Game")

            # 3️⃣ Fallback: Place direkt prüfen
            async with session.get(f"https://games.roblox.com/v1/games?placeIds={place_id}") as r3:
                if r3.status == 200:
                    data3 = await r3.json()
                    game_data3 = data3.get("data")
                    if game_data3 and len(game_data3) > 0:
                        return game_data3[0].get("name", "Unknown Game")

            return "Unknown Game"

    except Exception as e:
        print(f"Fehler beim Abrufen des Game-Namens (modern APIs): {e}")
        return "Unknown Game"

# ================== SLASH COMMANDS ==================
@tree.command(
    name="choose-bounty-channel",
    description="Setzt den Channel für alle Bounty-Embeds (Dropdown oder ID)"
)
@app_commands.check(admin_only)
@app_commands.describe(channel_input="Wähle einen Textchannel oder gib die Channel-ID ein")
async def choose_bounty_channel(interaction: discord.Interaction, channel_input: str):
    gid = str(interaction.guild.id)
    data = load_data()

    channel = None
    if channel_input.isdigit():
        channel = interaction.guild.get_channel(int(channel_input))
    elif channel_input.startswith("<#") and channel_input.endswith(">"):
        cid = int(channel_input[2:-1])
        channel = interaction.guild.get_channel(cid)
    else:
        for c in interaction.guild.text_channels:
            if c.name == channel_input.strip("#"):
                channel = c
                break

    if not channel or not isinstance(channel, TextChannel):
        await interaction.response.send_message(
            "Ungültiger Channel. Bitte eine gültige ID oder Channel auswählen.",
            ephemeral=True
        )
        return

    data.setdefault(gid, {})
    data[gid]["channel_id"] = channel.id
    data[gid].setdefault("users", {})
    save_data(data)

    await interaction.response.send_message(
        f"Bounty-Channel gesetzt: {channel.mention}", ephemeral=True
    )

@tree.command(name="add-user", description="Fügt einen Roblox User zur Bounty-Liste hinzu")
@app_commands.check(admin_only)
@app_commands.describe(roblox_id="Roblox User ID")
async def add_user(interaction: discord.Interaction, roblox_id: int):
    data = load_data()
    gid = str(interaction.guild.id)
    if gid not in data or "channel_id" not in data[gid]:
        await interaction.response.send_message(
            "Bitte zuerst /choose-bounty-channel ausführen.",
            ephemeral=True
        )
        return

    users = data[gid].setdefault("users", {})
    if str(roblox_id) in users:
        await interaction.response.send_message(
            "User ist bereits in der Liste.", ephemeral=True
        )
        return

    user = await get_roblox_user(roblox_id)
    if not user:
        await interaction.response.send_message(
            "Roblox User nicht gefunden.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"{user['displayName']} ({user['name']})",
        description="Initialisiert...",
        color=discord.Color.red()
    )

    channel = interaction.guild.get_channel(data[gid]["channel_id"])
    message = await channel.send(embed=embed)

    users[str(roblox_id)] = {
        "roblox_id": roblox_id,
        "username": user["name"],
        "display_name": user["displayName"],
        "message_id": message.id,
        "last_online": None
    }

    save_data(data)
    await interaction.response.send_message("User hinzugefügt.", ephemeral=True)

@tree.command(name="remove-user", description="Entfernt einen User aus der Bounty-Liste")
@app_commands.check(admin_only)
@app_commands.describe(user="Roblox ID oder Username")
async def remove_user(interaction: discord.Interaction, user: str):
    data = load_data()
    gid = str(interaction.guild.id)
    users = data.get(gid, {}).get("users", {})

    for k in list(users.keys()):
        if user.lower() in (k, users[k]["username"].lower()):
            del users[k]
            save_data(data)
            await interaction.response.send_message("User entfernt.", ephemeral=True)
            return

    await interaction.response.send_message("User nicht gefunden.", ephemeral=True)

@tree.command(name="show-bounty-list", description="Zeigt alle gesuchten Spieler")
@app_commands.check(admin_only)
async def show_bounty_list(interaction: discord.Interaction):
    data = load_data().get(str(interaction.guild.id), {}).get("users", {})
    if not data:
        await interaction.response.send_message("Keine Bounties vorhanden.", ephemeral=True)
        return
    await interaction.response.send_message(
        "\n".join(f"ID: {v['roblox_id']} | User: {v['username']}" for v in data.values()),
        ephemeral=True
    )

# ================== MONITOR ==================
@tasks.loop(seconds=CHECK_INTERVAL)
async def monitor_users():
    data = load_data()
    for guild in client.guilds:
        gid = str(guild.id)
        guild_data = data.get(gid)
        if not guild_data:
            continue

        channel = guild.get_channel(guild_data.get("channel_id"))
        if not channel:
            continue

        for user in guild_data.get("users", {}).values():
            presence = await get_presence(user["roblox_id"])
            if not presence:
                continue

            embed = discord.Embed(title=f"{user['display_name']} ({user['username']})")
            status = presence["userPresenceType"]

            if status == 0:
                embed.color = discord.Color.red()
                embed.description = "**Is offline!**"
                if user["last_online"]:
                    embed.description += f"\n**Played for: {format_duration(time.time() - user['last_online'])}**"
                    user["last_online"] = None

            elif status == 1:
                embed.color = discord.Color.from_rgb(120, 180, 255)
                embed.description = "**Is now online!**\n**Location: Robloxmenu**"
                user["last_online"] = user["last_online"] or time.time()

            elif status == 2:
                embed.color = discord.Color.green()
                place_id = presence.get("placeId")
                game_name = await get_game_name_modern(place_id)
                embed.description = f"**Is now playing!**\n**Location: {game_name}**"
                user["last_online"] = user["last_online"] or time.time()

            try:
                msg = await channel.fetch_message(user["message_id"])
                await msg.edit(embed=embed)
            except:
                pass

    save_data(data)

# ================== START ==================
@client.event
async def on_ready():
    reset_data_on_startup()
    await tree.sync()
    monitor_users.start()
    print("Bot gestartet – Moderne APIs für Game-Namen – Dropdown/ID Channel")

client.run(TOKEN)
