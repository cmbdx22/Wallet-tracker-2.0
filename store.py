import json
import os
from config import DATA_FILE

class DataStore:
    """
    Per-chat data store.
    Every chat (DM, group, supergroup) has its own completely isolated
    wallet list, threshold, and settings.
    Nothing is ever shared between chats.
    """

    def __init__(self):
        self.data = {"chats": {}}
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                try:
                    self.data = json.load(f)
                except Exception:
                    self.data = {"chats": {}}

    def save(self):
        with open(DATA_FILE, 'w') as f:
            json.dump(self.data, f, indent=2)

    def _init_chat(self, chat_id: int):
        key = str(chat_id)
        if key not in self.data["chats"]:
            self.data["chats"][key] = {
                "wallets": {},
                "threshold": 2,
                "eco_mode": False   # Credit efficient mode — off by default
            }
        # Migrate old chats that don't have eco_mode key
        if "eco_mode" not in self.data["chats"][key]:
            self.data["chats"][key]["eco_mode"] = False

    # ── WALLETS (scoped to chat_id) ──────────────

    def add_wallet(self, chat_id: int, address: str, name: str):
        self._init_chat(chat_id)
        self.data["chats"][str(chat_id)]["wallets"][address] = {
            "name": name,
            "address": address
        }
        self.save()

    def remove_wallet(self, chat_id: int, address: str) -> bool:
        self._init_chat(chat_id)
        wallets = self.data["chats"][str(chat_id)]["wallets"]
        if address in wallets:
            del wallets[address]
            self.save()
            return True
        return False

    def get_wallets(self, chat_id: int) -> dict:
        self._init_chat(chat_id)
        return self.data["chats"][str(chat_id)]["wallets"]

    def get_wallet_count(self, chat_id: int) -> int:
        return len(self.get_wallets(chat_id))

    def wallet_exists(self, chat_id: int, address: str) -> bool:
        return address in self.get_wallets(chat_id)

    # ── THRESHOLD (per chat) ─────────────────────

    def get_threshold(self, chat_id: int) -> int:
        self._init_chat(chat_id)
        return self.data["chats"][str(chat_id)].get("threshold", 2)

    def set_threshold(self, chat_id: int, value: int):
        self._init_chat(chat_id)
        self.data["chats"][str(chat_id)]["threshold"] = value
        self.save()

    # ── ECO MODE (per chat) ──────────────────────

    def get_eco_mode(self, chat_id: int) -> bool:
        self._init_chat(chat_id)
        return self.data["chats"][str(chat_id)].get("eco_mode", False)

    def set_eco_mode(self, chat_id: int, enabled: bool):
        self._init_chat(chat_id)
        self.data["chats"][str(chat_id)]["eco_mode"] = enabled
        self.save()

    def any_eco_mode(self) -> bool:
        """True if ANY chat has eco mode on — tracker uses lowest poll interval."""
        for chat_data in self.data["chats"].values():
            if chat_data.get("eco_mode", False):
                return True
        return False

    def all_eco_mode(self) -> bool:
        """True if ALL chats have eco mode on."""
        chats = list(self.data["chats"].values())
        if not chats:
            return False
        return all(c.get("eco_mode", False) for c in chats)

    # ── CREDIT TRACKING ──────────────────────────

    def add_credits_used(self, amount: int):
        if "credits_used" not in self.data:
            self.data["credits_used"] = 0
        self.data["credits_used"] += amount
        # Save periodically (every 100 credits to avoid too many writes)
        if self.data["credits_used"] % 100 < amount:
            self.save()

    def get_credits_used(self) -> int:
        return self.data.get("credits_used", 0)

    def reset_credits(self):
        self.data["credits_used"] = 0
        self.save()

    # ── GLOBAL HELPERS for tracker ───────────────

    def get_all_addresses(self) -> set:
        """All unique addresses across all chats — for polling."""
        addresses = set()
        for chat_data in self.data["chats"].values():
            for addr in chat_data.get("wallets", {}).keys():
                addresses.add(addr)
        return addresses

    def get_chats_tracking_wallet(self, address: str) -> list:
        """Which chats are tracking a specific wallet — for targeted alerts."""
        chats = []
        for chat_id_str, chat_data in self.data["chats"].items():
            if address in chat_data.get("wallets", {}):
                chats.append(int(chat_id_str))
        return chats
