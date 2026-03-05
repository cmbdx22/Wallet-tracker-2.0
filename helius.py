import aiohttp
import asyncio
import logging
from config import HELIUS_API_KEY, HELIUS_API_BASE, DEXSCREENER_API

logger = logging.getLogger(__name__)

SOL_MINT  = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
STABLE_MINTS = {SOL_MINT, USDC_MINT, USDT_MINT}

class HeliusClient:
    def __init__(self):
        self.session = None

    async def init_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_wallet_transactions(self, wallet_address: str, limit: int = 10):
        """
        Fetch recent transactions — NO type filter.
        Pump.fun txs come through as UNKNOWN, not SWAP.
        Filtering by type here means zero Pump.fun detection.
        We parse manually instead.
        """
        await self.init_session()
        url    = f"{HELIUS_API_BASE}/addresses/{wallet_address}/transactions"
        params = {
            "api-key": HELIUS_API_KEY,
            "limit":   min(limit, 100),
            # NO "type" filter — catches Pump.fun + Raydium + Jupiter + all DEXes
        }
        try:
            async with self.session.get(url, params=params,
                                         timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        return data
                    return []
                elif resp.status == 429:
                    logger.warning(f"Rate limited — {wallet_address[:8]}")
                    await asyncio.sleep(3)
                    return []
                else:
                    logger.error(f"Helius {resp.status} for {wallet_address[:8]}")
                    return []
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {wallet_address[:8]}")
            return []
        except Exception as e:
            logger.error(f"get_wallet_transactions {wallet_address[:8]}: {e}")
            return []

    def parse_swap_transaction(self, tx: dict):
        """
        Parse any transaction type to detect a token buy.
        Tries 3 methods in order of reliability:
        1. events.swap  — Raydium / Jupiter structured swaps
        2. tokenTransfers + nativeTransfers — catches most DEXes
        3. accountData balance changes — last resort fallback
        Returns None if not a buy, or dict with buy details.
        """
        if not tx or not isinstance(tx, dict):
            return None

        fee_payer = tx.get("feePayer", "")
        if not fee_payer:
            return None

        result = (
            self._parse_swap_event(tx, fee_payer) or
            self._parse_token_transfers(tx, fee_payer) or
            self._parse_account_data(tx, fee_payer)
        )
        return result

    def _parse_swap_event(self, tx, fee_payer):
        """Method 1: events.swap — most accurate for Raydium/Jupiter."""
        swap = tx.get("events", {}).get("swap", {})
        if not swap:
            return None

        outputs = swap.get("tokenOutputs", [])
        inputs  = swap.get("tokenInputs",  [])
        if not outputs:
            return None

        bought_mint = outputs[0].get("mint", "")
        sold_mint   = inputs[0].get("mint", SOL_MINT) if inputs else SOL_MINT

        if not bought_mint or bought_mint in STABLE_MINTS:
            return None
        if sold_mint not in STABLE_MINTS:
            return None

        # Get SOL amount from nativeFees or nativeTransfers
        sol_spent = 0
        native_fees = swap.get("nativeFees", [])
        if native_fees:
            sol_spent = abs(native_fees[0].get("amount", 0))
        if sol_spent == 0:
            for t in tx.get("nativeTransfers", []):
                if t.get("fromUserAccount") == fee_payer:
                    sol_spent += t.get("amount", 0)

        return {
            "signature":  tx.get("signature", ""),
            "timestamp":  tx.get("timestamp", 0),
            "token_mint": bought_mint,
            "sol_spent":  sol_spent,
            "source":     "swap_event"
        }

    def _parse_token_transfers(self, tx, fee_payer):
        """Method 2: tokenTransfers array — catches Pump.fun and others."""
        token_transfers  = tx.get("tokenTransfers", [])
        native_transfers = tx.get("nativeTransfers", [])

        if not token_transfers:
            return None

        # Tokens received by the fee payer that aren't stablecoins
        received = [
            t for t in token_transfers
            if t.get("toUserAccount") == fee_payer
            and t.get("mint", "") not in STABLE_MINTS
            and t.get("mint", "")
        ]
        if not received:
            return None

        # SOL sent out by the fee payer
        sol_sent = sum(
            t.get("amount", 0) for t in native_transfers
            if t.get("fromUserAccount") == fee_payer
        )
        if sol_sent == 0:
            return None  # Didn't spend SOL — not a buy we care about

        return {
            "signature":  tx.get("signature", ""),
            "timestamp":  tx.get("timestamp", 0),
            "token_mint": received[0]["mint"],
            "sol_spent":  sol_sent,
            "source":     "token_transfers"
        }

    def _parse_account_data(self, tx, fee_payer):
        """Method 3: accountData balance changes — last resort."""
        account_data = tx.get("accountData", [])
        if not account_data:
            return None

        sol_change    = 0
        token_changes = []

        for acct in account_data:
            if acct.get("account") == fee_payer:
                sol_change = acct.get("nativeBalanceChange", 0)
            for tbc in acct.get("tokenBalanceChanges", []):
                if tbc.get("userAccount") == fee_payer:
                    mint   = tbc.get("mint", "")
                    raw    = tbc.get("rawTokenAmount", {})
                    amount = float(raw.get("tokenAmount", 0)) if raw else 0
                    if mint and mint not in STABLE_MINTS and amount > 0:
                        token_changes.append(mint)

        if token_changes and sol_change < -1_000_000:  # spent > 0.001 SOL
            return {
                "signature":  tx.get("signature", ""),
                "timestamp":  tx.get("timestamp", 0),
                "token_mint": token_changes[0],
                "sol_spent":  abs(sol_change),
                "source":     "account_data"
            }
        return None

    async def get_market_cap(self, mint_address: str) -> dict:
        """Token info from DexScreener."""
        await self.init_session()
        url = f"{DEXSCREENER_API}/{mint_address}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data      = await resp.json()
                    pairs     = data.get("pairs") or []
                    sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                    if sol_pairs:
                        pair = sorted(
                            sol_pairs,
                            key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0),
                            reverse=True
                        )[0]
                        return {
                            "ticker":       pair.get("baseToken", {}).get("symbol", "???"),
                            "name":         pair.get("baseToken", {}).get("name", "Unknown"),
                            "market_cap":   pair.get("marketCap", 0) or pair.get("fdv", 0),
                            "price_usd":    pair.get("priceUsd", "0"),
                            "pair_address": pair.get("pairAddress", ""),
                            "dex":          pair.get("dexId", ""),
                        }
        except Exception as e:
            logger.error(f"get_market_cap {mint_address[:8]}: {e}")
        return {}
