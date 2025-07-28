import discord
from discord.ext import commands
import random
import string
import os
import requests
import psycopg2
from urllib.parse import urlparse
from flask import Flask
from threading import Thread

# ===== Flask keep-alive (Replit) =====
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ===== PostgreSQL setup =====
DATABASE_URL = os.environ["DATABASE_URL"]
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS keys (
    key TEXT PRIMARY KEY,
    used BOOLEAN DEFAULT FALSE
);
""")
conn.commit()

def load_keys():
    cur.execute("SELECT key, used FROM keys;")
    rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}

def insert_key(new_key):
    cur.execute("INSERT INTO keys (key, used) VALUES (%s, %s)", (new_key, False))
    conn.commit()

def set_key_used(key):
    cur.execute("UPDATE keys SET used = TRUE WHERE key = %s;", (key,))
    conn.commit()

def wipe_all_keys():
    cur.execute("DELETE FROM keys;")
    conn.commit()

def get_active_keys():
    cur.execute("SELECT key FROM keys WHERE used = FALSE;")
    return [row[0] for row in cur.fetchall()]

def key_exists(key):
    cur.execute("SELECT used FROM keys WHERE key = %s;", (key,))
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]

keys = load_keys()

TOKEN = os.environ["TOKEN"]
ROBLOX_COOKIE = os.environ["ROBLOX_SECURITY"]
ROBLOX_GROUP_ID = os.environ["ROBLOX_GROUP_ID"]
ALLOWED_ROLE_ID = int(os.environ["ALLOWED_ROLE_ID"])

# ===== Discord bot setup =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Roblox API helper =====
def generate_key(length=16):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def get_user_id(username):
    url = "https://users.roblox.com/v1/usernames/users"
    resp = requests.post(url, json={"usernames": [username]})
    if resp.status_code == 200:
        data = resp.json()
        if data["data"]:
            return data["data"][0]["id"]
    return None

def roblox_request_with_xcsrf(method, url, json_data=None):
    headers = {
        "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
        "Content-Type": "application/json"
    }
    resp = requests.request(method, url, headers=headers, json=json_data)
    if resp.status_code == 403 and "X-CSRF-TOKEN" in resp.headers:
        headers["X-CSRF-TOKEN"] = resp.headers["X-CSRF-TOKEN"]
        resp = requests.request(method, url, headers=headers, json=json_data)
    return resp

def accept_group_request(user_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/join-requests/users/{user_id}"
    resp = roblox_request_with_xcsrf("POST", url)
    return resp.status_code == 200

def kick_from_group(user_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
    resp = roblox_request_with_xcsrf("DELETE", url)
    return resp.status_code == 200

def get_group_roles():
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles"
    resp = roblox_request_with_xcsrf("GET", url)
    if resp.status_code == 200:
        return resp.json()["roles"]
    return []

def get_user_role_in_group(user_id):
    url = f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    resp = roblox_request_with_xcsrf("GET", url)
    if resp.status_code == 200:
        for g in resp.json()["data"]:
            if str(g["group"]["id"]) == str(ROBLOX_GROUP_ID):
                return g["role"]
    return None

def set_user_role(user_id, new_role_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
    resp = roblox_request_with_xcsrf("PATCH", url, json_data={"roleId": new_role_id})
    return resp.status_code == 200

def promote_in_group(user_id):
    roles = get_group_roles()
    current = get_user_role_in_group(user_id)
    if not current: return False
    sorted_roles = sorted(roles, key=lambda r: r["rank"])
    for i, r in enumerate(sorted_roles):
        if r["id"] == current["id"] and i < len(sorted_roles)-1:
            return set_user_role(user_id, sorted_roles[i+1]["id"])
    return False

def demote_in_group(user_id):
    roles = get_group_roles()
    current = get_user_role_in_group(user_id)
    if not current: return False
    sorted_roles = sorted(roles, key=lambda r: r["rank"])
    for i, r in enumerate(sorted_roles):
        if r["id"] == current["id"] and i > 0:
            return set_user_role(user_id, sorted_roles[i-1]["id"])
    return False

def check_roblox_login():
    url = "https://auth.roblox.com/v2/logout"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"}
    resp = requests.post(url, headers=headers)
    return resp.status_code in [200, 403]

def has_allowed_role(ctx):
    return any(r.id == ALLOWED_ROLE_ID for r in ctx.author.roles)

# ===== Events =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if check_roblox_login():
        print("✅ Roblox cookie works and logged in!")
    else:
        print("❌ Roblox cookie is invalid!")

# ===== Commands =====
def embed_message(title, description, color=discord.Color.blue()):
    embed = discord.Embed(title=title, description=description, color=color)
    return embed

@bot.command()
async def generatekey(ctx, amount: int):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    new_keys = []
    for _ in range(amount):
        new_key = generate_key()
        while key_exists(new_key) is not None:
            new_key = generate_key()
        insert_key(new_key)
        new_keys.append(new_key)
    description = "\n".join([f"`{k}`" for k in new_keys])
    await ctx.author.send(embed=embed_message("Generated keys", description, discord.Color.green()))
    await ctx.reply(embed=embed_message("Done", "Keys har skickats till din DM.", discord.Color.green()))

@bot.command()
async def wipekeys(ctx):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    wipe_all_keys()
    await ctx.reply(embed=embed_message("Wiped", "Alla keys har raderats.", discord.Color.red()))

@bot.command()
async def activekeys(ctx):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    active = get_active_keys()
    if not active:
        await ctx.reply(embed=embed_message("Active Keys", "Det finns inga aktiva keys."))
    else:
        await ctx.reply(embed=embed_message("Active Keys", "\n".join(active)))

@bot.command()
async def cmds(ctx):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    description = (
        "!generatekey <amount>\n"
        "!wipekeys\n"
        "!activekeys\n"
        "!kick <username>\n"
        "!promote <username>\n"
        "!demote <username>\n"
        "!key <key> <username>\n"
        "!rank <username> <rank>\n"
        "!memberinfo <username>"
    )
    await ctx.reply(embed=embed_message("Commands", description))

@bot.command()
async def key(ctx, key: str, username: str):
    key_status = key_exists(key)
    if key_status is None:
        await ctx.reply(embed=embed_message("Error", "Ogiltig key."))
        return
    if key_status:
        await ctx.reply(embed=embed_message("Error", "Denna key är redan använd."))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.reply(embed=embed_message("Error", "Roblox användare hittades inte."))
        return
    if accept_group_request(user_id):
        set_key_used(key)
        await ctx.reply(embed=embed_message("Joined", f"{username} har blivit accepterad i gruppen!", discord.Color.green()))
    else:
        await ctx.reply(embed=embed_message("Error", "Misslyckades att acceptera join request."))

@bot.command()
async def kick(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.reply(embed=embed_message("Error", "Användare hittades inte."))
        return
    if kick_from_group(user_id):
        await ctx.reply(embed=embed_message("Kick", f"{username} har blivit kickad.", discord.Color.red()))
    else:
        await ctx.reply(embed=embed_message("Error", "Misslyckades att kicka."))

@bot.command()
async def promote(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.reply(embed=embed_message("Error", "Användare hittades inte."))
        return
    if promote_in_group(user_id):
        await ctx.reply(embed=embed_message("Promote", f"{username} har blivit befordrad.", discord.Color.green()))
    else:
        await ctx.reply(embed=embed_message("Error", "Misslyckades att befordra."))

@bot.command()
async def demote(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.reply(embed=embed_message("Error", "Användare hittades inte."))
        return
    if demote_in_group(user_id):
        await ctx.reply(embed=embed_message("Demote", f"{username} har blivit nedgraderad.", discord.Color.orange()))
    else:
        await ctx.reply(embed=embed_message("Error", "Misslyckades att nedgradera."))

@bot.command()
async def rank(ctx, username: str, *, rank: str):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.reply(embed=embed_message("Error", "Användare hittades inte."))
        return
    roles = get_group_roles()
    role_match = next((r for r in roles if r["name"].lower() == rank.lower()), None)
    if not role_match:
        await ctx.reply(embed=embed_message("Error", f"Rank '{rank}' hittades inte."))
        return
    if set_user_role(user_id, role_match["id"]):
        await ctx.reply(embed=embed_message("Rank", f"{username} har nu rank {rank}.", discord.Color.green()))
    else:
        await ctx.reply(embed=embed_message("Error", "Misslyckades att sätta rank."))

@bot.command()
async def memberinfo(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.reply(embed=embed_message("Error", "Du har inte behörighet."))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.reply(embed=embed_message("Error", "Användare hittades inte."))
        return
    role = get_user_role_in_group(user_id)
    if not role:
        await ctx.reply(embed=embed_message("Info", f"{username} är inte medlem i gruppen."))
        return
    await ctx.reply(embed=embed_message("Info", f"{username} har rollen {role['name']} (Rank {role['rank']})."))

bot.loop.create_task(keep_alive())
bot.run(TOKEN)
