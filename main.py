import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import random
import string
from datetime import datetime, timedelta
import pytz
import os

# =================== CONFIG ===================
GER_TZ = pytz.timezone("Europe/Berlin")
TOKEN = os.getenv("DISCORD_TOKEN")

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.guilds = True
INTENTS.message_content = False

bot = commands.Bot(command_prefix="!", intents=INTENTS)
bot.remove_command("help")

DATA_FILE = "data.json"

LIMITS = {
    "timeout": 10,
    "kick": 3,
    "ban": 2
}

# =================== DATEN ===================
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

def generate_id(length=12):
    chars = string.ascii_letters + string.digits + "!§$%&/?#@"
    return ''.join(random.choice(chars) for _ in range(length))

def get_today():
    return datetime.now(GER_TZ).strftime("%Y-%m-%d")

def find_member(guild, input_str):
    # Entfernt @, wenn vorhanden
    clean_input = input_str.replace("@", "").strip().lower()
    # Prüft ob es eine ID ist
    if clean_input.isdigit():
        return guild.get_member(int(clean_input))
    # Sonst Suche nach Name/Displayname
    for m in guild.members:
        if clean_input in m.name.lower() or clean_input in m.display_name.lower():
            return m
    return None

# =================== PERSISTENT VIEWS ===================
class DirectMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="TIMEOUT", style=discord.ButtonStyle.primary)
    async def timeout_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Wähle Timeout-Option:", view=TimeoutMenu(), ephemeral=True)

    @discord.ui.button(label="KICK", style=discord.ButtonStyle.secondary)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Kick someone:", view=KickMenu(), ephemeral=True)

    @discord.ui.button(label="BAN", style=discord.ButtonStyle.danger)
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Ban someone:", view=BanMenu(), ephemeral=True)

class TimeoutMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Timeout someone", style=discord.ButtonStyle.danger)
    async def timeout_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TimeoutModal())

    @discord.ui.button(label="Untimeout someone", style=discord.ButtonStyle.success)
    async def untimeout_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UntimeoutModal())

class KickMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Kick someone", style=discord.ButtonStyle.danger)
    async def kick_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KickModal())

class BanMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ban someone", style=discord.ButtonStyle.danger)
    async def ban_someone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BanModal())

# =================== MODALS ===================
class TimeoutModal(discord.ui.Modal, title="Timeout someone"):
    user = discord.ui.TextInput(label="User ID oder Name", required=True)
    seconds = discord.ui.TextInput(label="Sekunden", default="0", required=False)
    minutes = discord.ui.TextInput(label="Minuten", default="0", required=False)
    hours = discord.ui.TextInput(label="Stunden", default="0", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        author = interaction.user
        guild_id = str(guild.id)
        today = get_today()

        if guild_id not in data["guilds"]:
            data["guilds"][guild_id] = {"actions": {}, "last_reset": today}

        guild_data = data["guilds"][guild_id]

        # Reset, falls Tag gewechselt
        if guild_data.get("last_reset") != today:
            guild_data["actions"] = {}
            guild_data["last_reset"] = today

        user_data = guild_data["actions"].setdefault(str(author.id), {"timeout": 0, "kick": 0, "ban": 0, "used_id": False})

        if user_data["timeout"] >= LIMITS["timeout"]:
            await interaction.response.send_message(
                f"❌ Du hast das Timeout-Limit erreicht. Bitte frage den Eigentümer nach der globalen ID.", ephemeral=True)
            save_data()
            return

        member = find_member(guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return

        total_seconds = int(self.seconds.value or 0) + int(self.minutes.value or 0) * 60 + int(self.hours.value or 0) * 3600
        if total_seconds <= 0:
            await interaction.response.send_message("⚠️ Bitte eine gültige Dauer angeben.", ephemeral=True)
            return

        try:
            await member.timeout(timedelta(seconds=total_seconds), reason=f"Timeout by {author}")
            user_data["timeout"] += 1
            save_data()
            await interaction.response.send_message(f"✅ {member.mention} getimeoutet für {total_seconds} Sekunden.", ephemeral=True)
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

    async def on_submit(self, interaction: discord.Interaction):
        member = find_member(interaction.guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return
        try:
            await member.kick(reason=f"Kicked by {interaction.user}")
            await interaction.response.send_message(f"✅ {member.mention} gekickt.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

class BanModal(discord.ui.Modal, title="Ban someone"):
    user = discord.ui.TextInput(label="User ID oder Name", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        member = find_member(interaction.guild, self.user.value)
        if not member:
            await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
            return
        try:
            await member.ban(reason=f"Banned by {interaction.user}")
            await interaction.response.send_message(f"✅ {member.mention} gebannt.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# =================== SLASH COMMANDS ===================
@bot.tree.command(name="direct", description="Öffne das Moderationsmenü")
async def direct(interaction: discord.Interaction):
    await interaction.response.send_message("🛠️ Wähle eine Aktion:", view=DirectMenu(), ephemeral=True)

@bot.tree.command(name="show-my-id", description="Zeigt die globale Owner-ID (nur Eigentümer)")
async def show_my_id(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Nur der Eigentümer darf das sehen.", ephemeral=True)
        return

    owner_id = str(interaction.user.id)
    today = get_today()

    if owner_id not in data["global_ids"] or data["global_ids"][owner_id]["last_reset"] != today:
        data["global_ids"][owner_id] = {"id": generate_id(), "last_reset": today}
        save_data()

    await interaction.response.send_message(f"🔑 Deine globale ID: `{data['global_ids'][owner_id]['id']}`", ephemeral=True)

# =================== DAILY RESET ===================
@tasks.loop(minutes=1)
async def daily_reset():
    now = datetime.now(GER_TZ)
    if now.hour == 0 and now.minute == 0:
        # Reset pro Guild
        for guild_id, guild_data in data.get("guilds", {}).items():
            guild_data["actions"] = {}
            guild_data["last_reset"] = get_today()
        # Reset globale IDs
        for owner_id, g in data.get("global_ids", {}).items():
            g["id"] = generate_id()
            g["last_reset"] = get_today()
        save_data()
        print("[🔁] Tagesdaten & globale IDs zurückgesetzt.")

# =================== READY ===================
@bot.event
async def on_ready():
    bot.add_view(DirectMenu())
    bot.add_view(TimeoutMenu())
    bot.add_view(KickMenu())
    bot.add_view(BanMenu())
    daily_reset.start()
    await bot.tree.sync()
    print(f"✅ Bot eingeloggt als {bot.user}")

bot.run(TOKEN)
