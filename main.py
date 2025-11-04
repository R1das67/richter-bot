import os
import random
import string
import asyncio
import sqlite3
from datetime import datetime, timedelta
import pytz

import discord
from discord import app_commands, Interaction, ui

# --- Konfiguration ---
DB_FILE = "data.db"
DAILY_TIMEOUT_LIMIT = 10
DAILY_KICK_LIMIT = 3
DAILY_BAN_LIMIT = 2
DAILY_ID_LENGTH = 12
GER_TZ = pytz.timezone("Europe/Berlin")

# --- Bot-Setup ---
intents = discord.Intents.default()
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# --- SQLite Setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS guilds (
            guild_id INTEGER PRIMARY KEY,
            daily_id TEXT,
            reset_date TEXT,
            mod_role_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS limits (
            guild_id INTEGER,
            user_id INTEGER,
            timeouts INTEGER DEFAULT 0,
            kicks INTEGER DEFAULT 0,
            bans INTEGER DEFAULT 0,
            used_id INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

def get_guild_data(guild_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT daily_id, reset_date, mod_role_id FROM guilds WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    if not row:
        daily_id = generate_daily_id()
        reset_date = current_date_str()
        c.execute("INSERT INTO guilds (guild_id, daily_id, reset_date) VALUES (?, ?, ?)", (guild_id, daily_id, reset_date))
        conn.commit()
        conn.close()
        return {"daily_id": daily_id, "reset_date": reset_date, "mod_role_id": None}
    conn.close()
    return {"daily_id": row[0], "reset_date": row[1], "mod_role_id": row[2]}

def update_guild_id(guild_id, new_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE guilds SET daily_id = ?, reset_date = ? WHERE guild_id = ?", (new_id, current_date_str(), guild_id))
    conn.commit()
    conn.close()

def reset_daily_limits():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM limits")
    conn.commit()
    conn.close()

def generate_daily_id():
    chars = string.ascii_letters + string.digits + "!§$%&?#@*()-_=+"
    return "".join(random.choice(chars) for _ in range(DAILY_ID_LENGTH))

def current_date_str():
    return datetime.now(GER_TZ).date().isoformat()

def ensure_limit_entry(guild_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM limits WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    if not c.fetchone():
        c.execute("INSERT INTO limits (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
        conn.commit()
    conn.close()

def increment_limit(guild_id, user_id, action):
    ensure_limit_entry(guild_id, user_id)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE limits SET {action} = {action} + 1 WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    conn.commit()
    conn.close()

def get_limits(guild_id, user_id):
    ensure_limit_entry(guild_id, user_id)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT timeouts, kicks, bans, used_id FROM limits WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = c.fetchone()
    conn.close()
    return {"timeouts": row[0], "kicks": row[1], "bans": row[2], "used_id": row[3]}

def mark_id_used(guild_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE limits SET used_id = 1 WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    conn.commit()
    conn.close()

def user_used_id(guild_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT used_id FROM limits WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0] == 1)

# --- Reset Loop ---
async def daily_reset_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now(GER_TZ)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (tomorrow - now).total_seconds()
        await asyncio.sleep(seconds_until_midnight)

        # Reset alle Limits und neue IDs
        reset_daily_limits()
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        for row in c.execute("SELECT guild_id FROM guilds"):
            gid = row[0]
            new_id = generate_daily_id()
            c.execute("UPDATE guilds SET daily_id = ?, reset_date = ?", (new_id, current_date_str(), gid))
        conn.commit()
        conn.close()
        print("✅ Täglicher Reset (Europe/Berlin) abgeschlossen.")

# --- Slash Commands ---
@tree.command(name="show-my-id", description="Zeigt dem Server-Eigentümer die heutige ID (nur Owner).")
async def show_my_id(interaction: Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Nur der Server-Eigentümer darf diesen Befehl verwenden.", ephemeral=True)
        return
    g = get_guild_data(interaction.guild.id)
    await interaction.response.send_message(f"📢 Heutige ID: `{g['daily_id']}` (gültig bis Mitternacht Deutschland)", ephemeral=True)

@tree.command(name="resetid", description="Generiert eine neue ID (nur Owner).")
async def resetid(interaction: Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Nur der Server-Eigentümer darf das.", ephemeral=True)
        return
    new_id = generate_daily_id()
    update_guild_id(interaction.guild.id, new_id)
    await interaction.response.send_message(f"✅ Neue ID wurde generiert: `{new_id}`", ephemeral=True)

@tree.command(name="stats", description="Zeigt heutige Moderationsstatistiken (Admins/Mods).")
async def stats(interaction: Interaction):
    member = interaction.user
    if not member.guild_permissions.administrator:
        await interaction.response.send_message("❌ Nur Admins dürfen das.", ephemeral=True)
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT SUM(timeouts), SUM(kicks), SUM(bans), COUNT(*) FROM limits WHERE guild_id = ?", (interaction.guild.id,))
    row = c.fetchone()
    conn.close()
    embed = discord.Embed(title="Tagesstatistiken", color=discord.Color.blurple())
    embed.add_field(name="Timeouts", value=str(row[0] or 0))
    embed.add_field(name="Kicks", value=str(row[1] or 0))
    embed.add_field(name="Bans", value=str(row[2] or 0))
    embed.add_field(name="Nutzer mit heutiger ID", value=str(row[3] or 0))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="direct", description="Öffnet das Moderations-Panel.")
async def direct(interaction: Interaction):
    if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ Du hast keine Berechtigung, dieses Menü zu öffnen.", ephemeral=True)
        return
    await interaction.response.send_message("Wähle eine Moderationsaktion:", view=MainPanel(), ephemeral=True)

# --- Panels & Modals ---
class MainPanel(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="TIMEOUT", style=discord.ButtonStyle.primary)
    async def timeout_btn(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(TimeoutModal())

    @ui.button(label="KICK", style=discord.ButtonStyle.danger)
    async def kick_btn(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(KickModal())

    @ui.button(label="BAN", style=discord.ButtonStyle.danger)
    async def ban_btn(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(BanModal())

# Timeout Modal
class TimeoutModal(ui.Modal, title="Timeout someone"):
    user = ui.TextInput(label="User ID oder @Mention")
    seconds = ui.TextInput(label="Sekunden", default="0")
    minutes = ui.TextInput(label="Minuten", default="0")
    hours = ui.TextInput(label="Stunden", default="0")
    bypass_id = ui.TextInput(label="Bypass ID (optional)", required=False)

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        author = interaction.user
        g = get_guild_data(guild.id)
        limits = get_limits(guild.id, author.id)
        duration = int(self.seconds.value) + int(self.minutes.value) * 60 + int(self.hours.value) * 3600
        if duration <= 0:
            await interaction.response.send_message("❌ Dauer muss größer als 0 sein.", ephemeral=True)
            return

        # Check Bypass ID
        bypass_ok = False
        if self.bypass_id.value.strip():
            if self.bypass_id.value.strip() == g["daily_id"]:
                if user_used_id(guild.id, author.id):
                    await interaction.response.send_message("⚠️ Du hast die heutige ID bereits verwendet.", ephemeral=True)
                    return
                else:
                    bypass_ok = True
                    mark_id_used(guild.id, author.id)
            else:
                await interaction.response.send_message("❌ Ungültige ID.", ephemeral=True)
                return

        if limits["timeouts"] >= DAILY_TIMEOUT_LIMIT and not bypass_ok:
            await interaction.response.send_message("⚠️ Du hast dein Timeout-Limit erreicht.", ephemeral=True)
            return

        try:
            user_id = int(self.user.value.strip("<@!>"))
            member = guild.get_member(user_id)
            if not member:
                await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
                return
            await member.timeout_for(timedelta(seconds=duration), reason=f"Timeout durch {author}")
            if not bypass_ok:
                increment_limit(guild.id, author.id, "timeouts")
            await interaction.response.send_message(f"✅ {member.mention} wurde für {duration} Sekunden getimeoutet.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# Kick Modal
class KickModal(ui.Modal, title="Kick someone"):
    user = ui.TextInput(label="User ID oder @Mention")
    bypass_id = ui.TextInput(label="Bypass ID (optional)", required=False)

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        author = interaction.user
        g = get_guild_data(guild.id)
        limits = get_limits(guild.id, author.id)
        bypass_ok = False
        if self.bypass_id.value.strip():
            if self.bypass_id.value.strip() == g["daily_id"]:
                if user_used_id(guild.id, author.id):
                    await interaction.response.send_message("⚠️ Du hast die heutige ID bereits verwendet.", ephemeral=True)
                    return
                else:
                    bypass_ok = True
                    mark_id_used(guild.id, author.id)
            else:
                await interaction.response.send_message("❌ Ungültige ID.", ephemeral=True)
                return

        if limits["kicks"] >= DAILY_KICK_LIMIT and not bypass_ok:
            await interaction.response.send_message("⚠️ Kick-Limit erreicht.", ephemeral=True)
            return
        try:
            user_id = int(self.user.value.strip("<@!>"))
            member = guild.get_member(user_id)
            if not member:
                await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
                return
            await member.kick(reason=f"Gekickt durch {author}")
            if not bypass_ok:
                increment_limit(guild.id, author.id, "kicks")
            await interaction.response.send_message(f"✅ {member.mention} wurde gekickt.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# Ban Modal
class BanModal(ui.Modal, title="Ban someone"):
    user = ui.TextInput(label="User ID oder @Mention")
    bypass_id = ui.TextInput(label="Bypass ID (optional)", required=False)

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        author = interaction.user
        g = get_guild_data(guild.id)
        limits = get_limits(guild.id, author.id)
        bypass_ok = False
        if self.bypass_id.value.strip():
            if self.bypass_id.value.strip() == g["daily_id"]:
                if user_used_id(guild.id, author.id):
                    await interaction.response.send_message("⚠️ Du hast die heutige ID bereits verwendet.", ephemeral=True)
                    return
                else:
                    bypass_ok = True
                    mark_id_used(guild.id, author.id)
            else:
                await interaction.response.send_message("❌ Ungültige ID.", ephemeral=True)
                return

        if limits["bans"] >= DAILY_BAN_LIMIT and not bypass_ok:
            await interaction.response.send_message("⚠️ Ban-Limit erreicht.", ephemeral=True)
            return
        try:
            user_id = int(self.user.value.strip("<@!>"))
            member = guild.get_member(user_id)
            if not member:
                await interaction.response.send_message("❌ Nutzer nicht gefunden.", ephemeral=True)
                return
            await member.ban(reason=f"Gebannt durch {author}")
            if not bypass_ok:
                increment_limit(guild.id, author.id, "bans")
            await interaction.response.send_message(f"✅ {member.mention} wurde gebannt.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# --- Startup ---
@bot.event
async def on_ready():
    init_db()
    await tree.sync()
    print(f"✅ Eingeloggt als {bot.user}")
    bot.loop.create_task(daily_reset_loop())

# --- Start ---
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ Fehler: Umgebungsvariable DISCORD_TOKEN fehlt.")
    else:
        bot.run(token)