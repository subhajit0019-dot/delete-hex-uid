import os
import aiohttp
import discord
import sqlite3
import time
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import config

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or getattr(config, "DISCORD_BOT_TOKEN", "MTU2Mzg0NTI2MDQ3NDMxODk1OA.GUnhC2.mFvPEY5hdl5nGkaVLiUD3hU79R3LUzS1IzhKF0")
ADMIN_IDS = [id.strip() for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()] or getattr(config, "ADMIN_IDS", ["1535215246015340624"])

# API Configuration from tracked config module with env overrides
API_KEY = config.API_KEY
API_URL = config.API_URL
API_ACTION_ADD = getattr(config, "API_ACTION_ADD", "add")
API_ACTION_EDIT = getattr(config, "API_ACTION_EDIT", "change_uid")
API_ACTION_DELETE = getattr(config, "API_ACTION_DELETE", "delete")

# Check required environment variables
if not TOKEN:
    print("[-] DISCORD_TOKEN is missing. Bot daemon is idle.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "database.db")))
MAX_SAFE_TIMESTAMP = 253402300799  # 9999-12-31 23:59:59 UTC

def format_utc_timestamp(value, date_only=False):
    """Format Unix timestamps safely, including lifetime-sized reseller grants."""
    try:
        timestamp = int(value)
        if timestamp > MAX_SAFE_TIMESTAMP:
            return "LIFETIME"
        pattern = '%Y-%m-%d' if date_only else '%Y-%m-%d %H:%M:%S'
        return time.strftime(pattern, time.gmtime(timestamp))
    except (TypeError, ValueError, OverflowError, OSError):
        return "EXTENDED ACCESS"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resellers (
            discord_id TEXT PRIMARY KEY,
            credits INTEGER DEFAULT 0,
            expiry_timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS free_claims (
            discord_id TEXT PRIMARY KEY,
            last_claim_timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registered_uids (
            uid TEXT PRIMARY KEY,
            discord_id TEXT,
            added_timestamp INTEGER,
            expiry_days INTEGER,
            claim_type TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_registered_uid(uid: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT uid, discord_id, added_timestamp, expiry_days, claim_type FROM registered_uids WHERE uid = ?", (str(uid),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"uid": row[0], "discord_id": row[1], "added_timestamp": row[2], "expiry_days": row[3], "claim_type": row[4]}
    return None

# Database Helper Functions
def add_registered_uid(uid: str, discord_id: str, expiry_days: int, claim_type: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    current_time = int(time.time())
    cursor.execute("""
        INSERT INTO registered_uids (uid, discord_id, added_timestamp, expiry_days, claim_type)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(uid) DO UPDATE SET
            discord_id = excluded.discord_id,
            added_timestamp = excluded.added_timestamp,
            expiry_days = excluded.expiry_days,
            claim_type = excluded.claim_type
    """, (str(uid), str(discord_id), current_time, expiry_days, claim_type))
    conn.commit()
    conn.close()

def remove_registered_uid(uid: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM registered_uids WHERE uid = ?", (str(uid),))
    conn.commit()
    conn.close()

def update_registered_uid(old_uid: str, new_uid: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id, added_timestamp, expiry_days, claim_type FROM registered_uids WHERE uid = ?", (str(old_uid),))
    row = cursor.fetchone()
    if row:
        discord_id, added_timestamp, expiry_days, claim_type = row
        cursor.execute("DELETE FROM registered_uids WHERE uid = ?", (str(old_uid),))
        cursor.execute("""
            INSERT INTO registered_uids (uid, discord_id, added_timestamp, expiry_days, claim_type)
            VALUES (?, ?, ?, ?, ?)
        """, (str(new_uid), discord_id, added_timestamp, expiry_days, claim_type))
    conn.commit()
    conn.close()

def list_registered_uids(discord_id: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if discord_id:
        cursor.execute("SELECT uid, discord_id, added_timestamp, expiry_days, claim_type FROM registered_uids WHERE discord_id = ?", (str(discord_id),))
    else:
        cursor.execute("SELECT uid, discord_id, added_timestamp, expiry_days, claim_type FROM registered_uids")
    rows = cursor.fetchall()
    conn.close()
    return [{"uid": r[0], "discord_id": r[1], "added_timestamp": r[2], "expiry_days": r[3], "claim_type": r[4]} for r in rows]

def get_last_claim(discord_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT last_claim_timestamp FROM free_claims WHERE discord_id = ?", (str(discord_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return 0

def set_last_claim(discord_id: str, timestamp: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO free_claims (discord_id, last_claim_timestamp)
        VALUES (?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET last_claim_timestamp = excluded.last_claim_timestamp
    """, (str(discord_id), timestamp))
    conn.commit()
    conn.close()

def get_reseller(discord_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT credits, expiry_timestamp FROM resellers WHERE discord_id = ?", (str(discord_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"credits": row[0], "expiry_timestamp": row[1]}
    return None

def add_or_update_reseller(discord_id: str, credits: int, expiry_timestamp: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO resellers (discord_id, credits, expiry_timestamp)
        VALUES (?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            credits = excluded.credits,
            expiry_timestamp = excluded.expiry_timestamp
    """, (str(discord_id), credits, expiry_timestamp))
    conn.commit()
    conn.close()

def update_reseller_credits(discord_id: str, credits: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE resellers SET credits = ? WHERE discord_id = ?", (credits, str(discord_id)))
    conn.commit()
    conn.close()

def delete_reseller(discord_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM resellers WHERE discord_id = ?", (str(discord_id),))
    conn.commit()
    conn.close()

def list_all_resellers():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id, credits, expiry_timestamp FROM resellers")
    rows = cursor.fetchall()
    conn.close()
    return [{"discord_id": r[0], "credits": r[1], "expiry_timestamp": r[2]} for r in rows]



class UIDBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Register command groups and top level commands
        self.tree.add_command(add_group)
        self.tree.add_command(remove_group)
        self.tree.add_command(edit_group)
        self.tree.add_command(list_group)
        self.tree.add_command(free_command)
        self.tree.add_command(sync_command)
        await self.tree.sync()
        print("Slash command groups synced successfully.")

bot = UIDBot()

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")

@bot.command(name="sync")
async def sync_prefix_command(ctx: commands.Context):
    author_icon = ctx.author.display_avatar.url if ctx.author.avatar else None
    if not await is_admin(ctx.author):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="This command is restricted to administrative operators.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {ctx.author.name}", icon_url=author_icon)
        await ctx.send(embed=embed)
        return

    try:
        # Sync globally
        await bot.tree.sync()
        # Sync to current guild (server) instantly
        if ctx.guild:
            bot.tree.copy_global_to(guild=ctx.guild)
            await bot.tree.sync(guild=ctx.guild)
            desc = f"All slash commands have been synced globally and registered instantly to `{ctx.guild.name}`."
        else:
            desc = "All slash commands have been synced globally."

        embed = discord.Embed(
            title="🔥 Commands Synced",
            description=desc,
            color=0xFF0000
        )
        embed.set_author(name=f"Executed by {ctx.author.name}", icon_url=author_icon)
        embed.set_footer(text="Command Registry Synced")
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Sync Failed",
            description=f"An error occurred while syncing: `{str(e)}`",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {ctx.author.name}", icon_url=author_icon)
        await ctx.send(embed=embed)

async def is_admin(user: discord.User) -> bool:
    """Check if the user is an admin or the application owner."""
    if str(user.id) in ADMIN_IDS:
        return True
    try:
        return await bot.is_owner(user)
    except Exception:
        return False

async def send_api_request(action: str, payload: dict) -> dict:
    """Send post request to the external UID Management API."""
    url = f"{API_URL}?action={action}"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                status_code = response.status
                try:
                    data = await response.json()
                except Exception:
                    data = {"success": False, "message": "Invalid JSON response from server."}
                return {"status": status_code, "data": data}
        except Exception as e:
            return {"status": 500, "data": {"success": False, "message": f"API Connection error: {str(e)}"}}

# ==================== ADD COMMAND GROUP ====================
add_group = app_commands.Group(name="add", description="Add UIDs or Resellers")

@add_group.command(name="uid", description="Add a new UID to the system")
@app_commands.describe(
    uid="The numeric account ID to register",
    day="Number of days until expiry"
)
async def add_uid(interaction: discord.Interaction, uid: str, day: int):
    await interaction.response.defer(ephemeral=False)
    
    is_user_admin = await is_admin(interaction.user)
    reseller_data = get_reseller(interaction.user.id)

    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not is_user_admin and not reseller_data:
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="You do not possess the required permissions to execute this command.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if not is_user_admin:
        # Check expiry
        current_time = int(time.time())
        if reseller_data["expiry_timestamp"] < current_time:
            exp_date = format_utc_timestamp(reseller_data["expiry_timestamp"])
            embed = discord.Embed(
                title="⚠️ Account Expired",
                description=f"Your reseller privileges expired on `{exp_date} UTC`.",
                color=0xFF0000
            )
            embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        # Check credits
        if reseller_data["credits"] <= 0:
            embed = discord.Embed(
                title="⚠️ Insufficient Credits",
                description="Your reseller account does not have any credits remaining.",
                color=0xFF0000
            )
            embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

    if not uid.isdigit():
        embed = discord.Embed(
            title="⚠️ Validation Error",
            description="The provided UID must contain numeric digits only.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    existing = get_registered_uid(uid)
    if existing:
        embed = discord.Embed(
            title="❌ Registration Failed",
            description="This UID is already registered in the system.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    # Call external API matching main (1).py
    payload = {
        "account_id": str(uid),
        "for_days": int(day)
    }

    result = await send_api_request("add", payload)
    status = result["status"]
    data = result["data"]

    is_success = (status in [200, 201]) or (data.get("success") is True) or ("already" in str(data.get("message", "")).lower())

    if not is_success:
        err_msg = data.get("message", "An unexpected error occurred on the main server.")
        embed = discord.Embed(
            title="❌ Registration Failed (Main Server)",
            description=err_msg,
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    credit_info = "Unlimited (Admin Bypass)"
    claim_type = 'admin'
    if not is_user_admin and reseller_data:
        # Deduct credit
        new_credits = reseller_data["credits"] - 1
        update_reseller_credits(interaction.user.id, new_credits)
        credit_info = f"{new_credits} (Deducted 1)"
        claim_type = 'reseller'

    try:
        add_registered_uid(uid, interaction.user.id, day, claim_type)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Database Write Failed",
            description=f"An error occurred while saving the UID to the database: `{str(e)}`",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    embed = discord.Embed(
        title="🔥 UID Registration Complete",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Registered by {interaction.user.name}", icon_url=author_icon)
    embed.add_field(name="Target UID", value=f"`{uid}`", inline=True)
    embed.add_field(name="Validity Period", value=f"`{day}` Days", inline=True)
    embed.add_field(name="Credits Remaining", value=f"`{credit_info}`", inline=False)
    embed.set_footer(text="Local Registry Updated")
    
    await interaction.followup.send(embed=embed)

@add_group.command(name="reseller", description="Add or update a reseller by ID or Mention")
@app_commands.describe(
    user="The Discord user ID or Mention to set as a reseller",
    credits="Number of credits to allocate",
    expire="Expiry duration in days"
)
async def add_reseller(interaction: discord.Interaction, user: str, credits: int, expire: int):
    await interaction.response.defer(ephemeral=False)
    
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not await is_admin(interaction.user):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="This command is restricted to administrative operators.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Extract user ID from string or mention
    user_id_str = user.strip()
    if user_id_str.startswith("<@") and user_id_str.endswith(">"):
        user_id_str = user_id_str.replace("<@", "").replace(">", "").replace("!", "").replace("&", "")

    if not user_id_str.isdigit():
        embed = discord.Embed(
            title="⚠️ Validation Error",
            description="Please provide a valid numeric User ID or User Mention.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    user_id = int(user_id_str)
    
    current_time = int(time.time())
    expiry_timestamp = current_time + (expire * 86400)
    exp_date = format_utc_timestamp(expiry_timestamp)

    add_or_update_reseller(str(user_id), credits, expiry_timestamp)

    embed = discord.Embed(
        title="🔥 Reseller Account Provisioned",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Configured by {interaction.user.name}", icon_url=author_icon)
    embed.add_field(name="Reseller Target", value=f"<@{user_id}>", inline=True)
    embed.add_field(name="Allocated Credits", value=f"`{credits}`", inline=True)
    embed.add_field(name="Validity Period", value=f"`{expire}` Days", inline=True)
    embed.add_field(name="Expiration Date", value=f"`{exp_date} UTC`", inline=False)
    embed.set_footer(text="Reseller Registry Saved")

    await interaction.followup.send(embed=embed)

# ==================== REMOVE COMMAND GROUP ====================
remove_group = app_commands.Group(name="remove", description="Remove UIDs or Resellers")

@remove_group.command(name="uid", description="Remove a UID from the system")
@app_commands.describe(uid="The numeric account ID to remove")
async def remove_uid(interaction: discord.Interaction, uid: str):
    await interaction.response.defer(ephemeral=False)
    
    is_user_admin = await is_admin(interaction.user)
    reseller_data = get_reseller(interaction.user.id)
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not is_user_admin and not reseller_data:
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="You do not have the required permissions to execute this command.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if not is_user_admin:
        # Check expiry
        current_time = int(time.time())
        if reseller_data["expiry_timestamp"] < current_time:
            embed = discord.Embed(
                title="⚠️ Account Expired",
                description="Your reseller account has expired.",
                color=0xFF0000
            )
            embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

    if not uid.isdigit():
        embed = discord.Embed(
            title="⚠️ Validation Error",
            description="The provided UID must contain numeric digits only.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    existing = get_registered_uid(uid)
    if not existing:
        embed = discord.Embed(
            title="❌ Removal Failed",
            description="This UID is not registered in the system.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    if not is_user_admin and existing["discord_id"] != str(interaction.user.id):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="You do not possess permission to remove this UID (only the owner/admin can).",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Call external API to remove the UID matching main (1).py
    payload = {
        "account_id": str(uid)
    }

    delete_action = os.getenv("API_ACTION_DELETE", API_ACTION_DELETE)
    result = await send_api_request(delete_action, payload)
    if result["status"] not in [200, 201] and not result.get("data", {}).get("success") and "Invalid action" in str(result.get("data", {}).get("message", "")) and delete_action != "remove":
        result = await send_api_request("remove", payload)
    status = result["status"]
    data = result["data"]

    is_success = (status in [200, 201]) or (data.get("success") is True)

    if not is_success:
        err_msg = data.get("message", "An unexpected error occurred on the main server.")
        embed = discord.Embed(
            title="❌ Removal Failed (Main Server)",
            description=err_msg,
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    try:
        remove_registered_uid(uid)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Database Write Failed",
            description=f"An error occurred while removing the UID from the database: `{str(e)}`",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    embed = discord.Embed(
        title="🔥 UID Removal Complete",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Removed by {interaction.user.name}", icon_url=author_icon)
    embed.add_field(name="Target UID", value=f"`{uid}`", inline=True)
    embed.set_footer(text="Local Registry Updated")
    await interaction.followup.send(embed=embed)

@remove_group.command(name="reseller", description="Remove a reseller")
async def remove_reseller(interaction: discord.Interaction):
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    # Only admins can trigger this command
    if not await is_admin(interaction.user):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="This command is restricted to administrative operators.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    resellers = list_all_resellers()
    if not resellers:
        embed = discord.Embed(
            title="⚠️ Query Notice",
            description="No active reseller records were found in the local registry.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    options = []
    for r in resellers[:25]:
        uid_str = r["discord_id"]
        member = interaction.guild.get_member(int(uid_str)) if interaction.guild else None
        if not member:
            member = bot.get_user(int(uid_str))
            
        if not member:
            try:
                member = await bot.fetch_user(int(uid_str))
            except Exception:
                pass
        
        name = f"User: {uid_str}"
        if member:
            name = f"{member.display_name} (@{member.name})"
        
        exp_date = format_utc_timestamp(r["expiry_timestamp"], date_only=True)
        options.append(discord.SelectOption(
            label=name[:100],
            value=uid_str,
            description=f"Credits: {r['credits']} | Expires: {exp_date}"
        ))

    class ResellerSelect(discord.ui.Select):
        def __init__(self):
            super().__init__(placeholder="Select a reseller registry entry for deletion...", options=options)

        async def callback(self, select_interaction: discord.Interaction):
            sel_author_icon = select_interaction.user.display_avatar.url if select_interaction.user.avatar else None
            
            if not await is_admin(select_interaction.user):
                embed = discord.Embed(
                    title="⚠️ Access Denied",
                    description="This operation is restricted to admins.",
                    color=0xFF0000
                )
                embed.set_author(name=f"Requested by {select_interaction.user.name}", icon_url=sel_author_icon)
                await select_interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            target_uid = self.values[0]
            delete_reseller(target_uid)
            
            embed = discord.Embed(
                title="🔥 Reseller Account Deprovisioned",
                description=f"Reseller <@{target_uid}> (`{target_uid}`) was successfully removed from the registry.",
                color=0xFF0000,
                timestamp=select_interaction.created_at
            )
            embed.set_author(name=f"Removed by {select_interaction.user.name}", icon_url=sel_author_icon)
            await select_interaction.response.send_message(embed=embed)

    class ResellerSelectView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.add_item(ResellerSelect())

    embed = discord.Embed(
        title="🔥 Deprovision Reseller Account",
        description="Select a reseller entry from the dropdown menu to remove them from the system database.",
        color=0xFF0000
    )
    embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
    await interaction.response.send_message(embed=embed, view=ResellerSelectView(), ephemeral=True)

# ==================== EDIT COMMAND GROUP ====================
edit_group = app_commands.Group(name="edit", description="Edit UIDs or Resellers")

@edit_group.command(name="uid", description="Change an existing UID to a new one")
@app_commands.describe(
    old_uid="Current Account ID to change",
    new_uid="New Account ID to set"
)
async def edit_uid(interaction: discord.Interaction, old_uid: str, new_uid: str):
    await interaction.response.defer(ephemeral=False)
    
    is_user_admin = await is_admin(interaction.user)
    reseller_data = get_reseller(interaction.user.id)
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not is_user_admin and not reseller_data:
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="You do not have the required permissions to execute this command.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if not is_user_admin:
        # Check expiry
        current_time = int(time.time())
        if reseller_data["expiry_timestamp"] < current_time:
            embed = discord.Embed(
                title="⚠️ Account Expired",
                description="Your reseller account has expired.",
                color=0xFF0000
            )
            embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

    if not old_uid.isdigit() or not new_uid.isdigit():
        embed = discord.Embed(
            title="⚠️ Validation Error",
            description="Both old and new UIDs must consist of numeric characters only.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    existing = get_registered_uid(old_uid)
    if not existing:
        embed = discord.Embed(
            title="❌ UID Update Failed",
            description="The current UID is not registered in the system.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    if not is_user_admin and existing["discord_id"] != str(interaction.user.id):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="You do not possess permission to edit this UID (only the owner/admin can).",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    new_existing = get_registered_uid(new_uid)
    if new_existing:
        embed = discord.Embed(
            title="❌ UID Update Failed",
            description="The new UID is already registered in the system.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    # Call external API to change the UID
    payload = {
        "old_uid": str(old_uid),
        "new_uid": str(new_uid)
    }

    result = await send_api_request("change_uid", payload)
    status = result["status"]
    data = result["data"]

    is_success = (status in [200, 201]) or (data.get("success") is True)

    if not is_success:
        err_msg = data.get("message", "An unexpected error occurred on the main server.")
        embed = discord.Embed(
            title="❌ UID Update Failed (Main Server)",
            description=err_msg,
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    try:
        update_registered_uid(old_uid, new_uid)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Database Write Failed",
            description=f"An error occurred while updating the UID in the database: `{str(e)}`",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    embed = discord.Embed(
        title="🔥 UID Update Complete",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Updated by {interaction.user.name}", icon_url=author_icon)
    embed.add_field(name="Previous UID", value=f"`{old_uid}`", inline=True)
    embed.add_field(name="New UID", value=f"`{new_uid}`", inline=True)
    embed.set_footer(text="Local Registry Updated")
    await interaction.followup.send(embed=embed)

@edit_group.command(name="reseller", description="Edit reseller credits")
@app_commands.describe(
    user="The reseller to update",
    credits="New credit count"
)
async def edit_reseller(interaction: discord.Interaction, user: discord.User, credits: int):
    await interaction.response.defer(ephemeral=False)
    
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not await is_admin(interaction.user):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="This command is restricted to administrative operators.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    reseller_data = get_reseller(user.id)
    if not reseller_data:
        embed = discord.Embed(
            title="⚠️ Record Not Found",
            description=f"User <@{user.id}> does not possess a reseller registry record.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    update_reseller_credits(str(user.id), credits)
    
    embed = discord.Embed(
        title="🔥 Credits Updated",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Modified by {interaction.user.name}", icon_url=author_icon)
    embed.add_field(name="Reseller Target", value=user.mention, inline=True)
    embed.add_field(name="Previous Balance", value=f"`{reseller_data['credits']}`", inline=True)
    embed.add_field(name="New Balance", value=f"`{credits}`", inline=True)
    embed.set_footer(text="Reseller Registry Saved")
    
    await interaction.followup.send(embed=embed)

@app_commands.command(name="free", description="Register one free UID for 1 day (once per 24 hours)")
@app_commands.describe(uid="The numeric account ID to register for 1 day")
async def free_command(interaction: discord.Interaction, uid: str):
    await interaction.response.defer(ephemeral=False)
    
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not uid.isdigit():
        embed = discord.Embed(
            title="⚠️ Validation Error",
            description="The provided UID must contain numeric digits only.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    current_time = int(time.time())
    last_claim = get_last_claim(interaction.user.id)
    time_elapsed = current_time - last_claim
    cooldown = 86400  # 24 hours in seconds

    if time_elapsed < cooldown:
        seconds_left = cooldown - time_elapsed
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        embed = discord.Embed(
            title="⚠️ Cooldown Active",
            description=f"You have already claimed your daily free UID.\nTry again in `{hours}h {minutes}m`.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    existing = get_registered_uid(uid)
    if existing:
        embed = discord.Embed(
            title="❌ Claim Failed",
            description="This UID is already registered in the system.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    # Call external API matching main (1).py
    payload = {
        "account_id": str(uid),
        "for_days": 1
    }

    result = await send_api_request("add", payload)
    status = result["status"]
    data = result["data"]

    is_success = (status in [200, 201]) or (data.get("success") is True) or ("already" in str(data.get("message", "")).lower())

    if not is_success:
        err_msg = data.get("message", "An unexpected error occurred on the main server.")
        embed = discord.Embed(
            title="❌ Claim Failed (Main Server)",
            description=err_msg,
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return

    try:
        set_last_claim(interaction.user.id, current_time)
        add_registered_uid(uid, interaction.user.id, 1, 'free')
    except Exception as e:
        embed = discord.Embed(
            title="❌ Database Write Failed",
            description=f"An error occurred while saving your free claim to the database: `{str(e)}`",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="🔥 Free Daily UID Claimed",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Claimed by {interaction.user.name}", icon_url=author_icon)
    embed.add_field(name="Target UID", value=f"`{uid}`", inline=True)
    embed.add_field(name="Validity Period", value="`1` Day", inline=True)
    embed.set_footer(text="Daily Free Allotment Utilized")
    await interaction.followup.send(embed=embed)




# ==================== LIST COMMAND GROUP ====================
list_group = app_commands.Group(name="list", description="List registered UIDs or Resellers")

@list_group.command(name="resellers", description="List all resellers registered in the system")
async def list_resellers(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not await is_admin(interaction.user):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="This command is restricted to administrative operators.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    resellers = list_all_resellers()
    
    embed = discord.Embed(
        title="🔥 Active Resellers List",
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)

    if not resellers:
        embed.description = "No active resellers found in the system registry."
    else:
        desc_lines = []
        for i, r in enumerate(resellers, 1):
            exp_date = format_utc_timestamp(r["expiry_timestamp"])
            desc_lines.append(f"**{i}.** <@{r['discord_id']}> (`{r['discord_id']}`)\n🪙 Credits: `{r['credits']}` | 📅 Expires: `{exp_date} UTC`")
        embed.description = "\n\n".join(desc_lines)

    embed.set_footer(text="Reseller Registry Synced")
    await interaction.followup.send(embed=embed)

@list_group.command(name="uids", description="List all registered UIDs")
async def list_uids(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    
    is_user_admin = await is_admin(interaction.user)
    reseller_data = get_reseller(interaction.user.id)
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not is_user_admin and not reseller_data:
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="You do not have the required permissions to execute this command.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Admins see all UIDs. Resellers only see UIDs they added themselves.
    if is_user_admin:
        uids = list_registered_uids()
        list_title = "🔥 All Registered UIDs (Admin view)"
    else:
        # Reseller has expired check
        current_time = int(time.time())
        if reseller_data["expiry_timestamp"] < current_time:
            embed = discord.Embed(
                title="⚠️ Account Expired",
                description="Your reseller account has expired.",
                color=0xFF0000
            )
            embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        uids = list_registered_uids(interaction.user.id)
        list_title = "🔥 Your Registered UIDs"

    embed = discord.Embed(
        title=list_title,
        color=0xFF0000,
        timestamp=interaction.created_at
    )
    embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)

    if not uids:
        embed.description = "No registered UIDs found."
    else:
        desc_lines = []
        for i, u in enumerate(uids[:30], 1): # Cap at 30 items to stay under embed limits
            added_date = time.strftime('%Y-%m-%d', time.gmtime(u["added_timestamp"]))
            desc_lines.append(f"**{i}.** UID: `{u['uid']}`\n👤 Added by: <@{u['discord_id']}> | 📅 Added: `{added_date}` | 🏷️ Type: `{u['claim_type'].upper()}`")
        
        if len(uids) > 30:
            desc_lines.append(f"*...and {len(uids) - 30} more registered UIDs.*")
        embed.description = "\n\n".join(desc_lines)

    embed.set_footer(text="Local Registry Synced")
    await interaction.followup.send(embed=embed)


@app_commands.command(name="sync", description="Force sync all slash commands (Admin only)")
async def sync_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    author_icon = interaction.user.display_avatar.url if interaction.user.avatar else None

    if not await is_admin(interaction.user):
        embed = discord.Embed(
            title="⚠️ Access Denied",
            description="This command is restricted to administrative operators.",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    try:
        await bot.tree.sync()
        embed = discord.Embed(
            title="🔥 Commands Synced",
            description="All slash commands have been successfully synced with Discord.",
            color=0xFF0000
        )
        embed.set_author(name=f"Executed by {interaction.user.name}", icon_url=author_icon)
        embed.set_footer(text="Command Registry Synced")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Sync Failed",
            description=f"An error occurred while syncing: `{str(e)}`",
            color=0xFF0000
        )
        embed.set_author(name=f"Requested by {interaction.user.name}", icon_url=author_icon)
        await interaction.followup.send(embed=embed)


if __name__ == "__main__":
    init_db()
    if not TOKEN or TOKEN == "your_discord_bot_token_here":
        print("Please configure your DISCORD_TOKEN in the .env file.")
    else:
        bot.run(TOKEN)

