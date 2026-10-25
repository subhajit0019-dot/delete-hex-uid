import os
import time
import sqlite3
import secrets
import threading
import requests
from urllib.parse import urlencode
from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from dotenv import load_dotenv
load_dotenv()

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

static_dir = os.path.join(BASE_DIR, "static")
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=static_dir
)
app.secret_key = config.SECRET_KEY

# Ensure session cookies are hardened (Secure enabled on Vercel HTTPS)
is_vercel = bool(os.getenv("VERCEL"))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=is_vercel,
    TEMPLATES_AUTO_RELOAD=not is_vercel
)
app.jinja_env.auto_reload = not is_vercel

# Admin Panel Credentials (/admin)
ADMIN_PANEL_USER = config.ADMIN_PANEL_USER
ADMIN_PANEL_PASS = config.ADMIN_PANEL_PASS

# API & Server Configuration loaded directly from config.py
API_KEY = config.API_KEY
API_URL = config.API_URL
API_ACTION_ADD = getattr(config, "API_ACTION_ADD", "add")
API_ACTION_EDIT = getattr(config, "API_ACTION_EDIT", "change_uid")
API_ACTION_DELETE = getattr(config, "API_ACTION_DELETE", "delete")

DISCORD_SERVER_INVITE = config.DISCORD_SERVER_INVITE
DELETEHEX_DISCORD_SERVER_INVITE = getattr(config, "DELETEHEX_DISCORD_SERVER_INVITE", config.DISCORD_SERVER_INVITE)

# Vercel Serverless environment compatibility:
# /var/task is read-only on Vercel. Writable SQLite database must reside in temp directory (/tmp).
if is_vercel:
    import tempfile
    import shutil
    tmp_dir = "/tmp" if os.path.exists("/tmp") else tempfile.gettempdir()
    tmp_db = os.path.join(tmp_dir, "database.db")
    seed_db = os.path.join(BASE_DIR, "database.db")
    if not os.path.exists(tmp_db) and os.path.exists(seed_db):
        try:
            shutil.copy2(seed_db, tmp_db)
        except Exception:
            pass
    DB_PATH = tmp_db
else:
    DB_PATH = os.path.abspath(os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "database.db")))

COOLDOWN_SECONDS = 86400  # Strict 24-hour cycle

# Concurrency lock to prevent race-condition bypass exploits
claim_lock = threading.Lock()

# ==================== CLOUDFLARE & CLIENT IP DETECTION ====================
def get_client_ip() -> str:
    """Accurately resolve the visitor's real IP behind Cloudflare or reverse proxies."""
    # Cloudflare standard header
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip.strip()

    # Standard real IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Standard proxy chain header (leftmost IP is origin)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[0]

    return request.remote_addr or "127.0.0.1"

def get_client_identifiers():
    """Retrieve both IP address and persistent session client token for layered anti-bypass."""
    ip = get_client_ip()
    if "client_token" not in session:
        session["client_token"] = secrets.token_hex(16)
    return ip, session["client_token"]

# ==================== DATABASE INITIALIZATION & HELPERS ====================
def get_db():
    """Create a SQLite connection configured with in-memory journaling to prevent .db-journal files."""
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("PRAGMA journal_mode = MEMORY;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    # Rate limit table tracking claims per identifier (IP and session token)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            identifier TEXT PRIMARY KEY,
            last_claim_timestamp INTEGER,
            last_claimed_uid TEXT
        )
    """)
    # Registered UIDs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registered_uids (
            uid TEXT PRIMARY KEY,
            discord_id TEXT,
            added_timestamp INTEGER,
            expiry_days INTEGER,
            claim_type TEXT,
            identifier TEXT
        )
    """)
    # Ensure identifier column exists if table was created in an older schema
    cursor.execute("PRAGMA table_info(registered_uids);")
    columns = [col[1] for col in cursor.fetchall()]
    if "identifier" not in columns:
        try:
            cursor.execute("ALTER TABLE registered_uids ADD COLUMN identifier TEXT;")
        except Exception:
            pass
    if "discord_id" not in columns:
        try:
            cursor.execute("ALTER TABLE registered_uids ADD COLUMN discord_id TEXT;")
        except Exception:
            pass

    # System settings table for maintenance mode and dynamic configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO system_settings (key, value)
        VALUES ('maintenance_mode', '0')
    """)

    conn.commit()
    conn.close()

init_db()

# ==================== ADMIN & MAINTENANCE HELPERS ====================
def is_maintenance_mode() -> bool:
    """Check if free UID claims are paused for maintenance."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = 'maintenance_mode'")
        row = cursor.fetchone()
        return bool(row and row[0] == '1')
    except Exception:
        return False
    finally:
        conn.close()

