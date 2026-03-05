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
        self.last_signatures = {}
        self.token_buys      = defaultdict(dict)
        self.time_window     = timedelta(minutes=10)
        self.sent_alerts     = defaultdict(set)

    def _get_poll_interval(self):
        return ECO_POLL_INTERVAL if self.store.any_eco_mode() else NORMAL_POLL_INTERVAL

    def _get_tx_limit(self):
        return ECO_TX_FETCH if self.store.any_eco_mode() else NORMAL_TX_FETCH

    async def start_tracking(self):
        self.running = True
        await self.helius.init_session()
        logger.info("Wallet tracker started.")
        while self.running:
            await self.poll_all_wallets()
            await asyncio.sleep(self._get_poll_interval())

    async def stop(self):
        self.running = False
        await self.helius.close()

    async def poll_all_wallets(self):
        addresses = list(self.store.get_all_addresses())
        if not addresses:
            return
        for i in range(0, len(addresses), 10):
            batch = addresses[i:i+10]
            await asyncio.gather(
                *[self.process_wallet(a, self._get_tx_limit()) for a in batch],
                return_exceptions=True
            )
            await asyncio.sleep(1)
        await self.check_alerts()

    async def process_wallet(self, wallet_address: str, tx_limit: int = 10):
        try:
            txs = await self.helius.get_wallet_transactions(wallet_address, limit=tx_limit)
            if not txs:
                return
            self.store.add_credits_used(1)
            seen = self.last_signatures.get(wallet_address, set())
            for tx in txs:
                sig = tx.get("signature", "")
                if sig in seen:
                    continue
                swap = self.helius.parse_swap_transaction(tx)
                if not swap:
                    continue
                mint = swap["token_mint"]
                logger.info(f"[BUY] {wallet_address[:8]}... -> {mint[:8]}...")
                self.token_buys[mint][wallet_address] = {
                    "signature":      sig,
                    "timestamp":      swap["timestamp"],
                    "sol_spent":      swap.get("sol_spent", 0),
                    "wallet_address": wallet_address
                }
                seen.add(sig)
            self.last_signatures[wallet_address] = set(list(seen)[-50:])
        except Exception as e:
            logger.error(f"process_wallet {wallet_address[:8]}: {e}")

    async def check_alerts(self):
        now = datetime.utcnow()
        for token_mint, buyers in list(self.token_buys.items()):
            recent = {
                addr: info for addr, info in buyers.items()
                if datetime.utcfromtimestamp(info["timestamp"]) > now - self.time_window
            }
            if not recent:
                continue
            for chat_id_str, chat_data in self.store.data["chats"].items():
                chat_id      = int(chat_id_str)
                chat_wallets = chat_data.get("wallets", {})
                threshold    = chat_data.get("threshold", 2)
                chat_buyers  = {a: i for a, i in recent.items() if a in chat_wallets}
                if len(chat_buyers) < threshold:
                    continue
                alert_key = frozenset(chat_buyers.keys())
                if alert_key in self.sent_alerts[chat_id]:
                    continue
                self.sent_alerts[chat_id].add(alert_key)
                await self.send_alert(chat_id, token_mint, chat_buyers, chat_wallets)

    async def send_alert(self, chat_id: int, token_mint: str,
                          buyers: dict, chat_wallets: dict):
        market_data = await self.helius.get_market_cap(token_mint)

        ticker     = market_data.get("ticker", "???")
        market_cap = market_data.get("market_cap", 0)
        price      = market_data.get("price_usd", "0")
        dex        = market_data.get("dex", "").lower()

        def fmt_mc(mc):
            if not mc: return "-"
            mc = float(mc)
            if mc >= 1_000_000: return f"${mc/1_000_000:.2f}M"
            if mc >= 1_000:     return f"${mc/1_000:.1f}K"
            return f"${mc:.0f}"

        def fmt_sol(lamports):
            if not lamports: return ""
            sol = lamports / 1e9
            return f" ({sol:.2f} SOL)" if sol > 0.001 else ""

        timestamps = [info["timestamp"] for info in buyers.values()]
        earliest   = min(timestamps)
        seen_secs  = int(datetime.utcnow().timestamp() - earliest)
        seen_str   = f"{seen_secs}s" if seen_secs < 60 else f"{seen_secs//60}m{seen_secs%60}s"

        dex_label = {
            "raydium":  "Raydium",
            "jupiter":  "Jupiter",
            "orca":     "Orca",
            "pumpfun":  "Pump.fun",
            "pump-fun": "Pump.fun",
        }.get(dex, dex.upper() if dex else "Solana DEX")

        wallet_lines = []
        for addr, info in buyers.items():
            name     = chat_wallets.get(addr, {}).get("name", addr[:8] + "...")
            sol_note = fmt_sol(info.get("sol_spent", 0))
            wallet_lines.append(f"\U0001f48e *{name}*{sol_note}")

        eco_tag = "  \U0001f33f" if self.store.any_eco_mode() else ""

        text = (
            f"\U0001f6a8  *{len(buyers)} WALLETS BOUGHT*{eco_tag}\n"
            f"\n"
            + "\n".join(wallet_lines)
            + f"\n\n"
            f"\U0001f4a0  *#{ticker}*  |  MC: *{fmt_mc(market_cap)}*  |  Seen: *{seen_str}*\n"
            f"`{token_mint}`\n"
            f"\n"
            f"\U0001f4b5 Price  *${price}*\n"
            f"\U0001f3e6 DEX    *{dex_label}*"
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
            logger.info(f"Alert sent -> chat {chat_id} | {ticker}")
        except Exception as e:
            logger.error(f"Alert failed -> chat {chat_id}: {e}")
