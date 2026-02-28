import json
import os
from config import DATA_FILE

class DataStore:
    def __init__(self):
        self.data = {
            "wallets": {},       # address -> {name, label, added_by, chat_id}
            "chat_ids": [],      # telegram chat IDs to notify
            "threshold": 2,      # min wallets to trigger alert
            "active": True
        }
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                self.data = json.load(f)

    def save(self):
        with open(DATA_FILE, 'w') as f:
            json.dump(self.data, f, indent=2)

    def add_wallet(self, address: str, name: str, chat_id: int):
        self.data["wallets"][address] = {
            "name": name,
            "address": address,
            "chat_id": chat_id
        }
        if chat_id not in self.data["chat_ids"]:
            self.data["chat_ids"].append(chat_id)
        self.save()

    def remove_wallet(self, address: str):
        if address in self.data["wallets"]:
            del self.data["wallets"][address]
            self.save()
            return True
        return False

    def get_wallets(self):
        return self.data["wallets"]

    def get_wallet_count(self):
        return len(self.data["wallets"])

    def get_threshold(self):
        return self.data.get("threshold", 2)

    def set_threshold(self, value: int):
        self.data["threshold"] = value
        self.save()

    def get_chat_ids(self):
        return self.data.get("chat_ids", [])

    def add_chat_id(self, chat_id: int):
        if chat_id not in self.data["chat_ids"]:
            self.data["chat_ids"].append(chat_id)
            self.save()

    def get_wallet_by_address(self, address: str):
        return self.data["wallets"].get(address)
