# main.py
import os
import json
import random
import string
from datetime import datetime, timedelta
import pytz

import discord
from discord import app_commands
from discord.ext import commands, tasks

# =================== CONFIG ===================
GER_TZ = pytz.timezone("Europe/Berlin")
TOKEN = os.getenv("DISCORD_TOKEN")  # Railway env var

DATA_FILE = "data.json"

# Limits pro User / Tag
LIMITS = {
    "timeout": 10,
    "kick": 3,
    "ban": 2
}

# ---------------- INTENTS ----------------
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
try:
    bot.remove_command("help")
except Exception:
    pass

# =================== PERSISTENT DATEN ===================
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"guilds": {}, "global_ids": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

data = load_data()

def today_str():
    return datetime.now(GER_TZ).date().isoformat()

def generate_id(length=14):
    chars = string.ascii_letters + string.digits + "!§$%&/?#@_-+"
    return ''.join(random.choice(chars) for _ in range(length))

# =================== UTILITIES ===================
def find_member(guild: discord.Guild, input_str: str):
    if not input_str or not guild:
        return None
    s = input_str.strip()
    if s.startswith("<@") and s.endswith(">"):
        s = s.replace("<@", "").replace(">", "").replace("!", "")
    s = s.lstrip("@").strip()
    # ID
    if s.isdigit():
        try:
            return guild.get_member(int(s)) or guild.fetch_member(int(s))
        except:
            return None
    s_low = s.lower()
    # username#discriminator
    if "#" in s:
        name, disc = s.rsplit("#", 1)
        for m in guild.members:
            if m.name.lower() == name.lower() and m.discriminator == disc:
                return m
    # partial match display_name or name
    for m in guild.members:
        if s_low in (m.display_name or "").lower() or s_low in (m.name or "").lower():
            return m
    return None

def ensure_guild_entry(guild_id: int):
    gid = str(guild_id)
    if gid not in data["guilds"]:
        data["guilds"][gid] = {"actions": {}, "last_reset": today_str()}
        save_data()
    return data["guilds"][gid]

def ensure_user_entry(guild_id: int, user_id: int):
    g = ensure_guild_entry(guild_id)
    uid = str(user_id)
    if uid not in g["actions"]:
        g["actions"][uid] = {"timeout": 0, "kick": 0, "ban": 0, "used_global_id": False}
        save_data()
    return g["actions"][uid]

def check_limit(user_entry: dict, action: str, user_id: int, guild_owner_id: int, provided_id: str = None):
    """Prüft Limit + globale ID Bypass"""
    # Limit überschritten
    if user_entry[action] >= LIMITS[action]:
        # Überprüfe globale ID
        if provided_id:
            g_id_entry = data["global_ids"].get(str(guild_owner_id))
            if g_id_entry and g_id_entry["id"] == provided_id and str(user_id) not in g_id_entry.get("used_by", []):
                # Bypass einmalig erlaubt
                g_id_entry.setdefault("used_by", []).append(str(user_id))
                save_data()
                return True  # Limit gebypasst
        return False  # Limit überschritten
    return True  # unter Limit

# =================== VIEWS ===================
class DirectMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="TIMEOUT", style=discord.ButtonStyle.primary, custom_id="persistent_timeout_btn")
    async def timeout_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Timeout Optionen:", view=TimeoutMenu(), ephemeral=True)

    @discord.ui.button(label="KICK", style=discord.ButtonStyle.secondary, custom_id="persistent_kick_btn")
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Kick Optionen:", view=KickMenu(), ephemeral=True)

    @discord.ui.button(label="BAN", style=discord.ButtonStyle.danger, custom_id="persistent_ban_btn")
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Ban Optionen:", view=BanMenu(), ephemeral=True)

class TimeoutMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Timeout someone", style=discord.ButtonStyle.danger, custom_id="persistent_timeout_someone")
    async def timeout_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TimeoutModal())
    @discord.ui.button(label="Untimeout someone", style=discord.ButtonStyle.success, custom_id="persistent_untimeout_someone")
    async def untimeout_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UntimeoutModal())

class KickMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Kick someone", style=discord.ButtonStyle.danger, custom_id="persistent_kick_someone")
    async def kick_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KickModal())

class BanMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Ban someone", style=discord.ButtonStyle.danger, custom_id="persistent_ban_someone")
    async def ban_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BanModal())

