"""
Delete Hex Configuration Module
Tracked directly in GitHub. Works on Vercel and local machines without any .env file needed.
"""
import os

# ==================== DISCORD LINKS & GUILD IDS ====================
DISCORD_SERVER_INVITE = os.getenv("DISCORD_SERVER_INVITE", "https://discord.gg/QDNBcfCAAh")
DELETEHEX_DISCORD_SERVER_INVITE = os.getenv("DELETEHEX_DISCORD_SERVER_INVITE", os.getenv("DISCORD_SERVER_INVITE", "https://discord.gg/QDNBcfCAAh"))

GUILD_ID = os.getenv("GUILD_ID", "1320592077997998162")
DELETEHEX_GUILD_ID = os.getenv("DELETEHEX_GUILD_ID", os.getenv("GUILD_ID", "1320592077997998162"))

# ==================== DISCORD OAUTH2 & BOT VERIFICATION ====================
# Discord Developer Portal: https://discord.com/developers/applications -> General Information / OAuth2
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1563845260474318958")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "nzly38gMySgEJawC_a6DIaiuvm6vfz6b")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", os.getenv("DISCORD_TOKEN", "MTU2Mzg0NTI2MDQ3NDMxODk1OA.GUnhC2.mFvPEY5hdl5nGkaVLiUD3hU79R3LUzS1IzhKF0"))
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "")
REQUIRE_DISCORD_LOGIN = os.getenv("REQUIRE_DISCORD_LOGIN", "true").lower() in ("true", "1", "yes")

# ==================== WEB SESSION SECRET & PORT ====================
SECRET_KEY = os.getenv("SECRET_KEY", "deletehex_secure_session_key_2026")
PORT = int(os.getenv("PORT", 5000))

# ==================== UPSTREAM WHITELIST API CONFIG ====================
# Embedded directly so GitHub repo deployed to Vercel works immediately
API_KEY = os.getenv("API_KEY", "GTCAPI-BB05166D26D7EC81F86BA3C893998613")
API_URL = os.getenv("API_URL", "https://gtccheats.xyz/Api/uidbypassapi/api_user.php")

API_ACTION_ADD = os.getenv("API_ACTION_ADD", "add")
API_ACTION_EDIT = os.getenv("API_ACTION_EDIT", "change_uid")
API_ACTION_DELETE = os.getenv("API_ACTION_DELETE", "delete")

# ==================== ADMIN CONTROL PANEL (/admin) ====================
ADMIN_PANEL_USER = os.getenv("ADMIN_PANEL_USER", "72")
ADMIN_PANEL_PASS = os.getenv("ADMIN_PANEL_PASS", "12")
ADMIN_IDS = [id.strip() for id in os.getenv("ADMIN_IDS", "1535215246015340624").split(",") if id.strip()]
