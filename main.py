import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time

CONFIG_FILE = "config.json"
COOLDOWN_SECONDS = 60

# -------------------------------------------------
# CONFIG HANDLING
# -------------------------------------------------
def load_config():
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

# Cooldown storage
user_cooldowns = {}

# -------------------------------------------------
# PERMISSION CHECK
# -------------------------------------------------
def admin_only(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.manage_guild
    )

# -------------------------------------------------
# MODAL
# -------------------------------------------------
class PanicModal(discord.ui.Modal, title="🚨 Panic Alarm"):
    roblox_user = discord.ui.TextInput(
        label="Your Roblox Username",
        placeholder="Enter your Roblox username",
        required=True,
        max_length=100
    )

    location = discord.ui.TextInput(
        label="Your Location",
        placeholder="Where are you currently?",
        required=True,
        max_length=100
    )

    extra_info = discord.ui.TextInput(
        label="Additional Information (Optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        now = time.time()
        last_used = user_cooldowns.get(interaction.user.id, 0)

        if now - last_used < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - (now - last_used))
            await interaction.response.send_message(
                f"You must wait **{remaining}s** before creating another panic alarm.",
                ephemeral=True
            )
            return

        user_cooldowns[interaction.user.id] = now

        config = load_config()
        channel_id = config.get("panic_channel_id")
        role_id = config.get("panic_role_id")

        if not channel_id or not role_id:
            await interaction.response.send_message(
                "Panic system is not fully configured.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(channel_id)
        role = interaction.guild.get_role(role_id)

        if not channel or not role:
            await interaction.response.send_message(
                "Configured channel or role no longer exists.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🚨 Panic Alarm! 🚨",
            color=discord.Color.red()
        )
        embed.add_field(
            name="User",
            value=f"{interaction.user.mention} has created a panic alarm.",
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
            value=self.extra_info.value if self.extra_info.value else "No additional information provided.",
            inline=False
        )

        await channel.send(content=role.mention)
        await channel.send(embed=embed)

        await interaction.response.send_message(
            "Your panic alarm has been sent successfully. Help is on the way.",
            ephemeral=True
        )

# -------------------------------------------------
# BUTTON VIEW
# -------------------------------------------------
class PanicView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🚨 Create Panic Alarm",
        style=discord.ButtonStyle.danger
    )
    async def panic_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(PanicModal())

# -------------------------------------------------
# SLASH COMMANDS (ADMIN ONLY)
# -------------------------------------------------
@bot.tree.command(name="pick-panic-channel", description="Set the channel for panic alarms")
@app_commands.describe(channel="Channel where panic alarms will be sent")
async def pick_panic_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):
    if not admin_only(interaction):
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )
        return

    config = load_config()
    config["panic_channel_id"] = channel.id
    save_config(config)

    await interaction.response.send_message(
        f"Panic channel set to {channel.mention}",
        ephemeral=True
    )

@bot.tree.command(name="pick-panic-role", description="Set the role to ping during panic alarms")
@app_commands.describe(role="Role to be mentioned for panic alarms")
async def pick_panic_role(
    interaction: discord.Interaction,
    role: discord.Role
):
    if not admin_only(interaction):
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )
        return

    config = load_config()
    config["panic_role_id"] = role.id
    save_config(config)

    await interaction.response.send_message(
        f"Panic role set to {role.mention}",
        ephemeral=True
    )

@bot.tree.command(name="create-panic-button", description="Create the panic button embed")
async def create_panic_button(interaction: discord.Interaction):
    if not admin_only(interaction):
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🚨 Panic Button 🚨",
        description=(
            "**Are you on an EH server and require immediate assistance?**\n\n"
            "Press the button below to create a panic alarm. "
            "Our team will be notified instantly and respond as fast as possible."
        ),
        color=discord.Color.red()
    )

    await interaction.channel.send(
        embed=embed,
        view=PanicView()
    )

    await interaction.response.send_message(
        "Panic button successfully created.",
        ephemeral=True
    )

# -------------------------------------------------
# EVENTS
# -------------------------------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    bot.add_view(PanicView())
    print(f"Bot logged in as {bot.user}")

# -------------------------------------------------
# START
# -------------------------------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