def set_maintenance_mode(enabled: bool):
    """Enable or disable free UID claims maintenance mode."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        val = '1' if enabled else '0'
        cursor.execute("""
            INSERT INTO system_settings (key, value)
            VALUES ('maintenance_mode', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (val,))
        conn.commit()
    finally:
        conn.close()

def get_admin_stats() -> dict:
    """Compile metrics on lifetime claims, today's claims, and active rate limits."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        current_time = int(time.time())
        day_ago = current_time - 86400

        cursor.execute("SELECT COUNT(*) FROM registered_uids")
        total_claims = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM registered_uids WHERE added_timestamp >= ?", (day_ago,))
        claims_24h = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT identifier) FROM rate_limits WHERE last_claim_timestamp >= ?", (day_ago,))
        active_cooldowns = cursor.fetchone()[0]

        return {
            "total_claims": total_claims,
            "claims_24h": claims_24h,
            "active_cooldowns": active_cooldowns,
            "maintenance_mode": is_maintenance_mode()
        }
    finally:
        conn.close()

def get_all_claims(query: str = None, limit: int = 200) -> list:
    """Retrieve claimed UIDs with timestamp and client identifier."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        current_time = int(time.time())
        if query:
            q = f"%{query.strip()}%"
            cursor.execute("""
                SELECT uid, added_timestamp, expiry_days, claim_type, identifier
                FROM registered_uids
                WHERE uid LIKE ? OR identifier LIKE ?
                ORDER BY added_timestamp DESC
                LIMIT ?
            """, (q, q, limit))
        else:
            cursor.execute("""
                SELECT uid, added_timestamp, expiry_days, claim_type, identifier
                FROM registered_uids
                ORDER BY added_timestamp DESC
                LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        claims = []
        for row in rows:
            uid, added_ts, expiry_days, claim_type, identifier = row
            is_active = (added_ts + (expiry_days * 86400)) > current_time
            readable_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(added_ts))
            claims.append({
                "uid": uid,
                "added_timestamp": added_ts,
                "readable_date": readable_date,
                "expiry_days": expiry_days,
                "claim_type": claim_type or "free_web",
                "identifier": identifier or "Unknown",
                "is_active": is_active
            })
        return claims
    finally:
        conn.close()

def delete_claimed_uid(uid: str) -> bool:
    """Remove a UID from whitelist registration and clear its cooldown."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM registered_uids WHERE uid = ?", (uid,))
        cursor.execute("DELETE FROM rate_limits WHERE last_claimed_uid = ?", (uid,))
        conn.commit()
        return True
    finally:
        conn.close()

def reset_identifier_cooldown(identifier: str) -> bool:
    """Clear 24-hour rate limit for a specific IP or UID."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rate_limits WHERE identifier = ? OR last_claimed_uid = ?", (identifier, identifier))
        conn.commit()
        return True
    finally:
        conn.close()

def reset_all_rate_limits() -> bool:
    """Reset all active 24-hour rate limits, allowing immediate re-claims."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rate_limits")
        conn.commit()
        return True
    finally:
        conn.close()


