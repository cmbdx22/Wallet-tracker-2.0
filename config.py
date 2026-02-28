import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "YOUR_HELIUS_API_KEY")
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_API_BASE = "https://api.helius.xyz/v0"

# Minimum wallets that must buy the same coin to trigger alert
DEFAULT_ALERT_THRESHOLD = 2  # Alert when 2+ wallets buy same token

# How often to poll (seconds) - Helius webhooks are preferred but polling as fallback
POLL_INTERVAL = 10

# Max wallets supported (minimum 70 as required)
MAX_WALLETS = 200
MIN_WALLETS_REQUIRED = 70

# Data persistence file
DATA_FILE = "wallet_data.json"

# Birdeye API for market cap data (free tier)
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens"
