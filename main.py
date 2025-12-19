import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time

CONFIG_FILE = "config.json"
COOLDOWN_SECONDS = 60

# -------------------------------------------------
# CONFIG HANDLING (SAFE)
# -------------------------------------------------
def load_config():
    if not os.path.exists(CONFIG_FILE):
        default = {
            "panic_channel_id": None,
            "panic_role_id": None
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(default, f, indent=4)
        return default

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -------------------------------------------------
# BOT SETUP
# -------------------------------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}

# -------------------------------------------------
# PERMISSION CHECK
# -------------------------------------------------
def admin_only(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild

# -------------------------------------------------
# MODAL
# -------------------------------------------------
class PanicModal(discord.ui.Modal, title="🚨 Panic Alarm"):
    roblox_user = discord.ui.TextInput(
        label="Your Roblox Username",
        required=True
    )
    location = discord.ui.TextInput(
        label="Your Location",
        required=True
    )
    extra_info = discord.ui.TextInput(
        label="Additional Information (Optional)",
        style=discord.TextStyle.paragraph,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        now = time.time()
        last = user_cooldowns.get(interaction.user.id, 0)

        if now - last < COOLDOWN_SECONDS:
            await interaction.response.send_message(
                "Please wait **1 minute** before using the panic button again.",
                ephemeral=True
            )
            return

        user_cooldowns[interaction.user.id] = now

        config = load_config()
        channel = interaction.guild.get_channel(config["panic_channel_id"])
        role = interaction.guild.get_role(config["panic_role_id"])

        if not channel or not role:
            await interaction.response.send_message(
                "Panic system is not configured correctly.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🚨 Panic Alarm! 🚨",
            color=discord.Color.red()
        )
        embed.add_field(
            name="User",
            value=interaction.user.mention,
            inline=False
        )
        embed.add_field(
            name="Roblox Username",
            value=self.roblox_user.value,
            inline=False
        )
        embed.add_field(
            name="Location",
            value=self.location.value,
            inline=False
        )
        embed.add_field(
            name="Additional Information",
            value=self.extra_info.value or "None",
            inline=False
        )

        await channel.send(content=role.mention)
        await channel.send(embed=embed)

        await interaction.response.send_message(
            "Panic alarm sent successfully.",
            ephemeral=True
        )

# -------------------------------------------------
# BUTTON VIEW (PERSISTENT)
# -------------------------------------------------
class PanicView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🚨 Create Panic Alarm",
        style=discord.ButtonStyle.danger,
        custom_id="panic_button"
    )
    async def panic_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PanicModal())

# -------------------------------------------------
# SLASH COMMANDS (ADMIN ONLY)
# -------------------------------------------------
@bot.tree.command(name="pick-panic-channel")
async def pick_panic_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not admin_only(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    config = load_config()
    config["panic_channel_id"] = channel.id
    save_config(config)

    await interaction.response.send_message(
        f"Panic channel set to {channel.mention}",
        ephemeral=True
    )

@bot.tree.command(name="pick-panic-role")
async def pick_panic_role(interaction: discord.Interaction, role: discord.Role):
    if not admin_only(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    config = load_config()
    config["panic_role_id"] = role.id
    save_config(config)

    await interaction.response.send_message(
        f"Panic role set to {role.mention}",
        ephemeral=True
    )

@bot.tree.command(name="create-panic-button")
async def create_panic_button(interaction: discord.Interaction):
    if not admin_only(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🚨 Panic Button 🚨",
        description=(
            "**Need immediate help on an EH server?**\n\n"
            "Press the button below to alert our team instantly."
        ),
        color=discord.Color.red()
    )

    await interaction.channel.send(embed=embed, view=PanicView())
    await interaction.response.send_message("Panic button created.", ephemeral=True)

# -------------------------------------------------
# EVENTS
# -------------------------------------------------
@bot.event
async def on_ready():
    load_config()
    bot.add_view(PanicView())
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

# -------------------------------------------------
# START
# -------------------------------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
