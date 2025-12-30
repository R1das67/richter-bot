import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time

CONFIG_FILE = "config.json"
APPLICATION_BAN_FILE = "application_bans.json"
COOLDOWN_SECONDS = 60

OWNER_ID = 843180408152784936

# -------------------------------------------------
# CONFIG HANDLING
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

def load_application_bans():
    if not os.path.exists(APPLICATION_BAN_FILE):
        with open(APPLICATION_BAN_FILE, "w") as f:
            json.dump({}, f)
        return {}

    with open(APPLICATION_BAN_FILE, "r") as f:
        return json.load(f)

def save_application_bans(data):
    with open(APPLICATION_BAN_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -------------------------------------------------
# BOT SETUP
# -------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
user_cooldowns = {}

# -------------------------------------------------
# PERMISSION CHECKS
# -------------------------------------------------
def admin_only(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_roles

def owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

# -------------------------------------------------
# PANIC MODAL
# -------------------------------------------------
class PanicModal(discord.ui.Modal, title="🚨 Panic Alarm"):
    roblox_user = discord.ui.TextInput(label="Your Roblox Username", required=True)
    location = discord.ui.TextInput(label="Your Location", required=True)
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

        embed = discord.Embed(title="🚨 Panic Alarm! 🚨", color=discord.Color.red())
        embed.add_field(name="User", value=interaction.user.mention, inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_user.value, inline=False)
        embed.add_field(name="Location", value=self.location.value, inline=False)
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
# PANIC VIEW
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
# PANIC COMMANDS (OWNER ONLY)
# -------------------------------------------------
@bot.tree.command(name="pick-panic-channel")
@app_commands.check(owner_only)
async def pick_panic_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config = load_config()
    config["panic_channel_id"] = channel.id
    save_config(config)

    await interaction.response.send_message(
        f"Panic channel set to {channel.mention}",
        ephemeral=True
    )

@bot.tree.command(name="pick-panic-role")
@app_commands.check(owner_only)
async def pick_panic_role(interaction: discord.Interaction, role: discord.Role):
    config = load_config()
    config["panic_role_id"] = role.id
    save_config(config)

    await interaction.response.send_message(
        f"Panic role set to {role.mention}",
        ephemeral=True
    )

@bot.tree.command(name="create-panic-button")
@app_commands.check(owner_only)
async def create_panic_button(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🚨 Panic Button 🚨",
        description="Press the button below to alert our team instantly.",
        color=discord.Color.red()
    )

    await interaction.channel.send(embed=embed, view=PanicView())
    await interaction.response.send_message("Panic button created.", ephemeral=True)

# -------------------------------------------------
# EMBED COMMAND (ADMIN ONLY)
# -------------------------------------------------
@bot.tree.command(name="send-embed", description="Send an embed message to a channel")
@app_commands.default_permissions(administrator=True)
async def send_embed(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    description: str,
    color: str = "red",
    thumbnail_url: str | None = None,
    image_url_top: str | None = None,
    image_url_bottom: str | None = None
):
    try:
        embed_color = int(color.replace("#", ""), 16)
    except ValueError:
        embed_color = discord.Color.red().value

    embed = discord.Embed(
        title=title,
        description=description,
        color=embed_color
    )

    if image_url_top:
        embed.set_image(url=image_url_top)  # Bild oben über Titel
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    await channel.send(embed=embed)

    # Wenn unten Bild gesetzt ist, zweiten Embed direkt darunter senden
    if image_url_bottom:
        embed_bottom = discord.Embed(color=embed_color)
        embed_bottom.set_image(url=image_url_bottom)
        await channel.send(embed=embed_bottom)

    await interaction.response.send_message(
        f"Embed sent to {channel.mention}",
        ephemeral=True
    )

# -------------------------------------------------
# APPLICATION BAN COMMANDS (ADMIN)
# -------------------------------------------------
@bot.tree.command(name="add-application-ban")
async def add_application_ban(
    interaction: discord.Interaction,
    user_id: str,
    role: discord.Role
):
    if not admin_only(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    bans = load_application_bans()
    bans[str(user_id)] = role.id
    save_application_bans(bans)

    member = interaction.guild.get_member(int(user_id))
    if member:
        await member.add_roles(role)

    await interaction.response.send_message(
        f"User `{user_id}` received application ban role `{role.name}`.",
        ephemeral=True
    )

@bot.tree.command(name="remove-application-ban")
async def remove_application_ban(interaction: discord.Interaction, user_id: str):
    if not admin_only(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    bans = load_application_bans()
    role_id = bans.pop(str(user_id), None)
    save_application_bans(bans)

    member = interaction.guild.get_member(int(user_id))
    if member and role_id:
        role = interaction.guild.get_role(role_id)
        if role:
            await member.remove_roles(role)

    await interaction.response.send_message(
        f"Application ban removed for `{user_id}`.",
        ephemeral=True
    )

@bot.tree.command(name="show-application-ban-list")
async def show_application_ban_list(interaction: discord.Interaction):
    if not admin_only(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    bans = load_application_bans()
    if not bans:
        await interaction.response.send_message(
            "No application banned users.",
            ephemeral=True
        )
        return

    lines = []
    for uid, role_id in bans.items():
        member = interaction.guild.get_member(int(uid))
        role = interaction.guild.get_role(role_id)
        name = member.display_name if member else "Unknown User"
        role_name = role.name if role else "Unknown Role"
        lines.append(f"{name} — `{uid}` — {role_name}")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)

# -------------------------------------------------
# EVENTS
# -------------------------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    bans = load_application_bans()
    role_id = bans.get(str(member.id))
    if role_id:
        role = member.guild.get_role(role_id)
        if role:
            await member.add_roles(role)

@bot.event
async def on_ready():
    load_config()
    bot.add_view(PanicView())
    await bot.tree.sync()
    print(f"Logged in als {bot.user}")

# -------------------------------------------------
# START
# -------------------------------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
