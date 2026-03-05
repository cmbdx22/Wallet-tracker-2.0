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

# ── CREDIT EFFICIENT MODE ──────────────────────────
# Normal mode:  poll every 10s, fetch 10 tx per wallet
# Eco mode:     poll every 60s, fetch 5 tx per wallet
# Saves ~80% of Helius credits used by the tracker

NORMAL_POLL_INTERVAL = 10    # seconds between full polls
ECO_POLL_INTERVAL    = 60    # seconds between polls in eco mode
NORMAL_TX_FETCH      = 10    # transactions fetched per wallet per poll
ECO_TX_FETCH         = 5     # transactions fetched per wallet in eco mode

# Monthly credit estimates (rough)
# Normal:  ~72K credits/day for 70 wallets → blows free tier in 1-2 days
# Eco:     ~12K credits/day for 70 wallets → stays well within 100K/month
MONTHLY_FREE_CREDITS = 100_000

# Data persistence file
DATA_FILE = "wallet_data.json"

# Birdeye API for market cap data (free tier)
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens"
