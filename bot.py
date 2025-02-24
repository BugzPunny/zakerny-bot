import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime
import sqlite3
import os

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

DATABASE_URL = "zakerny.db"

def init_db():
    conn = sqlite3.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS servers 
                 (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER, guild_id INTEGER, country TEXT, activated BOOLEAN,
                  PRIMARY KEY (user_id, guild_id))''')
    conn.commit()
    conn.close()

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

        role_name = f"{country} Subscriber"
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            try:
                role = await interaction.guild.create_role(name=role_name, mentionable=True)
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to create roles.", ephemeral=True)
                return
            except discord.HTTPException:
                await interaction.response.send_message("Failed to create the role.", ephemeral=True)
                return

        for existing_role in interaction.user.roles:
            if "Subscriber" in existing_role.name:
                await interaction.user.remove_roles(existing_role)

        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"You'll now receive **{country}** prayer time notifications!", ephemeral=True)

        conn = sqlite3.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (user_id, guild_id, country, activated) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (user_id, guild_id) DO UPDATE SET country = ?, activated = ?",
            (user_id, guild_id, country, True, country, True)
        )
        conn.commit()
        conn.close()

class CountryView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(CountrySelect())

class ActivateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Activate", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        conn = sqlite3.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("SELECT country, activated FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        result = c.fetchone()
        conn.close()

        if result is None:
            await interaction.response.send_message(
                "You must select a country using `/countries` first.",
                ephemeral=True)
            return

        country = result[0]
        activated = not result[1] if result[1] is not None else True  # Default to True if no record exists

        conn = sqlite3.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute(
            "UPDATE users SET activated = ? WHERE user_id = ? AND guild_id = ?",
            (activated, user_id, guild_id)
        )
        conn.commit()
        conn.close()

        status = "activated" if activated else "deactivated"
        await interaction.response.send_message(
            f"Notifications have been **{status}** for **{country}** in this server.",
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

    conn = sqlite3.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute("SELECT country FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
    result = c.fetchone()
    conn.close()

    if result is None:
        await interaction.response.send_message(
            "You haven't selected a country yet. Use `/countries` to select your country.",
            ephemeral=True)
        return

    country = result[0]
    city = SUPPORTED_COUNTRIES[country]

    prayer_times = get_prayer_times(city, country)

    if prayer_times:
        embed = discord.Embed(
            title=f"Prayer Times for {city}, {country} 🕌",
            description="Here are the prayer times for today:",
            color=discord.Color.blue())
        embed.add_field(name="Fajr", value=convert_to_12_hour(prayer_times["Fajr"]), inline=True)
        embed.add_field(name="Sunrise", value=convert_to_12_hour(prayer_times["Sunrise"]), inline=True)
        embed.add_field(name="Dhuhr", value=convert_to_12_hour(prayer_times["Dhuhr"]), inline=True)
        embed.add_field(name="Asr", value=convert_to_12_hour(prayer_times["Asr"]), inline=True)
        embed.add_field(name="Maghrib", value=convert_to_12_hour(prayer_times["Maghrib"]), inline=True)
        embed.add_field(name="Isha", value=convert_to_12_hour(prayer_times["Isha"]), inline=True)
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

    conn = sqlite3.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute("SELECT channel_id FROM servers WHERE guild_id = ?", (guild_id,))
    result = c.fetchone()
    conn.close()

    if result:
        channel_id = result[0]
        channel = guild.get_channel(channel_id)
        if channel:
            await interaction.response.send_message(
                f"Notification channel already exists: {channel.mention}",
                ephemeral=True
            )
            return
        else:
            conn = sqlite3.connect(DATABASE_URL)
            c = conn.cursor()
            c.execute("DELETE FROM servers WHERE guild_id = ?", (guild_id,))
            conn.commit()
            conn.close()

    # Create the notification channel with restricted permissions
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

    # Store the channel ID in the database
    conn = sqlite3.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute(
        "INSERT INTO servers (guild_id, channel_id) VALUES (?, ?)",
        (guild_id, channel.id)
    )
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"Notification channel created: {channel.mention}",
        ephemeral=True
    )

    # Send the activation button to the new channel
    view = ActivateView()
    await channel.send(
        "Click the button below to activate/deactivate prayer time notifications:\n"
        "**Note:** You must select a country using `/countries` to receive notifications.",
        view=view
    )

@bot.tree.command(name="removerole", description="Remove your country role to stop receiving pings.")
async def removerole(interaction: discord.Interaction):
    user_id = interaction.user.id
    guild_id = interaction.guild.id

    conn = sqlite3.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute("SELECT country FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
    result = c.fetchone()
    conn.close()

    if result is None:
        await interaction.response.send_message(
            "You don't have a country role to remove.", ephemeral=True)
        return

    country = result[0]
    role_name = f"{country} Subscriber"
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
    embed.add_field(
        name="/activate",
        value="Activate/deactivate notifications.",
        inline=False)
    embed.add_field(name="/removerole",
                    value="Remove your country role to stop receiving pings.",
                    inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tasks.loop(minutes=1)
async def notify_prayer_times():
    conn = sqlite3.connect(DATABASE_URL)
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
            role_name = f"{country} Subscriber"
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
                for prayer, time in prayer_times.items():
                    if current_time == time:
                        await channel.send(
                            f"{role.mention} It's time for **{prayer}**! ⏰",
                            allowed_mentions=discord.AllowedMentions(roles=True)
                        )
    conn.close()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")
    notify_prayer_times.start()
    await bot.tree.sync()

TOKEN = os.getenv('TOKEN')
if not TOKEN:
    print("Error: Token not found in environment variables!")
    exit(1)
bot.run(TOKEN)
