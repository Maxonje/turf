import discord
from discord.ext import commands
from discord import app_commands
import random
import string
import os
import json
import requests
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

# ===== Configuration =====
KEYS_FILE = "keys.json"

def load_keys():
    if not os.path.isfile(KEYS_FILE):
        return {}
    with open(KEYS_FILE, "r") as f:
        return json.load(f)

def save_keys(keys):
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=4)

# Ladda keys vid start
keys = load_keys()

TOKEN = os.environ["TOKEN"]
ROBLOX_COOKIE = os.environ["ROBLOX_SECURITY"]
ROBLOX_GROUP_ID = os.environ["ROBLOX_GROUP_ID"]
ALLOWED_ROLE_ID = int(os.environ["ALLOWED_ROLE_ID"])

# ===== Discord bot setup =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # slash commands manager

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
    # Handle X-CSRF-Token requirement
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

# ===== Helper function =====
def has_allowed_role(interaction: discord.Interaction):
    roles_user = interaction.user.roles if hasattr(interaction.user, 'roles') else []
    return any(r.id == ALLOWED_ROLE_ID for r in roles_user)

# ===== Events =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if check_roblox_login():
        print("✅ Roblox cookie works and logged in!")
    else:
        print("❌ Roblox cookie is invalid!")
    await tree.sync()

# ===== Slash commands =====
@tree.command(name="generatekey", description="Generate keys for Roblox group")
@app_commands.describe(amount="Number of keys to generate")
async def generatekey(interaction: discord.Interaction, amount: int):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    global keys
    new_keys = []
    for _ in range(amount):
        new_key = generate_key()
        while new_key in keys:
            new_key = generate_key()
        keys[new_key] = False
        new_keys.append(new_key)
    save_keys(keys)
    embed = discord.Embed(title="Generated keys", color=discord.Color.green())
    for k in new_keys:
        embed.add_field(name="Key", value=f"```{k}```", inline=False)
    await interaction.user.send(embed=embed)
    await interaction.response.send_message("Keys have been generated and sent to your DM!", ephemeral=True)

@tree.command(name="wipekeys", description="Wipe all keys")
async def wipekeys(interaction: discord.Interaction):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    global keys
    keys = {}
    save_keys(keys)
    await interaction.response.send_message("All keys have been wiped!", ephemeral=True)

@tree.command(name="activekeys", description="Show active keys")
async def activekeys(interaction: discord.Interaction):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    active = [k for k, v in keys.items() if not v]
    if not active:
        await interaction.response.send_message("There are no active keys.", ephemeral=True)
    else:
        await interaction.response.send_message("**Active keys:**\n" + "\n".join(active), ephemeral=True)

@tree.command(name="cmds", description="List all commands")
async def cmds(interaction: discord.Interaction):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    text = (
        "**Commands:**\n"
        "/generatekey <amount>\n"
        "/wipekeys\n"
        "/activekeys\n"
        "/kick <username>\n"
        "/promote <username>\n"
        "/demote <username>\n"
        "/key <key> <username>\n"
        "/rank <username> <rank name>\n"
        "/memberinfo <username>"
    )
    await interaction.response.send_message(text, ephemeral=True)

@tree.command(name="key", description="Accept user into Roblox group with key")
@app_commands.describe(key="The key to use", username="Roblox username")
async def key(interaction: discord.Interaction, key: str, username: str):
    global keys
    if key not in keys:
        await interaction.response.send_message("Invalid key.", ephemeral=True)
        return
    if keys[key]:
        await interaction.response.send_message("This key has already been used.", ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message("The specified Roblox user was not found.", ephemeral=True)
        return
    if accept_group_request(user_id):
        keys[key] = True
        save_keys(keys)
        await interaction.response.send_message(f"**{username}** has successfully been accepted into the group!", ephemeral=False)
    else:
        await interaction.response.send_message("Failed to accept the join request.", ephemeral=True)

@tree.command(name="kick", description="Kick user from Roblox group")
@app_commands.describe(username="Roblox username")
async def kick(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message("User not found.", ephemeral=True)
        return
    if kick_from_group(user_id):
        await interaction.response.send_message(f"User {username} has been kicked.", ephemeral=False)
    else:
        await interaction.response.send_message("Failed to kick user.", ephemeral=True)

@tree.command(name="promote", description="Promote user in Roblox group")
@app_commands.describe(username="Roblox username")
async def promote(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message("User not found.", ephemeral=True)
        return
    if promote_in_group(user_id):
        await interaction.response.send_message(f"User {username} has been promoted.", ephemeral=False)
    else:
        await interaction.response.send_message("Failed to promote user.", ephemeral=True)

@tree.command(name="demote", description="Demote user in Roblox group")
@app_commands.describe(username="Roblox username")
async def demote(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message("User not found.", ephemeral=True)
        return
    if demote_in_group(user_id):
        await interaction.response.send_message(f"User {username} has been demoted.", ephemeral=False)
    else:
        await interaction.response.send_message("Failed to demote user.", ephemeral=True)

@tree.command(name="rank", description="Set user rank in Roblox group")
@app_commands.describe(username="Roblox username", rank_name="Rank name")
async def rank(interaction: discord.Interaction, username: str, rank_name: str):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message("User not found.", ephemeral=True)
        return
    roles = get_group_roles()
    target_role = next((r for r in roles if r["name"].lower() == rank_name.lower()), None)
    if not target_role:
        await interaction.response.send_message(f"Rank '{rank_name}' not found.", ephemeral=True)
        return
    if set_user_role(user_id, target_role["id"]):
        await interaction.response.send_message(f"User {username} has been set to rank {rank_name}.", ephemeral=False)
    else:
        await interaction.response.send_message("Failed to set rank.", ephemeral=True)

@tree.command(name="memberinfo", description="Get Roblox group member info")
@app_commands.describe(username="Roblox username")
async def memberinfo(interaction: discord.Interaction, username: str):
    if not has_allowed_role(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    user_id = get_user_id(username)
    if not user_id:
        await interaction.response.send_message("User not found.", ephemeral=True)
        return
    role = get_user_role_in_group(user_id)
    if role:
        await interaction.response.send_message(f"{username} is currently '{role['name']}' in the group.", ephemeral=False)
    else:
        await interaction.response.send_message(f"{username} is not in the group.", ephemeral=True)

keep_alive()
bot.run(TOKEN)
