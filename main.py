import discord
from discord.ext import commands
import random
import string
import os
import requests
import psycopg2
from flask import Flask
from threading import Thread

# Version for identifying script
SCRIPT_VERSION = "v2.0 - slash commands"

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
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# ===== Roblox API helper functions =====
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

# ===== Helper functions =====
def has_allowed_role(member: discord.Member):
    return any(role.id == ALLOWED_ROLE_ID for role in member.roles)

def embed_message(title, description, color=discord.Color.blue()):
    return discord.Embed(title=title, description=description, color=color)

# ===== Events =====
@bot.event
async def on_ready():
    await tree.sync()  # Sync slash commands to guild(s)
    print("===================================")
    print(f"🚀 Bot started! Running script version: {SCRIPT_VERSION}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    if check_roblox_login():
        print("✅ Roblox cookie works!")
    else:
        print("❌ Roblox cookie is invalid!")
    print("===================================")

    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"Bot restarted and is now running `{SCRIPT_VERSION}`")

# ===== Slash commands =====

@tree.command(name="generatekey", description="Generate new keys")
async def generatekey(interaction: discord.Interaction, amount: int):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    new_keys = []
    for _ in range(amount):
        new_key = generate_key()
        while key_exists(new_key) is not None:
            new_key = generate_key()
        insert_key(new_key)
        new_keys.append(new_key)
    embed = discord.Embed(title="Generated Keys", color=discord.Color.green())
    for k in new_keys:
        embed.add_field(name="Key", value=f"```{k}```", inline=False)
    try:
        await interaction.user.send(embed=embed)
        await interaction.response.send_message(embed=embed_message("Done", "Keys have been sent to your DM!", discord.Color.green()), ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_message("Warning", "Couldn't DM you. Enable DMs!", discord.Color.red()), ephemeral=True)

@tree.command(name="wipekeys", description="Wipe all keys")
async def wipekeys(interaction: discord.Interaction):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    wipe_all_keys()
    await interaction.response.send_message(embed=embed_message("Success", "All keys have been wiped!", discord.Color.green()), ephemeral=True)

@tree.command(name="activekeys", description="Show active keys")
async def activekeys(interaction: discord.Interaction):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    active = get_active_keys()
    if not active:
        await interaction.response.send_message(embed=embed_message("Active Keys", "There are no active keys.", discord.Color.blue()), ephemeral=True)
    else:
        embed = discord.Embed(title="Active Keys", color=discord.Color.blue())
        for k in active:
            embed.add_field(name="Key", value=k, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="cmds", description="Show commands list")
async def cmds(interaction: discord.Interaction):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    commands_text = (
        "/generatekey <amount>\n"
        "/wipekeys\n"
        "/activekeys\n"
        "/kick <username>\n"
        "/promote <username>\n"
        "/demote <username>\n"
        "/key <key> <username>\n"
        "/rank <username> <rank>\n"
        "/memberinfo <username>"
    )
    await interaction.response.send_message(embed=embed_message("Commands", commands_text, discord.Color.blue()), ephemeral=True)

@tree.command(name="key", description="Use a key to accept user into group")
async def key(interaction: discord.Interaction, key: str, username: str):
    key_status = key_exists(key)
    if key_status is None:
        await interaction.response.send_message(embed=embed_message("Error", "Invalid key.", discord.Color.red()), ephemeral=True)
        return
    if key_status:
        await interaction.response.send_message(embed=embed_message("Error", "This key has already been used.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()), ephemeral=True)
        return
    if accept_group_request(user_id):
        set_key_used(key)
        await interaction.response.send_message(embed=embed_message("Success", f"{username} has been accepted into the group using the key!", discord.Color.green()), ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed_message("Error", "Failed to accept user.", discord.Color.red()), ephemeral=True)

@tree.command(name="kick", description="Kick user from group")
async def kick(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()), ephemeral=True)
        return
    if kick_from_group(user_id):
        await interaction.response.send_message(embed=embed_message("Success", f"{username} was kicked from the group.", discord.Color.green()), ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed_message("Error", "Failed to kick user.", discord.Color.red()), ephemeral=True)

@tree.command(name="promote", description="Promote user in group")
async def promote(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()), ephemeral=True)
        return
    if promote_in_group(user_id):
        await interaction.response.send_message(embed=embed_message("Success", f"{username} was promoted.", discord.Color.green()), ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed_message("Error", "Failed to promote user.", discord.Color.red()), ephemeral=True)

@tree.command(name="demote", description="Demote user in group")
async def demote(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()), ephemeral=True)
        return
    if demote_in_group(user_id):
        await interaction.response.send_message(embed=embed_message("Success", f"{username} was demoted.", discord.Color.green()), ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed_message("Error", "Failed to demote user.", discord.Color.red()), ephemeral=True)

@tree.command(name="rank", description="Set user rank")
async def rank(interaction: discord.Interaction, username: str, rank: int):
    if not has_allowed_role(interaction.user):
        await interaction.response.send_message(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()), ephemeral=True)
        return
    roles = get_group_roles()
    desired_role = next((r for r in roles if r["rank"] == rank), None)
    if not desired_role:
        await interaction.response.send_message(embed=embed_message("Error", "Invalid rank.", discord.Color.red()), ephemeral=True)
        return
    if set_user_role(user_id, desired_role["id"]):
        await interaction.response.send_message(embed=embed_message("Success", f"{username}'s rank set to {rank}.", discord.Color.green()), ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed_message("Error", "Failed to set rank.", discord.Color.red()), ephemeral=True)

@tree.command(name="memberinfo", description="Get info about a group member")
async def memberinfo(interaction: discord.Interaction, username: str):
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()), ephemeral=True)
        return
    role = get_user_role_in_group(user_id)
    if not role:
        await interaction.response.send_message(embed=embed_message("Info", f"{username} is not in the group.", discord.Color.blue()), ephemeral=True)
        return
    await interaction.response.send_message(embed=embed_message(f"Member Info for {username}", f"Role: {role['name']}\nRank: {role['rank']}", discord.Color.green()), ephemeral=True)

# ===== Main =====
keep_alive()
bot.run(TOKEN)
