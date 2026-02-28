import aiohttp
import asyncio
import logging
from config import HELIUS_API_KEY, HELIUS_API_BASE, HELIUS_RPC_URL, DEXSCREENER_API

logger = logging.getLogger(__name__)

class HeliusClient:
    def __init__(self):
        self.session = None

    async def init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

    async def get_wallet_transactions(self, wallet_address: str, before_sig: str = None):
        """Fetch recent transactions for a wallet using Helius enhanced API."""
        await self.init_session()
        url = f"{HELIUS_API_BASE}/addresses/{wallet_address}/transactions"
        params = {
            "api-key": HELIUS_API_KEY,
            "limit": 10,
            "type": "SWAP"  # Only fetch swap transactions
        }
        if before_sig:
            params["before"] = before_sig

        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.error(f"Helius API error {resp.status} for {wallet_address}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching transactions for {wallet_address}: {e}")
            return []

    async def get_token_metadata(self, mint_address: str):
        """Get token metadata from Helius DAS API."""
        await self.init_session()
        url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        payload = {
            "jsonrpc": "2.0",
            "id": "get-asset",
            "method": "getAsset",
            "params": {"id": mint_address}
        }
        try:
            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", {})
                return {}
        except Exception as e:
            logger.error(f"Error fetching token metadata for {mint_address}: {e}")
            return {}

    async def get_market_cap(self, mint_address: str):
        """Get token market cap and info from DexScreener (free, no key needed)."""
        await self.init_session()
        url = f"{DEXSCREENER_API}/{mint_address}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        # Get the most liquid Solana pair
                        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                        if sol_pairs:
                            pair = sorted(sol_pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)[0]
                            return {
                                "ticker": pair.get("baseToken", {}).get("symbol", "UNKNOWN"),
                                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0),
                                "price_usd": pair.get("priceUsd", "0"),
                                "pair_address": pair.get("pairAddress", ""),
                                "dex": pair.get("dexId", ""),
                                "liquidity_usd": pair.get("liquidity", {}).get("usd", 0)
                            }
        except Exception as e:
            logger.error(f"Error fetching market cap for {mint_address}: {e}")
        return {}

    async def setup_webhook(self, wallet_addresses: list, webhook_url: str):
        """Register wallets with Helius webhook for real-time notifications."""
        await self.init_session()
        url = f"{HELIUS_API_BASE}/webhooks"
        payload = {
            "webhookURL": webhook_url,
            "transactionTypes": ["SWAP"],
            "accountAddresses": wallet_addresses,
            "webhookType": "enhanced"
        }
        try:
            async with self.session.post(
                url,
                json=payload,
                params={"api-key": HELIUS_API_KEY},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
                return data
        except Exception as e:
            logger.error(f"Error setting up webhook: {e}")
            return {}

    def parse_swap_transaction(self, tx: dict):
        """
        Parse a Helius enhanced transaction to extract swap details.
        Returns dict with token_in, token_out, amount, mint addresses.
        """
        if not tx:
            return None

        tx_type = tx.get("type", "")
        if tx_type != "SWAP":
            return None

        events = tx.get("events", {})
        swap = events.get("swap", {})
        
        if not swap:
            return None

        # Extract the token being bought (tokenOutputs)
        token_outputs = swap.get("tokenOutputs", [])
        token_inputs = swap.get("tokenInputs", [])

        if not token_outputs:
            return None

        # The token bought is in outputs
        bought_token = token_outputs[0] if token_outputs else {}
        sold_token = token_inputs[0] if token_inputs else {}

        # SOL mint address (native SOL wrapped)
        SOL_MINT = "So11111111111111111111111111111111111111112"

        bought_mint = bought_token.get("mint", "")
        sold_mint = sold_token.get("mint", SOL_MINT)

        # We care when someone buys a token WITH SOL (or USDC)
        # i.e., sold_mint is SOL or USDC, bought_mint is the new token
        USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        
        is_buy = sold_mint in [SOL_MINT, USDC_MINT] and bought_mint not in [SOL_MINT, USDC_MINT]

        if not is_buy or not bought_mint:
            return None

        return {
            "signature": tx.get("signature", ""),
            "timestamp": tx.get("timestamp", 0),
            "token_mint": bought_mint,
            "token_amount": bought_token.get("tokenAmount", 0),
            "sol_spent": abs(swap.get("nativeFees", [{}])[0].get("amount", 0)) if swap.get("nativeFees") else 0,
            "description": tx.get("description", ""),
            "fee_payer": tx.get("feePayer", "")
        }
