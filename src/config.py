# config.py

import os
from dotenv import load_dotenv

# Local me .env se load karega (Render pe env dashboard kaam karega)
load_dotenv()

# ------------------------------
# DATABASE CONFIG (Tortoise ORM)
# ------------------------------
TORTOISE = {
    "connections": {
        "default": os.getenv("DATABASE_URL")  # Render ke env me set hoga
    },
    "apps": {
        "models": {
            "models": ["models", "models.misc", "aerich.models"],
            "default_connection": "default",
        },
    },
}

POSTGRESQL = {}

# ------------------------------
# COGS / EXTENSIONS
# ------------------------------
EXTENSIONS = (
    "cogs.mod",
    "cogs.events",
    "cogs.esports",
    "cogs.premium",
    "cogs.quomisc",
    "cogs.reminder",
    "cogs.utility",
    "cogs.waiting"
)

# ------------------------------
# DISCORD BOT SETTINGS
# ------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
COLOR = int(os.getenv("COLOR", "0xFF0000"), 16)
FOOTER = os.getenv("FOOTER", "ScrimX is lub!")
PREFIX = os.getenv("PREFIX", "x")
SERVER_ID = int(os.getenv("SERVER_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SERVER_LINK = os.getenv("SERVER_LINK")
BOT_INVITE = os.getenv("BOT_INVITE")
WEBSITE = os.getenv("WEBSITE")
REPOSITORY = os.getenv("REPOSITORY")
DEVS = ()
PAY_LINK= os.getenv("PAY_LINK")

# ------------------------------
# FASTAPI SETTINGS
# ------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PRIME_EMOJI = os.getenv("PRIME_EMOJI", "☑️")

# ------------------------------
# LOG FILE PATHS / WEBHOOKS
# ------------------------------
PRO_LINK = os.getenv("PRO_LINK")
SHARD_LOG = os.getenv("SHARD_LOG", "")
ERROR_LOG = os.getenv("ERROR_LOG", "")
PUBLIC_LOG = os.getenv("PUBLIC_LOG")
