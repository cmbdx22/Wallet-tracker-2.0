import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from config import POLL_INTERVAL
from store import DataStore
from helius import HeliusClient

logger = logging.getLogger(__name__)

class WalletTracker:
    def __init__(self, app):
        self.app = app
        self.store = DataStore()
        self.helius = HeliusClient()
        self.running = False

        # Track last seen signature per wallet to avoid duplicate alerts
        self.last_signatures = {}  # wallet_address -> set of signatures

        # Track token buys: token_mint -> {wallet_address -> {sig, timestamp, mc}}
        self.token_buys = defaultdict(dict)

        # Time window to group buys (10 minutes)
        self.time_window = timedelta(minutes=10)

        # Alerts already sent to avoid duplicates
        self.sent_alerts = set()  # frozenset of (token_mint, wallet_addresses_tuple)

    async def start_tracking(self):
        self.running = True
        await self.helius.init_session()
        logger.info("Wallet tracker started.")
        while self.running:
            await self.poll_all_wallets()
            await asyncio.sleep(POLL_INTERVAL)

    async def stop(self):
        self.running = False
        await self.helius.close()

    async def poll_all_wallets(self):
        wallets = self.store.get_wallets()
        if not wallets:
            return

        # Fetch transactions for all wallets concurrently (batch of 10 at a time)
        addresses = list(wallets.keys())
        batch_size = 10
        tasks = []

        for i in range(0, len(addresses), batch_size):
            batch = addresses[i:i+batch_size]
            for addr in batch:
                tasks.append(self.process_wallet(addr))
            await asyncio.gather(*tasks, return_exceptions=True)
            tasks = []
            await asyncio.sleep(1)  # Rate limit between batches

        # After processing, check for multi-wallet alerts
        await self.check_alerts()

    async def process_wallet(self, wallet_address: str):
        try:
            txs = await self.helius.get_wallet_transactions(wallet_address)
            if not txs:
                return

            seen = self.last_signatures.get(wallet_address, set())

            for tx in txs:
                sig = tx.get("signature", "")
                if sig in seen:
                    continue

                swap = self.helius.parse_swap_transaction(tx)
                if not swap:
                    continue

                # New buy detected
                token_mint = swap["token_mint"]
                timestamp = swap["timestamp"]

                logger.info(f"[BUY] Wallet {wallet_address[:8]}... bought token {token_mint[:8]}...")

                self.token_buys[token_mint][wallet_address] = {
                    "signature": sig,
                    "timestamp": timestamp,
                    "wallet_address": wallet_address
                }

                seen.add(sig)

            # Keep only last 50 signatures to avoid memory bloat
            self.last_signatures[wallet_address] = set(list(seen)[-50:])

        except Exception as e:
            logger.error(f"Error processing wallet {wallet_address}: {e}")

    async def check_alerts(self):
        threshold = self.store.get_threshold()
        now = datetime.utcnow()
        wallets = self.store.get_wallets()

        for token_mint, buyers in list(self.token_buys.items()):
            # Filter buyers within time window
            recent_buyers = {
                addr: info for addr, info in buyers.items()
                if datetime.utcfromtimestamp(info["timestamp"]) > now - self.time_window
            }

            if len(recent_buyers) < threshold:
                continue

            # Check if we already alerted for this exact combination
            alert_key = frozenset(recent_buyers.keys())
            if alert_key in self.sent_alerts:
                continue

            # We have a new multi-wallet buy — fetch token info and alert
            self.sent_alerts.add(alert_key)
            await self.send_alert(token_mint, recent_buyers, wallets)

    async def send_alert(self, token_mint: str, buyers: dict, wallets: dict):
        # Get token market data
        market_data = await self.helius.get_market_cap(token_mint)
        
        ticker = market_data.get("ticker", "UNKNOWN")
        token_name = market_data.get("name", "Unknown Token")
        market_cap = market_data.get("market_cap", 0)
        price = market_data.get("price_usd", "0")
        dex = market_data.get("dex", "").upper()

        # Format market cap
        def fmt_mc(mc):
            if not mc:
                return "Unknown"
            mc = float(mc)
            if mc >= 1_000_000:
                return f"${mc/1_000_000:.2f}M"
            elif mc >= 1000:
                return f"${mc/1000:.1f}K"
            return f"${mc:.2f}"

        # Build wallet list with names
        wallet_lines = []
        for addr, info in buyers.items():
            wallet_info = wallets.get(addr, {})
            name = wallet_info.get("name", addr[:8] + "...")
            wallet_lines.append(f"  • {name}")

        wallets_str = "\n".join(wallet_lines)
        mc_str = fmt_mc(market_cap)
        count = len(buyers)

        message = (
            f"🚨 *MULTI-WALLET BUY ALERT* 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"*{count} wallets* bought the same token!\n\n"
            f"🪙 *Token:* {token_name} (${ticker})\n"
            f"📋 *CA:* `{token_mint}`\n"
            f"💰 *Market Cap:* {mc_str}\n"
            f"💵 *Price:* ${price}\n"
            f"🏦 *DEX:* {dex if dex else 'Solana DEX'}\n\n"
            f"👛 *Wallets that bought:*\n{wallets_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        chat_ids = self.store.get_chat_ids()
        for chat_id in chat_ids:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown"
                )
                logger.info(f"Alert sent to chat {chat_id} for token {ticker}")
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
