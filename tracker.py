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

        # Last seen signatures per wallet
        self.last_signatures = {}

        # token_mint -> { wallet_address -> {sig, timestamp} }
        self.token_buys = defaultdict(dict)

        # Time window to group buys
        self.time_window = timedelta(minutes=10)

        # Sent alerts: per chat — set of frozensets
        # chat_id -> set of frozenset(wallet_addresses)
        self.sent_alerts = defaultdict(set)

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
        # Poll every unique address across all chats
        all_addresses = self.store.get_all_addresses()
        if not all_addresses:
            return

        addresses = list(all_addresses)
        batch_size = 10

        for i in range(0, len(addresses), batch_size):
            batch = addresses[i:i + batch_size]
            tasks = [self.process_wallet(addr) for addr in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(1)

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

                token_mint = swap["token_mint"]
                timestamp = swap["timestamp"]

                logger.info(f"[BUY] {wallet_address[:8]}... bought {token_mint[:8]}...")

                self.token_buys[token_mint][wallet_address] = {
                    "signature": sig,
                    "timestamp": timestamp,
                    "wallet_address": wallet_address
                }
                seen.add(sig)

            self.last_signatures[wallet_address] = set(list(seen)[-50:])

        except Exception as e:
            logger.error(f"Error processing wallet {wallet_address}: {e}")

    async def check_alerts(self):
        now = datetime.utcnow()

        for token_mint, buyers in list(self.token_buys.items()):
            # Filter to buys within the time window
            recent_buyers = {
                addr: info for addr, info in buyers.items()
                if datetime.utcfromtimestamp(info["timestamp"]) > now - self.time_window
            }

            if not recent_buyers:
                continue

            # For each chat, check if enough of THEIR wallets bought this token
            for chat_id_str, chat_data in self.store.data["chats"].items():
                chat_id = int(chat_id_str)
                chat_wallets = chat_data.get("wallets", {})
                threshold = chat_data.get("threshold", 2)

                # Which recent buyers belong to THIS chat
                chat_buyers = {
                    addr: info for addr, info in recent_buyers.items()
                    if addr in chat_wallets
                }

                if len(chat_buyers) < threshold:
                    continue

                # Check if we already sent this alert to this chat
                alert_key = frozenset(chat_buyers.keys())
                if alert_key in self.sent_alerts[chat_id]:
                    continue

                self.sent_alerts[chat_id].add(alert_key)
                await self.send_alert(chat_id, token_mint, chat_buyers, chat_wallets)

    async def send_alert(self, chat_id: int, token_mint: str,
                          buyers: dict, chat_wallets: dict):
        market_data = await self.helius.get_market_cap(token_mint)

        ticker = market_data.get("ticker", "UNKNOWN")
        token_name = market_data.get("name", "Unknown Token")
        market_cap = market_data.get("market_cap", 0)
        price = market_data.get("price_usd", "0")
        dex = market_data.get("dex", "").upper()

        def fmt_mc(mc):
            if not mc:
                return "Unknown"
            mc = float(mc)
            if mc >= 1_000_000:
                return f"${mc/1_000_000:.2f}M"
            elif mc >= 1000:
                return f"${mc/1000:.1f}K"
            return f"${mc:.2f}"

        wallet_lines = []
        for addr in buyers:
            name = chat_wallets.get(addr, {}).get("name", addr[:8] + "...")
            wallet_lines.append(f"  • {name}")

        message = (
            f"🚨 *MULTI-WALLET BUY ALERT* 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"*{len(buyers)} wallets* bought the same token!\n\n"
            f"🪙 *Token:* {token_name} (${ticker})\n"
            f"📋 *CA:* `{token_mint}`\n"
            f"💰 *Market Cap:* {fmt_mc(market_cap)}\n"
            f"💵 *Price:* ${price}\n"
            f"🏦 *DEX:* {dex if dex else 'Solana DEX'}\n\n"
            f"👛 *Wallets that bought:*\n"
            + "\n".join(wallet_lines) +
            f"\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        try:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown"
            )
            logger.info(f"Alert sent to chat {chat_id} for {ticker}")
        except Exception as e:
            logger.error(f"Failed to send alert to {chat_id}: {e}")