def get_cooldown_data(ip: str, client_token: str, discord_id: str = None):
    """Check cooldown status across IP, session cookie, and Discord ID to eliminate bypasses."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        identifiers = [ip, client_token]
        if discord_id:
            identifiers.append(f"discord_{discord_id}")

        placeholders = ",".join("?" for _ in identifiers)
        cursor.execute(
            f"SELECT MAX(last_claim_timestamp), last_claimed_uid FROM rate_limits WHERE identifier IN ({placeholders})",
            identifiers
        )
        row = cursor.fetchone()
        last_claim_timestamp = row[0] if (row and row[0]) else 0
        last_claimed_uid = row[1] if (row and row[1]) else None
        current_time = int(time.time())
        elapsed = current_time - last_claim_timestamp
        remaining = max(0, COOLDOWN_SECONDS - elapsed) if last_claim_timestamp > 0 else 0

        return {
            "last_claim_timestamp": last_claim_timestamp,
            "last_claimed_uid": last_claimed_uid,
            "cooldown_remaining": remaining,
            "can_claim": remaining == 0,
            "current_time": current_time
        }
    finally:
        conn.close()

def record_claim(ip: str, client_token: str, uid: str, current_time: int, discord_id: str = None):
    """Atomically record claim timestamp across IP, session token, and Discord ID without journal disk artifacts."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        effective_discord_id = discord_id or ip
        identifiers = [ip, client_token]
        if discord_id:
            identifiers.append(f"discord_{discord_id}")

        for identifier in identifiers:
            cursor.execute("""
                INSERT INTO rate_limits (identifier, last_claim_timestamp, last_claimed_uid)
                VALUES (?, ?, ?)
                ON CONFLICT(identifier) DO UPDATE SET
                    last_claim_timestamp = excluded.last_claim_timestamp,
                    last_claimed_uid = excluded.last_claimed_uid
            """, (identifier, current_time, uid))

        cursor.execute("""
            INSERT INTO registered_uids (uid, discord_id, identifier, added_timestamp, expiry_days, claim_type)
            VALUES (?, ?, ?, ?, 1, 'free_web')
            ON CONFLICT(uid) DO UPDATE SET
                discord_id = excluded.discord_id,
                identifier = excluded.identifier,
                added_timestamp = excluded.added_timestamp,
                expiry_days = 1,
                claim_type = 'free_web'
        """, (uid, effective_discord_id, ip, current_time))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def is_uid_already_active(uid: str, current_time: int) -> bool:
    """Verify if UID has already been whitelisted within an active window."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT added_timestamp, expiry_days FROM registered_uids WHERE uid = ?",
            (uid,)
        )
        row = cursor.fetchone()
        if row:
            added_ts, expiry_days = row
            if added_ts + (expiry_days * 86400) > current_time:
                return True
        return False
    finally:
        conn.close()

# ==================== EXTERNAL API CLIENT ====================
def call_upstream_uid_api(uid: str, days: int = 1) -> dict:
    """Secure upstream whitelist API call. No keys or URLs leak to client."""
    current_key = os.getenv("API_KEY") or API_KEY or "GTCAPI-BB05166D26D7EC81F86BA3C893998613"
    current_url = os.getenv("API_URL") or API_URL or "https://gtccheats.xyz/Api/uidbypassapi/api_user.php"
    action = os.getenv("API_ACTION_ADD", API_ACTION_ADD)

    url = f"{current_url}?action={action}"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": current_key
    }
    payload = {
        "account_id": str(uid),
        "for_days": int(days)
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        try:
            data = response.json()
        except Exception:
            data = {"success": False, "message": "Unexpected upstream gateway response."}

        is_success = (response.status_code in [200, 201]) or (data.get("success") is True) or ("already" in str(data.get("message", "")).lower())
        message = data.get("message", "Whitelist request processed.") if is_success else data.get("message", "Upstream server rejected request.")

        return {
            "status": 200 if is_success else 502,
            "success": is_success,
            "message": message
        }
    except requests.exceptions.Timeout:
        return {"status": 504, "success": False, "message": "Upstream gate timed out. Please try again in a few moments."}
    except Exception:
        return {"status": 500, "success": False, "message": "Network error while connecting to activation gateway."}

def admin_add_registered_uid(uid: str, days: int = 1, claim_type: str = "admin", identifier: str = "ADMIN") -> bool:
    """Insert or update a registered UID from the admin panel."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        current_time = int(time.time())
        cursor.execute("""
            INSERT INTO registered_uids (uid, discord_id, identifier, added_timestamp, expiry_days, claim_type)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                discord_id = excluded.discord_id,
                identifier = excluded.identifier,
                added_timestamp = excluded.added_timestamp,
                expiry_days = excluded.expiry_days,
                claim_type = excluded.claim_type
        """, (str(uid), "admin", identifier, current_time, int(days), claim_type))
        conn.commit()
        return True
    finally:
        conn.close()

