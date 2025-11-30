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
POLL_INTERVAL = 30  # Sekunden

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

# ================== COLORS ==================
RED = discord.Color.red()
COLOR_GREEN = discord.Color.from_rgb(64, 255, 64)
COLOR_RED = discord.Color.from_rgb(255, 64, 64)

# -----------------------------
# PANIC MODAL
# -----------------------------
class PanicModal(discord.ui.Modal, title="🚨 Panic Request"):
    username = discord.ui.TextInput(label="Roblox Username", placeholder="Dein Roblox Username", required=True, max_length=50)
    location = discord.ui.TextInput(label="Location", placeholder="Wo befindest du dich?", required=True, max_length=100)
    additional_info = discord.ui.TextInput(label="Additional Information", placeholder="Zusätzliche Informationen", required=False, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        panic_channel_id = data.get("panic_channel")
        panic_role_id = data.get("panic_role")

        if panic_channel_id is None or panic_role_id is None:
            await interaction.response.send_message(
                "❌ Panic-Channel oder Panic-Rolle nicht gesetzt!",
                ephemeral=True
            )
            return

        channel = interaction.client.get_channel(panic_channel_id)
        role_ping = f"<@&{panic_role_id}>"

        embed = discord.Embed(
            title=f"🚨 Panic Button pressed by {interaction.user}",
            color=RED
        )
        embed.add_field(name="Roblox Username", value=self.username.value, inline=False)
        embed.add_field(name="Location", value=self.location.value, inline=False)
        embed.add_field(name="Additional Information", value=self.additional_info.value or "Keine", inline=False)

        await channel.send(f"**__🚨{role_ping} panic!🚨__**", embed=embed)
        await interaction.response.send_message("✅ Panic Alert gesendet!", ephemeral=True)

# -----------------------------
# PANIC BUTTON
# -----------------------------
class PanicButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚨 Panic", style=discord.ButtonStyle.danger, custom_id="panic_button")
    async def panic_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PanicModal()
        await interaction.response.send_modal(modal)

# -----------------------------
# ADMIN CHECK
# -----------------------------
def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

# -----------------------------
# SLASH COMMANDS: PANIC
# -----------------------------
@bot.tree.command(name="create-panic-button", description="Erstellt den Panic Button")
async def create_panic_button(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🚨 Panic Button",
        description="Wenn du Hilfe benötigst, drücke den Panic Button.",
        color=RED
    )
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

@bot.tree.command(name="set-panic-role", description="Setze die Rolle die beim Panic gepingt wird")
async def set_panic_role(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return

    data["panic_role"] = role.id
    save_data()
    await interaction.response.send_message(f"Panic Rolle gesetzt auf {role.mention}", ephemeral=True)

# -----------------------------
# ROBLOX TRACKING
# -----------------------------
last_status: Dict[int, str] = {}
online_start_times: Dict[int, float] = {}

def format_played_time(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} sec"
    elif seconds < 3600:
        return f"{int(seconds//60)} min {int(seconds%60)} sec"
    elif seconds < 86400:
        h = int(seconds//3600)
        m = int((seconds%3600)//60)
        return f"{h} h {m} min"
    else:
        d = int(seconds//86400)
        h = int((seconds%86400)//3600)
        return f"{d} d {h} h"

async def roblox_get_user_by_username(session: aiohttp.ClientSession, username: str) -> Optional[Dict]:
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": False}
    try:
        async with session.post(url, json=payload, timeout=10) as resp:
            if resp.status != 200:
                return None
            js = await resp.json()
            if "data" in js and len(js["data"]) > 0:
                u = js["data"][0]
                return {"id": u["id"], "name": u["name"], "displayName": u.get("displayName", u["name"])}
    except:
        return None
    return None

async def roblox_get_presences(session: aiohttp.ClientSession, user_ids: List[int]) -> Dict:
    url = "https://presence.roblox.com/v1/presence/users"
    payload = {"userIds": user_ids}
    try:
        async with session.post(url, json=payload, timeout=10) as resp:
            if resp.status != 200:
                return {}
            return await resp.json()
    except:
        return {}

async def roblox_get_avatar_url(session: aiohttp.ClientSession, user_id: int, size: int = 150) -> Optional[str]:
    url = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
    params = {"userIds": str(user_id), "size": str(size), "format": "Png", "isCircular": "false"}
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            if resp.status != 200:
                return None
            js = await resp.json()
            if "data" in js and len(js["data"]) > 0:
                return js["data"][0].get("imageUrl")
    except:
        return None
    return None

def build_online_embed(display_name: str, username: str, avatar_url: Optional[str]) -> discord.Embed:
    title = "🟢**Online!**🟢"
    description = f"**{display_name} ({username})** is online!"
    e = discord.Embed(title=title, description=description, color=COLOR_GREEN)
    if avatar_url:
        e.set_thumbnail(url=avatar_url)
    return e

def build_offline_embed(display_name: str, username: str, avatar_url: Optional[str], played_str: str = "") -> discord.Embed:
    title = "🔴**Offline!**🔴"
    description = f"**{display_name} ({username})** is offline!{played_str}"
    e = discord.Embed(title=title, description=description, color=COLOR_RED)
    if avatar_url:
        e.set_thumbnail(url=avatar_url)
    return e

# -----------------------------
# ROBLOX SLASH COMMANDS
# -----------------------------
def admin_check(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

@bot.tree.command(name="choose-bounty-log", description="Set the channel where status embeds will be posted")
@app_commands.describe(channel="Wähle den Channel für die Embeds")
async def choose_bounty_log(interaction: discord.Interaction, channel: discord.TextChannel):
    if not admin_check(interaction):
        await interaction.response.send_message("Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    data["log_channel"] = channel.id
    save_data()
    await interaction.response.send_message(f"Log channel gesetzt auf {channel.mention}", ephemeral=True)

@bot.tree.command(name="add-user", description="Add a Roblox username to the tracked list")
@app_commands.describe(username="Roblox username (z. B. Builderman)")
async def add_user(interaction: discord.Interaction, username: str):
    if not admin_check(interaction):
        await interaction.response.send_message("Nur Admins dürfen diesen Befehl nutzen.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        user = await roblox_get_user_by_username(session, username)
        if not user:
            await interaction.followup.send(f"Roblox-User `{username}` nicht gefunden.", ephemeral=True)
            return
        for t in data["tracked"]:
            if t["userId"] == user["id"]:
                await interaction.followup.send(f"`{user['name']}` ist bereits in der Liste.", ephemeral=True)
                return
        data["tracked"].append({
            "username": user["name"],
            "userId": user["id"],
            "displayName": user.get("displayName", user["name"])
        })
        save_data()
        await interaction.followup.send(f"`{user['name']}` wurde hinzugefügt.", ephemeral=True)

@bot.tree.command(name="remove-user", description="Remove a Roblox username from the tracked list")
@app_commands.describe(username="Roblox username to remove")
async def remove_user(interaction: discord.Interaction, username: str):
    if not admin_check(interaction):
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
        await interaction.response.send_message(f"`{username}` nicht in der Liste gefunden.", ephemeral=True)

@bot.tree.command(name="show-bounty-list", description="Show the tracked Roblox players")
async def show_bounty_list(interaction: discord.Interaction):
    if not data.get("tracked"):
        await interaction.response.send_message("Aktuell sind keine Spieler in der Liste.", ephemeral=False)
        return
    lines = []
    for t in data["tracked"]:
        lines.append(f"- **{t.get('displayName','-')}** (`{t.get('username')}`)")
    await interaction.response.send_message(f"**Tracked Players:**\n" + "\n".join(lines), ephemeral=False)

# -----------------------------
# BACKGROUND TASK
# -----------------------------
@tasks.loop(seconds=POLL_INTERVAL)
async def presence_poll():
    if not bot.is_ready():
        return
    if not data.get("tracked") or not data.get("log_channel"):
        return
    log_channel = bot.get_channel(data["log_channel"])
    if not log_channel:
        return
    user_ids = [t["userId"] for t in data["tracked"]]
    BATCH = 100
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(user_ids), BATCH):
            batch_ids = user_ids[i:i+BATCH]
            resp = await roblox_get_presences(session, batch_ids)
            user_presences = resp.get("userPresences", [])
            pres_by_id = {p.get("userId"): p for p in user_presences}
            for tracked_item in data["tracked"]:
                uid = tracked_item["userId"]
                username = tracked_item.get("username")
                display_name = tracked_item.get("displayName", username)
                pres = pres_by_id.get(uid)
                online_now = pres.get("userPresenceType") == 2 if pres else False

                current = "ONLINE" if online_now else "OFFLINE"
                previous = last_status.get(uid)

                if current != previous:
                    last_status[uid] = current
                    avatar_url = await roblox_get_avatar_url(session, uid)

                    if current == "ONLINE":
                        online_start_times[uid] = time.time()
                        embed = build_online_embed(display_name, username, avatar_url)
                    else:
                        start_time = online_start_times.pop(uid, None)
                        played_str = ""
                        if start_time:
                            played_sec = time.time() - start_time
                            played_str = f"\nPlayed for: {format_played_time(played_sec)}"
                        embed = build_offline_embed(display_name, username, avatar_url, played_str)

                    try:
                        await log_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Fehler Embed senden für {username}: {e}")

# -----------------------------
# BOT READY
# -----------------------------
@bot.event
async def on_ready():
    bot.add_view(PanicButtonView())
    await bot.tree.sync()
    if not presence_poll.is_running():
        presence_poll.start()
    print(f"Bot ist online als {bot.user}")

bot.run(TOKEN)
