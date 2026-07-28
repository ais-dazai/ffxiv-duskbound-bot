"""
Persistenza molto semplice basata su un file JSON locale (data.json).
Va benissimo per un singolo server/community. Se in futuro ti serve
qualcosa di più robusto (tanti utenti, più server) si può passare
a un vero database senza toccare il resto del bot: basta riscrivere
questa classe.
"""

import json
import os
import threading

_LOCK = threading.Lock()


class Storage:
    def __init__(self, path="data.json"):
        self.path = path
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(self.path):
            self._write({})

    def _read(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def set_pending(self, discord_id, char_info, code):
        with _LOCK:
            data = self._read()
            data.setdefault("pending", {})[str(discord_id)] = {
                "character": char_info,
                "code": code,
            }
            self._write(data)

    def get_pending(self, discord_id):
        with _LOCK:
            data = self._read()
            return data.get("pending", {}).get(str(discord_id))

    def clear_pending(self, discord_id):
        with _LOCK:
            data = self._read()
            data.get("pending", {}).pop(str(discord_id), None)
            self._write(data)

    def set_verified(self, discord_id, char_info):
        with _LOCK:
            data = self._read()
            data.setdefault("verified", {})[str(discord_id)] = char_info
            self._write(data)

    def get_verified(self, discord_id):
        with _LOCK:
            data = self._read()
            return data.get("verified", {}).get(str(discord_id))

    def set_reaction_message(self, message_id, group_key):
        with _LOCK:
            data = self._read()
            data.setdefault("reaction_messages", {})[str(message_id)] = group_key
            self._write(data)

    def get_reaction_group(self, message_id):
        with _LOCK:
            data = self._read()
            return data.get("reaction_messages", {}).get(str(message_id))

    def set_giveaway(self, message_id, giveaway_data):
        with _LOCK:
            data = self._read()
            data.setdefault("giveaways", {})[str(message_id)] = giveaway_data
            self._write(data)

    def get_active_giveaways(self):
        with _LOCK:
            data = self._read()
            return {
                mid: g for mid, g in data.get("giveaways", {}).items()
                if not g.get("ended")
            }

    def get_giveaway(self, message_id):
        with _LOCK:
            data = self._read()
            return data.get("giveaways", {}).get(str(message_id))

    def mark_giveaway_ended(self, message_id):
        with _LOCK:
            data = self._read()
            giveaway = data.get("giveaways", {}).get(str(message_id))
            if giveaway:
                giveaway["ended"] = True
                self._write(data)
