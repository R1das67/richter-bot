import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
from typing import List, Dict
import time

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN nicht gesetzt!")

DATA_FILE = "bot_data.json"
POLL_INTERVAL = 30  # Sekunden

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="$", intents=intents)

# -----------------------------
# DATA HANDLING
# -----------------------------
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
else:
    data = {
        "panic_channel": None,
        "panic_role": None,
        "tracked": [],
        "log_channel": None
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# COLORS
# -----------------------------
RED = discord.Color.red()
COLOR_PLAYING = discord.Color.from_rgb(64, 255, 64)
COLOR_OFFLINE = discord.Color.from_rgb(255, 64, 64)

# -----------------------------
# PANIC SYSTEM
# -----------------------------
class PanicModal(discord.ui.Modal, title="🚨 Panic Request"):
    username = discord.ui.TextInput(label="Roblox Username", required=True)
    location = discord.ui.TextInput(label="Location", required=True)
    additional_info = discord.ui.TextInput(label="Additional Information", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        panic_channel_id = data.get("panic_channel")
        panic_role_id = data.get("panic_role")
        if panic_channel_id is None or panic_role_id is None:
            await interaction.response.send_message("❌ Panic-Channel oder Panic-Rolle nicht gesetzt!", ephemeral=True)
            return

        channel = interaction.client.get_channel(panic_channel_id)
        role_ping = f"<@&{panic_role_id}>"

        embed = discord.Embed(title=f"🚨 Panic Button pressed by {interaction.user}", color=RED)
        embed.add_field(name="Roblox Username", value=self.username.value, inline=False)
        embed.add_field(name="Location", value=self.location.value, inline=False)
        embed.add_field(name="Additional Information", value=self.additional_info.value or "Keine", inline=False)

        await channel.send(f"**__🚨{role_ping} panic!🚨__**", embed=embed)
        await interaction.response.send_message("✅ Panic Alert gesendet!", ephemeral=True)

class PanicButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚨 Panic", style=discord.ButtonStyle.danger, custom_id="panic_button")
    async def panic_button_callback(self, interaction, button):
        await interaction.response.send_modal(PanicModal())

# -----------------------------
# ROBLOX API HELPERS
# -----------------------------
last_status: Dict[int, str] = {}
online_start_times: Dict[int, float] = {}

async def roblox_get_presences(session, user_ids: List[int]):
    url = "https://presence.roblox.com/v1/presence/users"
    try:
        async with session.post(url, json={"userIds": user_ids}, timeout=10) as resp:
            return await resp.json() if resp.status == 200 else {}
    except:
        return {}

async def roblox_get_game_data(session, place_id):
    url = f"https://games.roblox.com/v1/games?universeIds={place_id}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200: return None
            js = await resp.json()
            return js["data"][0]["name"] if js.get("data") else None
    except:
        return None

async def roblox_get_game_info_from_presence(pres, session):
    place_id = pres.get("placeId") or pres.get("rootPlaceId")
    last_location = pres.get("lastLocation")
    game_name = None
    game_link = None

    if place_id:
        game_name = await roblox_get_game_data(session, place_id)
        if game_name:
            game_link = f"https://www.roblox.com/games/{place_id}"
    if not game_name:
        game_name = last_location or "Öffentlicher Server"

    return game_name, game_link, "Playing"

async def roblox_get_avatar_url(session, user_id, size=150):
    url = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
    params = {"userIds": str(user_id), "size": str(size), "format": "Png", "isCircular": "false"}
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            js = await resp.json()
            return js.get("data", [{}])[0].get("imageUrl")
    except:
        return None

# -----------------------------
# TIME FORMATTER
# -----------------------------
def format_played_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} sec"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min {seconds % 60} sec"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h {minutes % 60} min"
    days = hours // 24
    return f"{days} d {hours % 24} h"

# -----------------------------
# EMBED BUILDERS
# -----------------------------
def embed_playing(display, username, avatar, game_name, game_link):
    description = f"**{display} ({username})** is now playing!\nLocation: {game_name or 'Unbekannt'}"
    e = discord.Embed(
        title="🟢 Playing",
        description=description,
        color=COLOR_PLAYING
    )
    if avatar: e.set_thumbnail(url=avatar)
    if game_link: e.set_author(name=game_name, url=game_link)
    return e

def embed_offline(display, username, avatar, played_str):
    e = discord.Embed(
        title="🔴 Offline",
        description=f"**{display} ({username})** is offline!\nPlayed for: {played_str}",
        color=COLOR_OFFLINE
    )
    if avatar: e.set_thumbnail(url=avatar)
    return e

# -----------------------------
# SLASH COMMANDS
# -----------------------------
def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

@bot.tree.command(name="create-panic-button", description="Erstellt den Panic Button")
async def create_panic_button(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    embed = discord.Embed(title="🚨 Panic Button", description="Drücke den Button wenn du Hilfe brauchst.", color=RED)
    view = PanicButtonView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Panic Button erstellt!", ephemeral=True)

@bot.tree.command(name="set-panic-channel", description="Setze den Panic Channel")
async def set_panic_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    data["panic_channel"] = channel.id
    save_data()
    await interaction.response.send_message(f"Panic Channel gesetzt auf {channel.mention}", ephemeral=True)

@bot.tree.command(name="set-panic-role", description="Setze die Panic Rolle")
async def set_panic_role(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    data["panic_role"] = role.id
    save_data()
    await interaction.response.send_message(f"Panic Rolle gesetzt auf {role.mention}", ephemeral=True)

@bot.tree.command(name="choose-bounty-log", description="Setze Log-Channel für Status Embeds")
async def choose_bounty_log(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    data["log_channel"] = channel.id
    save_data()
    await interaction.response.send_message(f"Log channel gesetzt auf {channel.mention}", ephemeral=True)

@bot.tree.command(name="add-user", description="Füge einen Roblox User zur Liste hinzu")
async def add_user(interaction: discord.Interaction, user_id: int):
    if not is_admin(interaction):
        await interaction.response.send_message("Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        url = f"https://users.roblox.com/v1/users/{user_id}"
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"Roblox-User mit ID `{user_id}` nicht gefunden.", ephemeral=True)
                    return
                user_data = await resp.json()
                username = user_data["name"]
                display_name = user_data.get("displayName", username)
        except:
            await interaction.followup.send(f"Fehler beim Abrufen des Benutzers.", ephemeral=True)
            return
        for t in data["tracked"]:
            if t["userId"] == user_id:
                await interaction.followup.send(f"`{username}` ist bereits in der Liste.", ephemeral=True)
                return
        data["tracked"].append({"username": username, "userId": user_id, "displayName": display_name})
        save_data()
        await interaction.followup.send(f"`{username}` ({display_name}) wurde hinzugefügt.", ephemeral=True)

@bot.tree.command(name="remove-user", description="Entferne einen Roblox User aus der Liste")
async def remove_user(interaction: discord.Interaction, username: str):
    if not is_admin(interaction):
        await interaction.response.send_message("Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    removed = None
    for t in list(data["tracked"]):
        if t["username"].lower() == username.lower():
            removed = t
            data["tracked"].remove(t)
            save_data()
            break
    if removed:
        await interaction.response.send_message(f"`{removed['username']}` entfernt.", ephemeral=True)
    else:
        await interaction.response.send_message(f"`{username}` nicht gefunden.", ephemeral=True)

@bot.tree.command(name="show-bounty-list", description="Zeige die Liste der getrackten Roblox User")
async def show_bounty_list(interaction: discord.Interaction):
    if not data.get("tracked"):
        await interaction.response.send_message("Keine Spieler in der Liste.", ephemeral=False)
        return
    lines = [f"- **{t.get('displayName','-')}** (`{t.get('username')}`)" for t in data["tracked"]]
    await interaction.response.send_message("**Tracked Players:**\n" + "\n".join(lines), ephemeral=False)

# -----------------------------
# BACKGROUND POLLING
# -----------------------------
@tasks.loop(seconds=POLL_INTERVAL)
async def presence_poll():
    if not bot.is_ready() or not data.get("tracked") or not data.get("log_channel"): 
        return
    log_channel = bot.get_channel(data["log_channel"])
    if not log_channel: 
        return
    user_ids = [t["userId"] for t in data["tracked"]]
    async with aiohttp.ClientSession() as session:
        resp = await roblox_get_presences(session, user_ids)
        presences = {p["userId"]: p for p in resp.get("userPresences", [])}
        for t in data["tracked"]:
            uid = t["userId"]
            username = t["username"]
            display = t.get("displayName", username)
            pres = presences.get(uid, {})
            ptype = pres.get("userPresenceType", 0)
            status = "OFFLINE" if ptype == 0 else "MENU" if ptype == 1 else "PLAYING"
            prev = last_status.get(uid)

            if status != prev:
                last_status[uid] = status
                avatar = await roblox_get_avatar_url(session, uid)

                if status == "PLAYING":
                    online_start_times.setdefault(uid, time.time())
                    game_name, game_link, _ = await roblox_get_game_info_from_presence(pres, session)
                    embed = embed_playing(display, username, avatar, game_name, game_link)

                else:  # OFFLINE
                    start = online_start_times.pop(uid, None)
                    played = int(time.time() - start) if start else 0
                    played_fmt = format_played_time(played)
                    embed = embed_offline(display, username, avatar, played_fmt)

                await log_channel.send(embed=embed)

# -----------------------------
# READY
# -----------------------------
@bot.event
async def on_ready():
    bot.add_view(PanicButtonView())
    await bot.tree.sync()
    if not presence_poll.is_running(): 
        presence_poll.start()
    print(f"Bot ist online als {bot.user}")

bot.run(TOKEN)
