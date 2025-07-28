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
    await interaction.response.defer(ephemeral=True)
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
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
        await interaction.followup.send(embed=embed_message("Done", "Keys have been sent to your DM!", discord.Color.green()), ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(embed=embed_message("Warning", "Couldn't DM you. Enable DMs!", discord.Color.red()), ephemeral=True)

@tree.command(name="wipekeys", description="Wipe all keys")
async def wipekeys(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    wipe_all_keys()
    await interaction.followup.send(embed=embed_message("Success", "All keys have been wiped!", discord.Color.green()), ephemeral=True)

@tree.command(name="activekeys", description="Show active keys")
async def activekeys(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    active = get_active_keys()
    if not active:
        await interaction.followup.send(embed=embed_message("Active Keys", "No active keys found.", discord.Color.gold()), ephemeral=True)
        return
    embed = discord.Embed(title="Active Keys", color=discord.Color.blue())
    for k in active:
        embed.add_field(name="Key", value=f"```{k}```", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="cmds", description="Show all commands")
async def cmds(interaction: discord.Interaction):
    await interaction.response.send_message(
        """**Available commands:**
/generatekey <amount> - Generate new keys (admin only)
/wipekeys - Delete all keys (admin only)
/activekeys - Show all active keys (admin only)
/key <key> <username> - Use a key to accept a user in Roblox group (one-time use)
/kick <username> - Kick a user from Roblox group
/rank <username> <rank> - Set rank of a user
/promote <username> - Promote a user
/demote <username> - Demote a user
/memberinfo <username> - Show info about a user
""",
        ephemeral=True
    )

@tree.command(name="key", description="Use a key to accept user in Roblox group")
async def key(interaction: discord.Interaction, key: str, username: str):
    await interaction.response.defer()
    # Check key exists and unused
    used_status = key_exists(key)
    if used_status is None:
        await interaction.followup.send(embed=embed_message("Error", "Key does not exist.", discord.Color.red()), ephemeral=True)
        return
    if used_status:
        await interaction.followup.send(embed=embed_message("Error", "Key has already been used.", discord.Color.red()), ephemeral=True)
        return

    # Get Roblox user id
    user_id = get_user_id(username)
    if not user_id:
        await interaction.followup.send(embed=embed_message("Error", f"Roblox user '{username}' not found.", discord.Color.red()), ephemeral=True)
        return

    # Accept join request in Roblox group
    success = accept_group_request(user_id)
    if success:
        set_key_used(key)
        await interaction.followup.send(embed=embed_message("Success", f"User '{username}' has been accepted to the group using key `{key}`.", discord.Color.green()))
        # Optional: log to a channel
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(f"User '{username}' accepted with key `{key}` by {interaction.user.mention}.")
    else:
        await interaction.followup.send(embed=embed_message("Error", f"Failed to accept user '{username}' to the group.", discord.Color.red()), ephemeral=True)

@tree.command(name="kick", description="Kick a user from Roblox group")
async def kick(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.followup.send(embed=embed_message("Error", f"Roblox user '{username}' not found.", discord.Color.red()), ephemeral=True)
        return
    success = kick_from_group(user_id)
    if success:
        await interaction.followup.send(embed=embed_message("Success", f"User '{username}' has been kicked from the group.", discord.Color.green()))
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(f"User '{username}' was kicked from group by {interaction.user.mention}.")
    else:
        await interaction.followup.send(embed=embed_message("Error", f"Failed to kick user '{username}'.", discord.Color.red()), ephemeral=True)

@tree.command(name="rank", description="Set rank of a user")
async def rank(interaction: discord.Interaction, username: str, rank: int):
    await interaction.response.defer()
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.followup.send(embed=embed_message("Error", f"Roblox user '{username}' not found.", discord.Color.red()), ephemeral=True)
        return
    roles = get_group_roles()
    # Find role by rank
    role_to_set = None
    for role in roles:
        if role["rank"] == rank:
            role_to_set = role
            break
    if not role_to_set:
        await interaction.followup.send(embed=embed_message("Error", f"No role found with rank {rank}.", discord.Color.red()), ephemeral=True)
        return
    success = set_user_role(user_id, role_to_set["id"])
    if success:
        await interaction.followup.send(embed=embed_message("Success", f"User '{username}' rank set to {role_to_set['name']} (Rank {rank}).", discord.Color.green()))
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(f"User '{username}' rank set to {role_to_set['name']} (Rank {rank}) by {interaction.user.mention}.")
    else:
        await interaction.followup.send(embed=embed_message("Error", f"Failed to set rank for user '{username}'.", discord.Color.red()), ephemeral=True)

@tree.command(name="promote", description="Promote a user")
async def promote(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.followup.send(embed=embed_message("Error", f"Roblox user '{username}' not found.", discord.Color.red()), ephemeral=True)
        return
    success = promote_in_group(user_id)
    if success:
        await interaction.followup.send(embed=embed_message("Success", f"User '{username}' promoted successfully.", discord.Color.green()))
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(f"User '{username}' was promoted by {interaction.user.mention}.")
    else:
        await interaction.followup.send(embed=embed_message("Error", f"Failed to promote user '{username}'.", discord.Color.red()), ephemeral=True)

@tree.command(name="demote", description="Demote a user")
async def demote(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    if not has_allowed_role(interaction.user):
        await interaction.followup.send(embed=embed_message("Permission Denied", "You do not have permission.", discord.Color.red()), ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.followup.send(embed=embed_message("Error", f"Roblox user '{username}' not found.", discord.Color.red()), ephemeral=True)
        return
    success = demote_in_group(user_id)
    if success:
        await interaction.followup.send(embed=embed_message("Success", f"User '{username}' demoted successfully.", discord.Color.green()))
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(f"User '{username}' was demoted by {interaction.user.mention}.")
    else:
        await interaction.followup.send(embed=embed_message("Error", f"Failed to demote user '{username}'.", discord.Color.red()), ephemeral=True)

@tree.command(name="memberinfo", description="Show info about a user")
async def memberinfo(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    user_id = get_user_id(username)
    if not user_id:
        await interaction.followup.send(embed=embed_message("Error", f"Roblox user '{username}' not found.", discord.Color.red()), ephemeral=True)
        return
    role = get_user_role_in_group(user_id)
    embed = discord.Embed(title=f"Member Info: {username}", color=discord.Color.blue())
    embed.add_field(name="UserID", value=str(user_id))
    if role:
        embed.add_field(name="Role", value=f"{role['name']} (Rank {role['rank']})")
    else:
        embed.add_field(name="Role", value="Not in group or role info unavailable")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ===== Run bot =====
keep_alive()
bot.run(TOKEN)