# =================== MODALS ===================
class TimeoutModal(discord.ui.Modal, title="Timeout someone"):
    user = discord.ui.TextInput(label="User ID oder Name", required=True)
    seconds = discord.ui.TextInput(label="Sekunden", default="0", required=False)
    minutes = discord.ui.TextInput(label="Minuten", default="0", required=False)
    hours = discord.ui.TextInput(label="Stunden", default="0", required=False)
    global_id = discord.ui.TextInput(label="Globale ID (optional)", required=False, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        author = interaction.user
        member = find_member(guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return

        # Dauer berechnen
        total_seconds = int(self.seconds.value or 0) + int(self.minutes.value or 0)*60 + int(self.hours.value or 0)*3600
        if total_seconds <= 0:
            await interaction.response.send_message("⚠️ Ungültige Dauer.", ephemeral=True)
            return

        user_entry = ensure_user_entry(guild.id, author.id)
        if not check_limit(user_entry, "timeout", author.id, guild.owner_id, self.global_id.value):
            await interaction.response.send_message("❌ Limit erreicht. Globale ID erforderlich!", ephemeral=True)
            return

        try:
            await member.timeout(timedelta(seconds=total_seconds), reason=f"Timeout by {author}")
            # nur hochzählen, wenn Limit nicht durch Bypass überschritten
            if user_entry["timeout"] < LIMITS["timeout"]:
                user_entry["timeout"] += 1
            save_data()
            await interaction.response.send_message(f"✅ {member.mention} getimeoutet ({total_seconds} Sekunden).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

class UntimeoutModal(discord.ui.Modal, title="Untimeout someone"):
    user = discord.ui.TextInput(label="User ID oder Name", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        member = find_member(interaction.guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return
        try:
            await member.timeout(None)
            await interaction.response.send_message(f"✅ {member.mention} ent-timeoutet.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

class KickModal(discord.ui.Modal, title="Kick someone"):
    user = discord.ui.TextInput(label="User ID oder Name", required=True)
    global_id = discord.ui.TextInput(label="Globale ID (optional)", required=False, max_length=50)
    async def on_submit(self, interaction: discord.Interaction):
        member = find_member(interaction.guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return
        user_entry = ensure_user_entry(interaction.guild.id, interaction.user.id)
        if not check_limit(user_entry, "kick", interaction.user.id, interaction.guild.owner_id, self.global_id.value):
            await interaction.response.send_message("❌ Limit erreicht. Globale ID erforderlich!", ephemeral=True)
            return
        try:
            await member.kick(reason=f"Kicked by {interaction.user}")
            if user_entry["kick"] < LIMITS["kick"]:
                user_entry["kick"] += 1
            save_data()
            await interaction.response.send_message(f"✅ {member.mention} gekickt.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

class BanModal(discord.ui.Modal, title="Ban someone"):
    user = discord.ui.TextInput(label="User ID oder Name", required=True)
    global_id = discord.ui.TextInput(label="Globale ID (optional)", required=False, max_length=50)
    async def on_submit(self, interaction: discord.Interaction):
        member = find_member(interaction.guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return
        user_entry = ensure_user_entry(interaction.guild.id, interaction.user.id)
        if not check_limit(user_entry, "ban", interaction.user.id, interaction.guild.owner_id, self.global_id.value):
            await interaction.response.send_message("❌ Limit erreicht. Globale ID erforderlich!", ephemeral=True)
            return
        try:
            await member.ban(reason=f"Banned by {interaction.user}")
            if user_entry["ban"] < LIMITS["ban"]:
                user_entry["ban"] += 1
            save_data()
            await interaction.response.send_message(f"✅ {member.mention} gebannt.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# =================== SLASH COMMANDS ===================
@bot.tree.command(name="direct", description="Öffne das Moderationsmenü")
async def direct(interaction: discord.Interaction):
    await interaction.response.send_message("🛠️ Moderationsmenü:", view=DirectMenu(), ephemeral=True)

@bot.tree.command(name="show-my-id", description="Zeigt globale Owner-ID (nur Eigentümer)")
async def show_my_id(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Nur Eigentümer darf das sehen.", ephemeral=True)
        return
    owner_id = str(interaction.user.id)
    today = today_str()
    if owner_id not in data["global_ids"] or data["global_ids"][owner_id]["last_reset"] != today:
        data["global_ids"][owner_id] = {"id": generate_id(), "last_reset": today, "used_by": []}
        save_data()
    await interaction.response.send_message(f"🔑 Deine globale ID: `{data['global_ids'][owner_id]['id']}`", ephemeral=True)

# =================== DAILY RESET ===================
@tasks.loop(minutes=1)
async def daily_reset():
    now = datetime.now(GER_TZ)
    if now.hour == 0 and now.minute == 0:
        # reset limits per guild
        for guild_id, gdata in data.get("guilds", {}).items():
            gdata["actions"] = {}
            gdata["last_reset"] = today_str()
        # reset global IDs
        for owner_id, entry in data.get("global_ids", {}).items():
            entry["id"] = generate_id()
            entry["last_reset"] = today_str()
            entry["used_by"] = []
        save_data()
        print("[🔁] Tagesreset durchgeführt")

# =================== READY ===================
@bot.event
async def on_ready():
    # persistent views
    bot.add_view(DirectMenu())
    bot.add_view(TimeoutMenu())
    bot.add_view(KickMenu())
    bot.add_view(BanMenu())
    daily_reset.start()
    await bot.tree.sync()
    print(f"✅ Bot eingeloggt als {bot.user}")

bot.run(TOKEN)