def delete_upstream_uid_api(uid: str) -> dict:
    """Delete a UID from the upstream whitelist API using configured API_ACTION_DELETE."""
    current_key = os.getenv("API_KEY") or API_KEY or "GTCAPI-BB05166D26D7EC81F86BA3C893998613"
    current_url = os.getenv("API_URL") or API_URL or "https://gtccheats.xyz/Api/uidbypassapi/api_user.php"
    action = os.getenv("API_ACTION_DELETE", API_ACTION_DELETE)

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": current_key
    }
    payload = {
        "account_id": str(uid)
    }

    try:
        url = f"{current_url}?action={action}"
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        try:
            data = response.json()
        except Exception:
            data = {"success": False, "message": "Unexpected upstream gateway response."}

        # If configured action was 'delete' but upstream server expects 'remove', auto-fallback
        if not data.get("success") and "Invalid action" in str(data.get("message", "")) and action != "remove":
            fallback_url = f"{current_url}?action=remove"
            response = requests.post(fallback_url, json=payload, headers=headers, timeout=12)
            try:
                data = response.json()
            except Exception:
                data = {"success": False, "message": "Unexpected upstream gateway response."}

        is_success = (
            (response.status_code in [200, 201])
            or (data.get("success") is True)
            or ("not found" in str(data.get("message", "")).lower())
            or ("deleted" in str(data.get("message", "")).lower())
            or ("removed" in str(data.get("message", "")).lower())
        )
        return {
            "status": 200 if is_success else response.status_code,
            "success": is_success,
            "message": data.get("message", "Upstream UID deletion processed.")
        }
    except requests.exceptions.Timeout:
        return {"status": 504, "success": False, "message": "Upstream gate timed out."}
    except Exception as e:
        return {"status": 500, "success": False, "message": f"Network error: {str(e)}"}

# ==================== DISCORD OAUTH2 & MEMBER VERIFICATION ====================
def get_discord_redirect_uri():
    if config.DISCORD_REDIRECT_URI:
        return config.DISCORD_REDIRECT_URI
    base = request.host_url.rstrip("/")
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" or (is_vercel and base.startswith("http://")):
        base = "https://" + base.split("://", 1)[-1]
    return f"{base}/auth/discord/callback"

def get_discord_oauth_url():
    if not config.DISCORD_CLIENT_ID:
        return None
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": get_discord_redirect_uri(),
        "response_type": "code",
        "scope": "identify guilds guilds.join",
        "prompt": "consent"
    }
    return f"https://discord.com/oauth2/authorize?{urlencode(params)}"

