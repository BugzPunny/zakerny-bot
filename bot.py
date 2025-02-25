import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime
import sqlite3
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

# --------------------------------------
# Simple HTTP server for health checks
# --------------------------------------

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write("🕌 Bot is running! فَذَكِّرْ إِنْ نَفَعَتِ الذِّكْرَى".encode("utf-8"))

def run_http_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthCheckHandler)
    print("Starting health check server on port 8000...")
    server.serve_forever()

# Start the HTTP server in a separate thread
http_server_thread = Thread(target=run_http_server, daemon=True)
http_server_thread.start()

# --------------------------------------
# Your existing bot code starts below
# --------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

SUPPORTED_COUNTRIES = {
    "Egypt": "Cairo",
    "Saudi Arabia": "Riyadh",
    "Turkey": "Istanbul",
    "UAE": "Dubai",
    "Malaysia": "Kuala Lumpur",
    "Indonesia": "Jakarta",
    "Pakistan": "Karachi",
    "UK": "London",
    "USA": "New York",
    "Canada": "Toronto"
}

# Prayers to exclude from notifications and /zakerny
EXCLUDED_PRAYERS = ["Midnight", "Firstthird", "Lastthird"]

DATABASE_URL = "zakerny.db"

def init_db():
    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        # Create servers table with message_id column
        c.execute('''CREATE TABLE IF NOT EXISTS servers 
                     (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, message_id INTEGER)''')
        # Create users table
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (user_id INTEGER, guild_id INTEGER, country TEXT, activated BOOLEAN,
                      PRIMARY KEY (user_id, guild_id))''')
        conn.commit()

init_db()

def get_prayer_times(city, country):
    url = f"http://api.aladhan.com/v1/timingsByCity?city={city}&country={country}&method=5"
    response = requests.get(url)
    data = response.json()
    if data["code"] == 200:
        return data["data"]["timings"]
    return None

def convert_to_12_hour(time_24h):
    try:
        time_obj = datetime.strptime(time_24h, "%H:%M")
        return time_obj.strftime("%I:%M %p")
    except ValueError:
        return time_24h

class CountrySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=country, value=country) for country in SUPPORTED_COUNTRIES]
        super().__init__(placeholder="Select your country...", options=options)

    async def callback(self, interaction: discord.Interaction):
        country = self.values[0]
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        # Create or get the country-specific role (e.g., Egypt_Prayer_Times)
        times_role_name = f"{country}_Prayer_Times"
        times_role = discord.utils.get(interaction.guild.roles, name=times_role_name)
        if not times_role:
            try:
                times_role = await interaction.guild.create_role(name=times_role_name, mentionable=True)
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to create roles.", ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.response.send_message("Failed to create the role.", ephemeral=True)
                return

        # Remove any existing country-specific roles
        for existing_role in interaction.user.roles:
            if "_Prayer_Times" in existing_role.name:
                await interaction.user.remove_roles(existing_role)

        # Add the new country-specific role
        await interaction.user.add_roles(times_role)
        await interaction.response.send_message(f"You've selected **{country}** for prayer times!", ephemeral=True)

        # Update the database (reset activation status)
        with sqlite3.connect(DATABASE_URL) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO users (user_id, guild_id, country, activated) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET country = ?, activated = ?",
                (user_id, guild_id, country, False, country, False)  # Reset activation on country change
            )
            conn.commit()

class CountryView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(CountrySelect())

class ActivateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Activate", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        try:
            user_id = interaction.user.id
            guild_id = interaction.guild.id

            # Check if the user has selected a country
            with sqlite3.connect(DATABASE_URL) as conn:
                c = conn.cursor()
                c.execute("SELECT country, activated FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
                result = c.fetchone()

            if result is None:
                await interaction.response.send_message(
                    "You must select a country using `/countries` first.",
                    ephemeral=True)
                return

            country = result[0]
            activated = not result[1] if result[1] is not None else True

            # Create or get the country-specific Prayer_Pings role
            pings_role_name = f"{country}_Prayer_Pings"
            pings_role = discord.utils.get(interaction.guild.roles, name=pings_role_name)
            if not pings_role:
                try:
                    pings_role = await interaction.guild.create_role(name=pings_role_name, mentionable=True)
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "I don't have permission to create roles. Please check my permissions.",
                        ephemeral=True)
                    return
                except discord.HTTPException:
                    await interaction.response.send_message(
                        "Failed to create the role. Please try again later.",
                        ephemeral=True)
                    return

            # Toggle the Prayer_Pings role
            if activated:
                await interaction.user.add_roles(pings_role)
            else:
                await interaction.user.remove_roles(pings_role)

            # Update activation status in the database
            with sqlite3.connect(DATABASE_URL) as conn:
                c = conn.cursor()
                c.execute(
                    "UPDATE users SET activated = ? WHERE user_id = ? AND guild_id = ?",
                    (activated, user_id, guild_id)
                )
                conn.commit()

            status = "activated" if activated else "deactivated"
            await interaction.response.send_message(
                f"Notifications have been **{status}** for **{country}** in this server.",
                ephemeral=True)
        except Exception as e:
            print(f"Error in ActivateButton callback: {e}")
            await interaction.response.send_message(
                "An error occurred. Please try again later.",
                ephemeral=True)

class ActivateView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(ActivateButton())

@bot.tree.command(name="countries", description="Select your country to get prayer time notifications.")
async def countries(interaction: discord.Interaction):
    view = CountryView()
    await interaction.response.send_message("Please select your country:", view=view, ephemeral=True)

@bot.tree.command(name="zakerny", description="Display prayer times for your selected country.")
async def zakerny(interaction: discord.Interaction):
    user_id = interaction.user.id
    guild_id = interaction.guild.id

    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        c.execute("SELECT country FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        result = c.fetchone()

    if result is None:
        await interaction.response.send_message(
            "You haven't selected a country yet. Use `/countries` to select your country.",
            ephemeral=True)
        return

    country = result[0]
    city = SUPPORTED_COUNTRIES[country]

    prayer_times = get_prayer_times(city, country)

    if prayer_times:
        # Filter out excluded prayers
        filtered_prayers = {prayer: time for prayer, time in prayer_times.items() 
                          if prayer not in EXCLUDED_PRAYERS}
        
        embed = discord.Embed(
            title=f"Prayer Times for {city}, {country} 🕌",
            description="Here are the prayer times for today:",
            color=discord.Color.blue())
        
        # Add filtered fields
        for prayer, time in filtered_prayers.items():
            embed.add_field(name=prayer, value=convert_to_12_hour(time), inline=True)
        
        embed.set_footer(text="فَذَكِّرْ إِنْ نَفَعَتِ الذِّكْرَى")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(
            "Failed to fetch prayer times. Please try again later.",
            ephemeral=True)

@bot.tree.command(name="setup-prayer-channel", description="Create a prayer times notification channel.")
async def setup_prayer_channel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You must be an administrator to use this command.",
            ephemeral=True)
        return

    guild = interaction.guild
    guild_id = guild.id

    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        c.execute("SELECT channel_id, message_id FROM servers WHERE guild_id = ?", (guild_id,))
        result = c.fetchone()

    if result:
        channel_id, message_id = result
        channel = guild.get_channel(channel_id)
        if channel:
            await interaction.response.send_message(
                f"Notification channel already exists: {channel.mention}",
                ephemeral=True
            )
            return
        else:
            with sqlite3.connect(DATABASE_URL) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM servers WHERE guild_id = ?", (guild_id,))
                conn.commit()

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    try:
        channel = await guild.create_text_channel(
            name="prayer-times",
            overwrites=overwrites,
            reason="Prayer time notifications"
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I don't have permission to create channels. Please check my permissions.",
            ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.response.send_message(
            "Failed to create the notification channel. Please try again later.",
            ephemeral=True
        )
        return

    view = ActivateView()
    message = await channel.send("Click the button below to activate/deactivate prayer time notifications:\n**Note:** You must select a country using `/countries` to receive notifications.", view=view)

    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO servers (guild_id, channel_id, message_id) VALUES (?, ?, ?)",
            (guild_id, channel.id, message.id)
        )
        conn.commit()

    await interaction.response.send_message(
        f"Notification channel created: {channel.mention}",
        ephemeral=True
    )

@bot.tree.command(name="removerole", description="Remove your country role to stop receiving pings.")
async def removerole(interaction: discord.Interaction):
    user_id = interaction.user.id
    guild_id = interaction.guild.id

    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        c.execute("SELECT country FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        result = c.fetchone()

    if result is None:
        await interaction.response.send_message(
            "You don't have a country role to remove.", ephemeral=True)
        return

    country = result[0]
    role_name = f"{country}_Prayer_Times"
    role = discord.utils.get(interaction.guild.roles, name=role_name)

    if role:
        try:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                f"Your **{role_name}** role has been removed.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to remove roles. Please check my permissions.",
                ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message(
                "Failed to remove your role. Please try again later.",
                ephemeral=True)
    else:
        await interaction.response.send_message(
            "Your role doesn't exist anymore.", ephemeral=True)

@bot.tree.command(name="info", description="Display information about all available commands.")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Zakerny Bot Commands 🕌",
        description="Here are all the commands and how to use them:",
        color=discord.Color.blue())
    embed.add_field(
        name="/countries",
        value="Select your country to receive prayer time notifications.",
        inline=False)
    embed.add_field(name="/zakerny",
                    value="Display prayer times for your selected country.",
                    inline=False)
    embed.add_field(name="/removerole",
                    value="Remove your country role to stop receiving pings.",
                    inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tasks.loop(minutes=1)
async def notify_prayer_times():
    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        c.execute("SELECT guild_id, channel_id FROM servers")
        servers = c.fetchall()

        for guild_id, channel_id in servers:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            c.execute("SELECT country FROM users WHERE guild_id = ? AND activated = 1 GROUP BY country", (guild_id,))
            countries = c.fetchall()

            for country_entry in countries:
                country = country_entry[0]
                role_name = f"{country}_Prayer_Pings"
                role = discord.utils.get(guild.roles, name=role_name)

                if not role:
                    try:
                        role = await guild.create_role(name=role_name, mentionable=True)
                    except discord.Forbidden:
                        print(f"Missing permissions to create role in {guild.name}")
                        continue

                city = SUPPORTED_COUNTRIES.get(country)
                prayer_times = get_prayer_times(city, country)
                
                if prayer_times:
                    current_time = datetime.now().strftime("%H:%M")
                    # Filter out excluded prayers
                    filtered_prayers = {prayer: time for prayer, time in prayer_times.items() 
                                       if prayer not in EXCLUDED_PRAYERS}
                    
                    for prayer, time in filtered_prayers.items():
                        if current_time == time:
                            await channel.send(
                                f"{role.mention} It's time for **{prayer}**! ⏰",
                                allowed_mentions=discord.AllowedMentions(roles=True)
                            )

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")
    notify_prayer_times.start()

    # Re-attach the view to the message in the notification channel
    with sqlite3.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        c.execute("SELECT guild_id, channel_id, message_id FROM servers")
        servers = c.fetchall()

        for guild_id, channel_id, message_id in servers:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            try:
                message = await channel.fetch_message(message_id)
                view = ActivateView()
                await message.edit(content=message.content, view=view)
            except discord.NotFound:
                print(f"Message with ID {message_id} not found in channel {channel_id} in guild {guild_id}")
            except discord.Forbidden:
                print(f"Missing permissions to fetch or edit message in channel {channel_id} in guild {guild_id}")
            except discord.HTTPException as e:
                print(f"Failed to re-attach view to message in channel {channel_id} in guild {guild_id}: {e}")

    await bot.tree.sync()

TOKEN = os.getenv('TOKEN')
if not TOKEN:
    print("Error: Discord token not found in environment variables!")
    exit(1)

bot.run(TOKEN)
