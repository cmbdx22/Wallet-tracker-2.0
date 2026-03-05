import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import (
    NORMAL_POLL_INTERVAL, ECO_POLL_INTERVAL,
    NORMAL_TX_FETCH, ECO_TX_FETCH
)
from store import DataStore
from helius import HeliusClient

logger = logging.getLogger(__name__)

class WalletTracker:
    def __init__(self, app):
        self.app             = app
        self.store           = DataStore()
        self.helius          = HeliusClient()
        self.running         = False

        # wallet_address -> set of signatures already processed
        # Only stores last 100 per wallet to prevent unbounded memory growth
        self.last_signatures = {}

        # token_mint -> { wallet_address -> {sig, timestamp, sol_spent} }
        # Persists across polls — cleared of old entries every cycle
        self.token_buys = defaultdict(dict)

        # How long a buy stays relevant for matching
        self.time_window = timedelta(minutes=15)

        # (chat_id, frozenset of buyer addresses) -> True
        # Prevents sending duplicate alerts for same group of buyers
        self.sent_alerts = defaultdict(set)

    def _poll_interval(self):
        return ECO_POLL_INTERVAL if self.store.any_eco_mode() else NORMAL_POLL_INTERVAL

    def _tx_limit(self):
        return ECO_TX_FETCH if self.store.any_eco_mode() else NORMAL_TX_FETCH

    async def start_tracking(self):
        self.running = True
        await self.helius.init_session()
        logger.info("Tracker started.")

        # Seed last_signatures on first boot so we don't
        # alert on old buys that happened before the bot started
        await self._seed_signatures()

        while self.running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"Poll cycle error: {e}", exc_info=True)
            await asyncio.sleep(self._poll_interval())

    async def stop(self):
        self.running = False
        await self.helius.close()

    async def _seed_signatures(self):
        """
        On first boot, fetch current signatures for every wallet and mark them
        as already seen. This prevents alerting on historic buys.
        Only runs once at startup.
        """
        addresses = list(self.store.get_all_addresses())
        if not addresses:
            return
        logger.info(f"Seeding signatures for {len(addresses)} wallets...")
        for addr in addresses:
            try:
                txs = await self.helius.get_wallet_transactions(addr, limit=10)
                sigs = {tx.get("signature", "") for tx in txs if tx.get("signature")}
                self.last_signatures[addr] = sigs
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"Seed error {addr[:8]}: {e}")
        logger.info("Seeding complete.")

    async def _poll_cycle(self):
        """One full poll of all wallets, then check for matches."""
        addresses = list(self.store.get_all_addresses())
        if not addresses:
            return

        # Poll in batches of 10 concurrently
        for i in range(0, len(addresses), 10):
            batch = addresses[i:i+10]
            await asyncio.gather(
                *[self._process_wallet(addr) for addr in batch],
                return_exceptions=True
            )
            await asyncio.sleep(0.5)

        # Clean stale entries older than time_window
        self._cleanup_old_buys()

        # Check if any token was bought by enough wallets
        await self._check_alerts()

    async def _process_wallet(self, address: str):
        """Fetch new transactions for one wallet and record any buys."""
        try:
            txs = await self.helius.get_wallet_transactions(address, limit=self._tx_limit())
            if not txs:
                return

            self.store.add_credits_used(1)
            seen = self.last_signatures.get(address, set())
            new_sigs = set()

            for tx in txs:
                sig = tx.get("signature", "")
                if not sig or sig in seen:
                    continue

                new_sigs.add(sig)
                swap = self.helius.parse_swap_transaction(tx)
                if not swap:
                    continue

                mint = swap["token_mint"]
                ts   = swap["timestamp"]

                # Ignore buys older than our time window — stale data
                age = datetime.utcnow() - datetime.utcfromtimestamp(ts)
                if age > self.time_window:
                    continue

                logger.info(
                    f"[BUY] {address[:8]} -> {mint[:8]} "
                    f"via {swap.get('source','?')} "
                    f"({swap.get('sol_spent',0)/1e9:.3f} SOL)"
                )

                self.token_buys[mint][address] = {
                    "signature": sig,
                    "timestamp": ts,
                    "sol_spent": swap.get("sol_spent", 0),
                }

            # Add new sigs, keep only last 100 to bound memory
            all_seen = seen | new_sigs
            self.last_signatures[address] = set(list(all_seen)[-100:])

        except Exception as e:
            logger.error(f"_process_wallet {address[:8]}: {e}")

    def _cleanup_old_buys(self):
        """Remove buy records older than time_window to keep memory clean."""
        cutoff = datetime.utcnow() - self.time_window
        for mint in list(self.token_buys.keys()):
            self.token_buys[mint] = {
                addr: info for addr, info in self.token_buys[mint].items()
                if datetime.utcfromtimestamp(info["timestamp"]) > cutoff
            }
            if not self.token_buys[mint]:
                del self.token_buys[mint]

    async def _check_alerts(self):
        """For every token with recent buys, check if threshold met per chat."""
        now = datetime.utcnow()

        for token_mint, buyers in list(self.token_buys.items()):
            # Only look at buys within the time window
            recent = {
                addr: info for addr, info in buyers.items()
                if datetime.utcfromtimestamp(info["timestamp"]) > now - self.time_window
            }
            if not recent:
                continue

            # Check each chat independently
            for chat_id_str, chat_data in self.store.data["chats"].items():
                chat_id      = int(chat_id_str)
                chat_wallets = chat_data.get("wallets", {})
                threshold    = chat_data.get("threshold", 2)

                # Which of this chat's wallets bought this token recently
                chat_buyers = {
                    addr: info for addr, info in recent.items()
                    if addr in chat_wallets
                }

                if len(chat_buyers) < threshold:
                    continue

                # Deduplicate — don't alert same set of buyers twice
                alert_key = frozenset(chat_buyers.keys())
                if alert_key in self.sent_alerts[chat_id]:
                    continue

                self.sent_alerts[chat_id].add(alert_key)
                await self._send_alert(chat_id, token_mint, chat_buyers, chat_wallets)

    async def _send_alert(self, chat_id: int, token_mint: str,
                           buyers: dict, chat_wallets: dict):
        """Format and send the Ray Gold style alert with quick-buy buttons."""
        market  = await self.helius.get_market_cap(token_mint)
        ticker  = market.get("ticker", "???")
        mc      = market.get("market_cap", 0)
        price   = market.get("price_usd", "0")
        dex     = market.get("dex", "").lower()

        def fmt_mc(v):
            if not v: return "-"
            v = float(v)
            if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
            if v >= 1_000:     return f"${v/1_000:.1f}K"
            return f"${v:.0f}"

        def fmt_sol(lamports):
            if not lamports: return ""
            sol = lamports / 1e9
            return f" ({sol:.3f} SOL)" if sol > 0.0001 else ""

        # Time since earliest buy in this group
        earliest = min(info["timestamp"] for info in buyers.values())
        secs     = int(datetime.utcnow().timestamp() - earliest)
        seen_str = f"{secs}s" if secs < 60 else f"{secs//60}m{secs%60}s"

        dex_label = {
            "raydium":  "Raydium",
            "jupiter":  "Jupiter",
            "orca":     "Orca",
            "pumpfun":  "Pump.fun",
            "pump-fun": "Pump.fun",
        }.get(dex, dex.upper() if dex else "DEX")

        eco_tag = "  \U0001f33f" if self.store.any_eco_mode() else ""

        wallet_lines = []
        for addr, info in buyers.items():
            name = chat_wallets.get(addr, {}).get("name", addr[:8] + "...")
            wallet_lines.append(f"\U0001f48e *{name}*{fmt_sol(info.get('sol_spent', 0))}")

        text = (
            f"\U0001f6a8  *{len(buyers)} WALLETS BOUGHT*{eco_tag}\n"
            f"\n"
            + "\n".join(wallet_lines) +
            f"\n\n"
            f"\U0001f4a0  *#{ticker}*  |  MC: *{fmt_mc(mc)}*  |  Seen: *{seen_str}*\n"
            f"`{token_mint}`\n"
            f"\n"
            f"\U0001f4b5 Price    *${price}*\n"
            f"\U0001f3e6 DEX      *{dex_label}*"
        )

        trojan_url = f"https://t.me/solana_trojanbot?start=r-buy_{token_mint}"
        gmgn_url   = f"https://gmgn.ai/sol/token/{token_mint}"
        ds_url     = f"https://dexscreener.com/solana/{token_mint}"
        pump_url   = f"https://pump.fun/{token_mint}"
        bullx_url  = f"https://bullx.io/terminal?chainId=1399811149&address={token_mint}"
        axiom_url  = f"https://axiom.trade/meme/{token_mint}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"\U0001f434 Trojan: #{ticker}", url=trojan_url),
                InlineKeyboardButton(f"\U0001f98e GMGN: #{ticker}",   url=gmgn_url),
            ],
            [
                InlineKeyboardButton(f"\U0001f4ca Chart",             url=ds_url),
                InlineKeyboardButton(f"\u26a1 BullX: #{ticker}",      url=bullx_url),
            ],
            [
                InlineKeyboardButton(f"\U0001f53a Axiom: #{ticker}",  url=axiom_url),
                InlineKeyboardButton(f"\U0001f7e3 Pump: #{ticker}",   url=pump_url),
            ],
        ])

        try:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            logger.info(f"Alert sent -> {chat_id} | {ticker} | {len(buyers)} buyers")
        except Exception as e:
            logger.error(f"Alert send failed -> {chat_id}: {e}")
