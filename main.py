import discord
from discord.ext import commands
import random
import string
import os
import psycopg2
from flask import Flask
from threading import Thread
import aiohttp
import asyncio
from datetime import datetime

SCRIPT_VERSION = "v2.1 - snygga embeds & snabbare svar"

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

def key_exists(key):
    cur.execute("SELECT used FROM keys WHERE key = %s;", (key,))
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]

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

TOKEN = os.environ["TOKEN"]
ROBLOX_COOKIE = os.environ["ROBLOX_SECURITY"]
ROBLOX_GROUP_ID = os.environ["ROBLOX_GROUP_ID"]
ALLOWED_ROLE_ID = int(os.environ["ALLOWED_ROLE_ID"])
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0))

# ===== Discord bot setup =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Hjälpfunktioner för snygga embeds =====
def make_embed(title, description=None, color=discord.Color.blurple(), fields=None, thumbnail=None, footer=True):
    embed = discord.Embed(title=title, description=description, color=color)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if footer:
        embed.set_footer(text=f"Script version: {SCRIPT_VERSION} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    return embed

# ===== Asynkrona Roblox-API-anrop med aiohttp =====

async def get_user_id(session, username):
    url = "https://users.roblox.com/v1/usernames/users"
    async with session.post(url, json={"usernames": [username]}) as resp:
        if resp.status == 200:
            data = await resp.json()
            if data["data"]:
                return data["data"][0]["id"]
    return None

async def roblox_request_with_xcsrf(session, method, url, json_data=None):
    headers = {
        "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
        "Content-Type": "application/json"
    }
    async with session.request(method, url, headers=headers, json=json_data) as resp:
        if resp.status == 403 and "X-CSRF-TOKEN" in resp.headers:
            headers["X-CSRF-TOKEN"] = resp.headers["X-CSRF-TOKEN"]
            async with session.request(method, url, headers=headers, json=json_data) as resp2:
                return resp2
        return resp

async def accept_group_request(session, user_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/join-requests/users/{user_id}"
    resp = await roblox_request_with_xcsrf(session, "POST", url)
    return resp.status == 200

async def kick_from_group(session, user_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
    resp = await roblox_request_with_xcsrf(session, "DELETE", url)
    return resp.status == 200

async def get_group_roles(session):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles"
    resp = await roblox_request_with_xcsrf(session, "GET", url)
    if resp.status == 200:
        data = await resp.json()
        return data["roles"]
    return []

async def get_user_role_in_group(session, user_id):
    url = f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    resp = await roblox_request_with_xcsrf(session, "GET", url)
    if resp.status == 200:
        data = await resp.json()
        for g in data["data"]:
            if str(g["group"]["id"]) == str(ROBLOX_GROUP_ID):
                return g["role"]
    return None

async def set_user_role(session, user_id, new_role_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
    resp = await roblox_request_with_xcsrf(session, "PATCH", url, json_data={"roleId": new_role_id})
    return resp.status == 200

async def promote_in_group(session, user_id):
    roles = await get_group_roles(session)
    current = await get_user_role_in_group(session, user_id)
    if not current: return False
    sorted_roles = sorted(roles, key=lambda r: r["rank"])
    for i, r in enumerate(sorted_roles):
        if r["id"] == current["id"] and i < len(sorted_roles)-1:
            return await set_user_role(session, user_id, sorted_roles[i+1]["id"])
    return False

async def demote_in_group(session, user_id):
    roles = await get_group_roles(session)
    current = await get_user_role_in_group(session, user_id)
    if not current: return False
    sorted_roles = sorted(roles, key=lambda r: r["rank"])
    for i, r in enumerate(sorted_roles):
        if r["id"] == current["id"] and i > 0:
            return await set_user_role(session, user_id, sorted_roles[i-1]["id"])
    return False

async def check_roblox_login():
    url = "https://auth.roblox.com/v2/logout"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers) as resp:
            return resp.status in [200, 403]

# ===== Helper function för permissions =====
def has_allowed_role(ctx):
    return any(r.id == ALLOWED_ROLE_ID for r in ctx.author.roles)

# ===== Events =====
@bot.event
async def on_ready():
    print("===================================")
    print(f"🚀 Bot started! Running script version: {SCRIPT_VERSION}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logged_in = await check_roblox_login()
    print("✅ Roblox cookie works!" if logged_in else "❌ Roblox cookie is invalid!")
    print("===================================")

    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"Bot restarted and is now running `{SCRIPT_VERSION}`")

# ===== Commands =====

@bot.command()
async def generatekey(ctx, amount: int):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    new_keys = []
    for _ in range(amount):
        new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        while key_exists(new_key) is not None:
            new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        insert_key(new_key)
        new_keys.append(new_key)
    embed = make_embed(f"Generated {amount} Keys", color=discord.Color.green())
    for k in new_keys:
        embed.add_field(name="Key", value=f"```{k}```", inline=False)
    try:
        await ctx.author.send(embed=embed)
        await ctx.send(embed=make_embed("Done", "Keys have been sent to your DM!", discord.Color.green()))
    except discord.Forbidden:
        await ctx.send(embed=make_embed("Warning", "Couldn't DM you. Enable DMs!", discord.Color.red()))

@bot.command()
async def wipekeys(ctx):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    wipe_all_keys()
    await ctx.send(embed=make_embed("Success", "All keys have been wiped!", discord.Color.green()))

@bot.command()
async def activekeys(ctx):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    active = get_active_keys()
    if not active:
        await ctx.send(embed=make_embed("Active Keys", "There are no active keys.", discord.Color.blue()))
    else:
        embed = make_embed("Active Keys", color=discord.Color.blue())
        for k in active:
            embed.add_field(name="Key", value=k, inline=False)
        await ctx.send(embed=embed)

@bot.command()
async def cmds(ctx):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    commands_text = (
        "**Commands:**\n"
        "`!generatekey <amount>`\n"
        "`!wipekeys`\n"
        "`!activekeys`\n"
        "`!kick <username>`\n"
        "`!promote <username>`\n"
        "`!demote <username>`\n"
        "`!key <key> <username>`\n"
        "`!rank <username> <rank>`\n"
        "`!memberinfo <username>`"
    )
    await ctx.send(embed=make_embed("Available Commands", commands_text, discord.Color.blue()))

@bot.command()
async def key(ctx, key: str, username: str):
    key_status = key_exists(key)
    if key_status is None:
        await ctx.send(embed=make_embed("Error", "Invalid key.", discord.Color.red()))
        return
    if key_status:
        await ctx.send(embed=make_embed("Error", "This key is already used.", discord.Color.red()))
        return
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return

    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await ctx.send(embed=make_embed("Error", "Roblox user not found.", discord.Color.red()))
            return
        success = await accept_group_request(session, user_id)
        if success:
            set_key_used(key)
            await ctx.send(embed=make_embed("Success", f"{username} har accepterats i gruppen!", discord.Color.green()))
        else:
            await ctx.send(embed=make_embed("Error", "Failed to accept group request.", discord.Color.red()))

@bot.command()
async def kick(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await ctx.send(embed=make_embed("Error", "Roblox user not found.", discord.Color.red()))
            return
        success = await kick_from_group(session, user_id)
        if success:
            await ctx.send(embed=make_embed("Success", f"{username} har blivit kickad från gruppen.", discord.Color.green()))
        else:
            await ctx.send(embed=make_embed("Error", "Det gick inte att kicka användaren.", discord.Color.red()))

@bot.command()
async def promote(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await ctx.send(embed=make_embed("Error", "Roblox user not found.", discord.Color.red()))
            return
        success = await promote_in_group(session, user_id)
        if success:
            await ctx.send(embed=make_embed("Success", f"{username} har blivit uppgraderad.", discord.Color.green()))
        else:
            await ctx.send(embed=make_embed("Error", "Det gick inte att uppgradera användaren.", discord.Color.red()))

@bot.command()
async def demote(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await ctx.send(embed=make_embed("Error", "Roblox user not found.", discord.Color.red()))
            return
        success = await demote_in_group(session, user_id)
        if success:
            await ctx.send(embed=make_embed("Success", f"{username} har blivit nedgraderad.", discord.Color.green()))
        else:
            await ctx.send(embed=make_embed("Error", "Det gick inte att nedgradera användaren.", discord.Color.red()))

@bot.command()
async def memberinfo(ctx, username: str):
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await ctx.send(embed=make_embed("Error", "Roblox user not found.", discord.Color.red()))
            return
        url = f"https://users.roblox.com/v1/users/{user_id}"
        async with session.get(url) as resp:
            if resp.status != 200:
                await ctx.send(embed=make_embed("Error", "Failed to fetch user info.", discord.Color.red()))
                return
            data = await resp.json()
    name = data.get("name", "N/A")
    display_name = data.get("displayName", "N/A")
    description = data.get("description") or "Ingen beskrivning"
    created = data.get("created", "N/A")

    embed = make_embed(
        f"Info för {name}",
        fields=[
            ("Display Name", display_name, True),
            ("Description", description, False),
            ("Created", created, True),
        ],
        color=discord.Color.blue(),
        thumbnail=f"https://www.roblox.com/headshot-thumbnail/image?userId={user_id}&width=48&height=48&format=png"
    )
    await ctx.send(embed=embed)

@bot.command()
async def rank(ctx, username: str, *, rank_name: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=make_embed("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await ctx.send(embed=make_embed("Error", "Roblox user not found.", discord.Color.red()))
            return
        roles = await get_group_roles(session)
        # Sök efter rollen med namn (case insensitive)
        found_role = None
        for role in roles:
            if role["name"].lower() == rank_name.lower():
                found_role = role
                break
        if not found_role:
            await ctx.send(embed=make_embed("Error", f"Rank '{rank_name}' hittades inte.", discord.Color.red()))
            return
        success = await set_user_role(session, user_id, found_role["id"])
        if success:
            await ctx.send(embed=make_embed("Success", f"{username} har nu rollen '{rank_name}'.", discord.Color.green()))
        else:
            await ctx.send(embed=make_embed("Error", "Kunde inte sätta rollen.", discord.Color.red()))

# ===== Keep alive & run =====
keep_alive()
bot.run(TOKEN)
