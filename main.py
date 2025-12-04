import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
from typing import List, Dict, Optional
import time

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN nicht gesetzt!")

DATA_FILE = "bot_data.json"
POLL_INTERVAL = 30

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="$", intents=intents)

# -----------------------------
# DATA HANDLING
# -----------------------------
default_data = {
    "panic_channel": None,
    "panic_role": None,
    "tracked": [],
    "log_channel": None
}

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
else:
    data = default_data
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Colors
COLOR_MENU = discord.Color.from_rgb(80, 150, 255)
COLOR_PLAYING = discord.Color.from_rgb(64, 255, 64)
COLOR_OFFLINE = discord.Color.from_rgb(255, 64, 64)
RED = discord.Color.red()

# -----------------------------
# PANIC SYSTEM (unchanged)
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
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🚨 Panic", style=discord.ButtonStyle.danger, custom_id="panic_button")
    async def panic_button_callback(self, interaction, button): await interaction.response.send_modal(PanicModal())

# -----------------------------
# ROBLOX API HELPERS
# -----------------------------
last_status: Dict[int, str] = {}
online_start_times: Dict[int, float] = {}

async def roblox_get_presences(session: aiohttp.ClientSession, user_ids: List[int]):
    url = "https://presence.roblox.com/v1/presence/users"
    try:
        async with session.post(url, json={"userIds": user_ids}, timeout=10) as resp:
            return await resp.json() if resp.status == 200 else {}
    except: return {}

async def roblox_get_game_data(session, place_id):
    url = f"https://games.roblox.com/v1/games?universeIds={place_id}"
    try:
        async with session.get(url, timeout=10) as resp:
            js = await resp.json()
            return js["data"][0]["name"] if resp.status == 200 else None
    except: return None

async def roblox_get_game_info_from_presence(pres, session):
    place_id = pres.get("placeId")
    if not place_id or place_id == 0: return None, None, None
    game_name = await roblox_get_game_data(session, place_id)
    game_link = f"https://www.roblox.com/games/{place_id}"
    return game_name, game_link, "Playing"

async def roblox_get_avatar_url(session, user_id, size=150):
    url = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
    params = {"userIds": str(user_id), "size": str(size), "format": "Png", "isCircular": "false"}
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            js = await resp.json()
            return js.get("data", [{}])[0].get("imageUrl")
    except: return None

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
def small_user(display, username): return f"**{display} ({username})**"

def embed_menu(display, username, avatar):
    e = discord.Embed(
        title="🔵 Online",
        description=(
        f"{small_user(display, username)} is right now online!\n"
        f"Location: Roblox Menü"
     ),
     color=0x4da6ff
 )

def embed_playing(display, username, avatar, game_name, game_link):
    e = discord.Embed(title="🟢 Playing", description=f"{small_user(display, username)} is right now playing!
Location: {game_name}", color=COLOR_PLAYING)
    if avatar: e.set_thumbnail(url=avatar)
    e.set_author(name=game_name, url=game_link)
    return e

def embed_offline(display, username, avatar, played_str):
    e = discord.Embed(title="🔴 Offline", description=f"{small_user(display, username)} is right now offline!
Played for: {played_str}", color=COLOR_OFFLINE)
    if avatar: e.set_thumbnail(url=avatar)
    return e

# -----------------------------
# BACKGROUND POLLING
# -----------------------------
@tasks.loop(seconds=POLL_INTERVAL)
async def presence_poll():
    if not bot.is_ready(): return
    if not data.get("tracked") or not data.get("log_channel"): return

    log_channel = bot.get_channel(data["log_channel"])
    if not log_channel: return

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

                if status == "MENU":
                    onlinestart = online_start_times.setdefault(uid, time.time())
                    embed = embed_menu(display, username, avatar)

                elif status == "PLAYING":
                    online_start_times.setdefault(uid, time.time())
                    game_name, game_link, _ = await roblox_get_game_info_from_presence(pres, session)
                    if not game_name: game_name = f"Place {pres.get('placeId')}"
                    embed = embed_playing(display, username, avatar, game_name, game_link)

                else:
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
    if not presence_poll.is_running(): presence_poll.start()
    print(f"Bot ist online als {bot.user}")

bot.run(TOKEN)

