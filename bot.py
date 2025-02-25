import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime, timedelta
import sqlite3
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

# --------------------------------------
# Configuration
# --------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

SUPPORTED_COUNTRIES = {
    "Egypt": "Cairo",
    "Saudi Arabia": "Riyadh",
    # ... keep other countries ...
}

EXCLUDED_PRAYERS = ["Midnight", "Firstthird", "Lastthird"]
DATABASE_URL = "zakerny.db"
CLEANUP_AFTER_ISHA = True
MAX_PINGS_TO_KEEP = 5

# --------------------------------------
# Database Setup
# --------------------------------------
def init_db():
    with sqlite3.connect(DATABASE_URL) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS servers 
                      (guild_id INTEGER PRIMARY KEY, 
                       channel_id INTEGER, 
                       message_id INTEGER)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER, 
                       guild_id INTEGER, 
                       country TEXT, 
                       activated BOOLEAN,
                       PRIMARY KEY (user_id, guild_id))''')

init_db()

# --------------------------------------
# Core Functionality (Fixed)
# --------------------------------------
class PersistentActivateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ActivateButton())

    async def on_error(self, interaction, error, item):
        print(f"View Error: {error}")

class ActivateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Activate", 
                        style=discord.ButtonStyle.green,
                        custom_id="persistent_activate")

    async def callback(self, interaction: discord.Interaction):
        # ... (keep existing activation logic but add):
        await interaction.response.defer()
        
        # Verify role assignment
        try:
            await interaction.user.add_roles(pings_role)
            print(f"Assigned {pings_role.name} to {interaction.user}")
        except Exception as e:
            print(f"Role assignment failed: {e}")

# --------------------------------------
# Critical Fixes in Key Areas
# --------------------------------------
@bot.event
async def on_ready():
    # Register persistent view
    bot.add_view(PersistentActivateView())
    
    # Restore button messages
    with sqlite3.connect(DATABASE_URL) as conn:
        for guild_id, channel_id, message_id in conn.execute("SELECT * FROM servers"):
            try:
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.get_partial_message(message_id).edit(view=PersistentActivateView())
            except Exception as e:
                print(f"Failed to restore buttons: {e}")
                
    await bot.tree.sync()
    print("Bot ready with persistent buttons!")

@tasks.loop(minutes=1)
async def notify_prayer_times():
    # Fixed ping logic
    for guild in bot.guilds:
        with sqlite3.connect(DATABASE_URL) as conn:
            # Get server settings
            server = conn.execute("SELECT channel_id, message_id FROM servers WHERE guild_id = ?", 
                                (guild.id,)).fetchone()
            if not server:
                continue

            # Get active users
            users = conn.execute("SELECT country FROM users WHERE guild_id = ? AND activated = 1",
                                (guild.id,)).fetchall()
            
            # Process prayer times
            channel = guild.get_channel(server[0])
            if not channel:
                continue

            for country in {u[0] for u in users}:
                city = SUPPORTED_COUNTRIES.get(country)
                times = get_prayer_times(city, country)
                
                if times and "Isha" in times:
                    current_time = datetime.now().strftime("%H:%M")
                    if current_time == times["Isha"]:
                        await send_ping(channel, country, "Isha")
                        if CLEANUP_AFTER_ISHA:
                            await clean_channel(channel, server[1])

async def send_ping(channel, country, prayer):
    role = discord.utils.get(channel.guild.roles, name=f"{country}_Prayer_Pings")
    if not role:
        try:
            role = await channel.guild.create_role(name=f"{country}_Prayer_Pings",
                                                 mentionable=True)
        except Exception as e:
            print(f"Role creation failed: {e}")
            return

    try:
        await channel.send(
            f"{role.mention} It's time for **{prayer}**!",
            allowed_mentions=discord.AllowedMentions(roles=True)
        )
    except Exception as e:
        print(f"Ping failed: {e}")

async def clean_channel(channel, keep_message_id):
    try:
        to_delete = []
        async for msg in channel.history(limit=200):
            if msg.id == keep_message_id:
                continue
            if len(to_delete) < MAX_PINGS_TO_KEEP and "It's time for" in msg.content:
                continue
            to_delete.append(msg)
        
        await channel.delete_messages(to_delete)
    except Exception as e:
        print(f"Cleanup failed: {e}")

# --------------------------------------
# Setup Command (Revised)
# --------------------------------------
@bot.tree.command(name="setup-prayer-channel")
async def setup_prayer_channel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Administrator required", ephemeral=True)

    # Create or update channel
    try:
        channel = await interaction.guild.create_text_channel(
            name="prayer-times",
            overwrites={
                interaction.guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True
                )
            }
        )
    except discord.Forbidden:
        return await interaction.response.send_message("🔒 Missing permissions!", ephemeral=True)

    # Send persistent button
    view = PersistentActivateView()
    msg = await channel.send("**Activate Notifications**", view=view)
    
    # Update database
    with sqlite3.connect(DATABASE_URL) as conn:
        conn.execute("INSERT OR REPLACE INTO servers VALUES (?, ?, ?)",
                    (interaction.guild.id, channel.id, msg.id))
    
    await interaction.response.send_message(f"✅ Channel ready: {channel.mention}", ephemeral=True)

# --------------------------------------
# Run Bot
# --------------------------------------
if __name__ == "__main__":
    # Health server and bot run
    Thread(target=run_http_server, daemon=True).start()
    bot.run(os.getenv('TOKEN'))
