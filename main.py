import os
import discord
from discord.ext import commands
from discord import app_commands
import json

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN nicht gesetzt!")

DATA_FILE = "bot_data.json"

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
    "panic_role": None
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
# BOT READY
# -----------------------------
@bot.event
async def on_ready():
    bot.add_view(PanicButtonView())
    await bot.tree.sync()
    print(f"Bot ist online als {bot.user}")

bot.run(TOKEN)