def exchange_discord_code(code: str):
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": get_discord_redirect_uri()
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post("https://discord.com/api/v10/oauth2/token", data=data, headers=headers, timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def get_discord_user_profile(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def add_and_verify_guild_member(user_id: str, access_token: str) -> bool:
    """Automatically joins user to guild via guilds.join and verifies membership."""
    guild_id = getattr(config, "DELETEHEX_GUILD_ID", None) or config.GUILD_ID
    bot_token = config.DISCORD_BOT_TOKEN
    is_member = False

    # 1. Bot Token Join Attempt: PUT /guilds/{guild_id}/members/{user_id}
    if bot_token and guild_id and access_token:
        join_url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"
        join_headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json"
        }
        try:
            put_res = requests.put(join_url, json={"access_token": access_token}, headers=join_headers, timeout=10)
            if put_res.status_code in (201, 204):
                is_member = True
        except Exception:
            pass

        # Check membership via Bot API: GET /guilds/{guild_id}/members/{user_id}
        if not is_member:
            try:
                get_res = requests.get(join_url, headers=join_headers, timeout=10)
                if get_res.status_code == 200:
                    is_member = True
            except Exception:
                pass

    # 2. Dual fallback: check user's guilds list via user access_token
    if not is_member and access_token:
        try:
            g_res = requests.get(
                "https://discord.com/api/v10/users/@me/guilds",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
            if g_res.status_code == 200:
                user_guilds = g_res.json()
                for g in user_guilds:
                    if str(g.get("id")) in (str(getattr(config, "DELETEHEX_GUILD_ID", config.GUILD_ID)), str(config.GUILD_ID)):
                        is_member = True
                        break
        except Exception:
            pass

    return is_member

# ==================== ROUTES ====================
@app.route("/")
def index():
    ip, token = get_client_identifiers()
    discord_user = session.get("discord_user")
    discord_id = discord_user.get("id") if discord_user else None

    status_info = get_cooldown_data(ip, token, discord_id=discord_id)
    maintenance = is_maintenance_mode()

    discord_oauth_enabled = bool(config.DISCORD_CLIENT_ID)
    is_discord_verified = (not discord_oauth_enabled) or (discord_user and discord_user.get("in_guild"))

    can_claim = status_info["can_claim"] and not maintenance and is_discord_verified

    return render_template(
        "index.html",
        cooldown_remaining=status_info["cooldown_remaining"],
        can_claim=can_claim,
        maintenance_mode=maintenance,
        last_claimed_uid=status_info["last_claimed_uid"],
        last_claim_timestamp=status_info["last_claim_timestamp"],
        current_time=status_info["current_time"],
        discord_user=discord_user,
        discord_oauth_enabled=discord_oauth_enabled,
        is_discord_verified=is_discord_verified,
        discord_oauth_url=get_discord_oauth_url(),
        NOVA_SERVER_INVITE=DISCORD_SERVER_INVITE,
        DELETEHEX_SERVER_INVITE=DELETEHEX_DISCORD_SERVER_INVITE
    )

@app.route("/auth/discord")
def auth_discord():
    oauth_url = get_discord_oauth_url()
    if not oauth_url:
        return redirect("/?error=discord_oauth_not_configured")
    return redirect(oauth_url)

@app.route("/auth/discord/callback")
def auth_discord_callback():
    code = request.args.get("code")
    if not code:
        return redirect("/")

    token_data = exchange_discord_code(code)
    if not token_data or "access_token" not in token_data:
        return redirect("/?auth_error=token_failed")

    access_token = token_data["access_token"]
    user_info = get_discord_user_profile(access_token)
    if not user_info or "id" not in user_info:
        return redirect("/?auth_error=profile_failed")

    user_id = str(user_info["id"])
    avatar = user_info.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=128" if avatar else "https://cdn.discordapp.com/embed/avatars/0.png"

    in_guild = add_and_verify_guild_member(user_id, access_token)

    session["discord_user"] = {
        "id": user_id,
        "username": user_info.get("username", "Member"),
        "global_name": user_info.get("global_name") or user_info.get("username", "Member"),
        "avatar": avatar_url,
        "access_token": access_token,
        "in_guild": in_guild
    }
    if not in_guild:
        return redirect("/?join_prompt=1")
    return redirect("/?verified=1")

@app.route("/auth/discord/check-guild")
def auth_discord_check_guild():
    user = session.get("discord_user")
    if not user:
        return jsonify({"success": False, "authenticated": False}), 401
    in_guild = add_and_verify_guild_member(user["id"], user.get("access_token"))
    user["in_guild"] = in_guild
    session["discord_user"] = user
    session.modified = True
    return jsonify({"success": True, "in_guild": in_guild})

@app.route("/auth/discord/logout")
def auth_discord_logout():
    session.pop("discord_user", None)
    return redirect("/")

@app.route("/api/status", methods=["GET"])
def api_status():
    """Live status query endpoint for client countdown synchronization."""
    ip, token = get_client_identifiers()
    discord_user = session.get("discord_user")
    discord_id = discord_user.get("id") if discord_user else None
    status_info = get_cooldown_data(ip, token, discord_id=discord_id)
    maintenance = is_maintenance_mode()

    discord_oauth_enabled = bool(config.DISCORD_CLIENT_ID)
    is_discord_verified = (not discord_oauth_enabled) or (discord_user and discord_user.get("in_guild"))

    return jsonify({
        "can_claim": status_info["can_claim"] and not maintenance and is_discord_verified,
        "cooldown_remaining": status_info["cooldown_remaining"],
        "maintenance_mode": maintenance,
        "current_time": status_info["current_time"],
        "last_claim_timestamp": status_info["last_claim_timestamp"],
        "last_claimed_uid": status_info["last_claimed_uid"],
        "discord_user": {
            "username": discord_user.get("username"),
            "global_name": discord_user.get("global_name"),
            "in_guild": discord_user.get("in_guild")
        } if discord_user else None,
        "is_discord_verified": is_discord_verified
    })

@app.route("/api/whitelist", methods=["POST"])
@app.route("/api/claim", methods=["POST"])
def api_claim():
    """Whitelists a numeric UID with strict 24-hour rate limit and anti-glitch concurrency lock."""
    if is_maintenance_mode():
        return jsonify({
            "success": False,
            "maintenance": True,
            "message": "Free UID Whitelist is currently under maintenance. Claims are temporarily paused by administration."
        }), 503

    discord_user = session.get("discord_user")
    discord_id = discord_user.get("id") if discord_user else None

    # Discord Membership gate check
    if bool(config.DISCORD_CLIENT_ID) and config.REQUIRE_DISCORD_LOGIN:
        if not discord_user:
            return jsonify({
                "success": False,
                "require_discord": True,
                "message": "Discord verification required! Please authorize your Discord account before claiming."
            }), 401

        if not discord_user.get("in_guild"):
            # Real-time re-verify membership in case they just clicked join
            if add_and_verify_guild_member(discord_user["id"], discord_user.get("access_token")):
                discord_user["in_guild"] = True
                session["discord_user"] = discord_user
            else:
                return jsonify({
                    "success": False,
                    "require_guild": True,
                    "message": "You must join the Delete Hex Discord server before whitelisting your UID!"
                }), 403

    data = request.get_json(silent=True) or {}
    uid = str(data.get("uid", "")).strip()

    # UID Validation: numeric only, 5 to 20 digits
    if not uid or not uid.isdigit():
        return jsonify({"success": False, "message": "Invalid UID! Please provide a numeric Account ID."}), 400

    if len(uid) < 5 or len(uid) > 20:
        return jsonify({"success": False, "message": "UID length must be between 5 and 20 digits."}), 400

    ip, token = get_client_identifiers()
    current_time = int(time.time())

    # Threading lock prevents parallel requests from racing past the cooldown check
    with claim_lock:
        status_info = get_cooldown_data(ip, token, discord_id=discord_id)
        if not status_info["can_claim"]:
            seconds_left = status_info["cooldown_remaining"]
            h = seconds_left // 3600
            m = (seconds_left % 3600) // 60
            s = seconds_left % 60
            return jsonify({
                "success": False,
                "message": f"Daily limit reached! 24 ghante me sirf 1 UID add ho sakta hai. Next claim unlock in: {h}h {m}m {s}s.",
                "cooldown_remaining": seconds_left
            }), 429

        # Verify UID is not already registered and currently active
        if is_uid_already_active(uid, current_time):
            return jsonify({
                "success": False,
                "message": f"UID {uid} is already active in the whitelist system."
            }), 400

        # Execute upstream API call
        upstream_result = call_upstream_uid_api(uid)
        if not upstream_result.get("success"):
            return jsonify({
                "success": False,
                "message": upstream_result.get("message", "Upstream server rejected registration.")
            }), upstream_result.get("status", 502)

        # Record claim and enforce 24-hour cooldown
        try:
            record_claim(ip, token, uid, current_time, discord_id=discord_id)
        except Exception:
            return jsonify({"success": False, "message": "Database write error. Please try again."}), 500

        return jsonify({
            "success": True,
            "message": f"SUCCESS! UID {uid} has been activated for 24 hours.",
            "uid": uid,
            "validity": "24 Hours (1 Day)",
            "cooldown_remaining": COOLDOWN_SECONDS
        }), 200

# ==================== ADMIN PANEL ROUTES (/admin) ====================
@app.route("/admin", methods=["GET", "POST"])
def admin_panel():
    """Admin panel: authentication with user 72 / pass 12, maintenance toggle, and claim monitoring."""
    if request.method == "POST":
        username = str(request.form.get("username", "")).strip()
        password = str(request.form.get("password", "")).strip()

        if username == ADMIN_PANEL_USER and password == ADMIN_PANEL_PASS:
            session["admin_authenticated"] = True
            return redirect("/admin")
        else:
            return render_template("admin_login.html", error="Invalid admin username or password.")

    # GET Request
    if not session.get("admin_authenticated"):
        return render_template("admin_login.html")

    search_q = request.args.get("q", "").strip()
    msg = request.args.get("msg", "").strip()
    error = request.args.get("error", "").strip()
    stats = get_admin_stats()
    claims = get_all_claims(query=search_q if search_q else None)

    return render_template(
        "admin.html",
        stats=stats,
        claims=claims,
        search_q=search_q,
        msg=msg,
        error=error,
        maintenance_mode=stats["maintenance_mode"],
        api_action_add=API_ACTION_ADD
    )

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    return redirect("/admin")

@app.route("/admin/add-uid", methods=["POST"])
def admin_add_uid():
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    uid = (request.form.get("uid") or (request.json.get("uid") if request.is_json else "") or "").strip()
    days_val = request.form.get("days") or (request.json.get("days") if request.is_json else 1)
    try:
        days = max(1, min(3650, int(days_val)))
    except (TypeError, ValueError):
        days = 1

    if not uid:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": "UID cannot be empty."}), 400
        return redirect("/admin?error=UID+cannot+be+empty")

    if not uid.isdigit():
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": "UID must contain numeric digits only."}), 400
        return redirect("/admin?error=UID+must+contain+numeric+digits+only")

    # Call upstream API with configured API_ACTION_ADD
    res = call_upstream_uid_api(uid, days=days)
    if not res.get("success"):
        err_msg = res.get("message", "Upstream server rejected registration.")
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": err_msg}), 400
        return redirect(f"/admin?error={requests.utils.quote(err_msg)}")

    # Record in database under admin
    admin_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "127.0.0.1"
    admin_add_registered_uid(uid, days=days, claim_type="admin", identifier=f"admin_{admin_ip}")

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "message": f"UID {uid} whitelisted successfully for {days} day(s).",
            "uid": uid,
            "days": days
        })

    return redirect(f"/admin?msg=UID+{uid}+whitelisted+successfully+for+{days}+day(s)")

@app.route("/admin/toggle-maintenance", methods=["POST"])
def admin_toggle_maintenance():
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    current = is_maintenance_mode()
    set_maintenance_mode(not current)
    return redirect("/admin")

@app.route("/admin/reset-cooldown", methods=["POST"])
def admin_reset_cooldown():
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    target = request.form.get("target", "").strip()
    if target:
        reset_identifier_cooldown(target)
    return redirect("/admin")

@app.route("/admin/reset-all-cooldowns", methods=["POST"])
def admin_reset_all_cooldowns():
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    reset_all_rate_limits()
    return redirect("/admin")

@app.route("/admin/delete-uid", methods=["POST"])
def admin_delete_uid():
    if not session.get("admin_authenticated"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    uid = (request.form.get("uid") or (request.json.get("uid") if request.is_json else "") or "").strip()
    if uid:
        delete_upstream_uid_api(uid)
        delete_claimed_uid(uid)
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "message": f"UID {uid} deleted successfully from database and upstream whitelist."
            })
    return redirect("/admin")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"[*] Delete Hex Portal initialized on port {port}")
    # debug=False strictly enforced to conceal debugger and prevent stack trace leaks
    app.run(host="0.0.0.0", port=port, debug=False)

