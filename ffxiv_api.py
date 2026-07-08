"""
External API clients used by the bot:

- FFLogsClient: queries FFLogs (API v2, GraphQL) to find out which Ultimate
  fights a character has already cleared (i.e. has at least one logged kill).
- LodestoneClient: reads character data directly from the official, public
  Lodestone pages (na.finalfantasyxiv.com/lodestone). No API key needed -
  Lodestone is Square Enix's own public website. We only read a couple of
  pages per verification, so we stay well within reasonable, respectful use.
"""

import time
import requests
from bs4 import BeautifulSoup

FFLOGS_TOKEN_URL = "https://www.fflogs.com/oauth/token"
FFLOGS_API_URL = "https://www.fflogs.com/api/v2/client"
LODESTONE_BASE = "https://na.finalfantasyxiv.com/lodestone"
LODESTONE_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FFXIVUltimateRolesBot/1.0)"}


class FFLogsClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expiry = 0
        self._server_cache = None

    def _get_token(self):
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = requests.post(
            FFLOGS_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        return self._token

    def query(self, query, variables=None):
        token = self._get_token()
        resp = requests.post(
            FFLOGS_API_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"FFLogs API error: {data['errors']}")
        return data["data"]

    def get_ultimate_encounters(self):
        """Returns every fight belonging to an 'Ultimate' zone on FFLogs
        (UCoB, UwU, TEA, DSR, TOP, FRU, and any future ones). Fetched
        dynamically so the code doesn't need updating when a new Ultimate
        is released."""
        query = """
        query {
          worldData {
            zones {
              name
              encounters {
                id
                name
              }
            }
          }
        }
        """
        data = self.query(query)
        encounters = []
        for zone in data["worldData"]["zones"]:
            if "ultimate" in zone["name"].lower():
                for enc in zone["encounters"]:
                    encounters.append({"id": enc["id"], "name": enc["name"]})
        return encounters

    def get_server_info(self, server_name):
        """Converts an FFXIV server name (e.g. 'Odin') into the slug and
        region FFLogs needs. Fetched dynamically, so it works for any
        server without having to hardcode a mapping."""
        if self._server_cache is None:
            query = """
            query {
              worldData {
                regions {
                  compactName
                  servers {
                    data {
                      name
                      slug
                    }
                  }
                }
              }
            }
            """
            data = self.query(query)
            cache = {}
            for region in data["worldData"]["regions"]:
                for server in region["servers"]["data"]:
                    cache[server["name"].lower()] = (server["slug"], region["compactName"])
            self._server_cache = cache
        return self._server_cache.get(server_name.strip().lower(), (None, None))

    def has_clear(self, char_name, server_slug, server_region, encounter_id):
        query = """
        query($name: String!, $server: String!, $region: String!, $encounterID: Int!) {
          characterData {
            character(name: $name, serverSlug: $server, serverRegion: $region) {
              encounterRankings(encounterID: $encounterID)
            }
          }
        }
        """
        variables = {
            "name": char_name,
            "server": server_slug,
            "region": server_region,
            "encounterID": encounter_id,
        }
        data = self.query(query, variables)
        char = data["characterData"]["character"]
        if not char:
            return False
        rankings = char.get("encounterRankings")
        if not rankings or not isinstance(rankings, dict):
            return False
        total_kills = rankings.get("totalKills", 0)
        return bool(total_kills and total_kills > 0)


class LodestoneClient:
    def search_character(self, name, server):
        params = {"q": name, "worldname": server}
        resp = requests.get(
            f"{LODESTONE_BASE}/character/",
            params=params,
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = soup.select("a.entry__link")
        if not entries:
            return None

        target_name = name.strip().lower()
        best = None
        for entry in entries:
            name_el = entry.select_one(".entry__name")
            if not name_el:
                continue
            if name_el.get_text(strip=True).lower() == target_name:
                best = entry
                break
            if best is None:
                best = entry  # fallback: first result if no exact match

        if best is None:
            return None

        href = best.get("href", "")
        parts = [p for p in href.split("/") if p]
        char_id = parts[-1] if parts else None
        name_el = best.select_one(".entry__name")
        world_el = best.select_one(".entry__world")
        world_text = world_el.get_text(strip=True) if world_el else server
        world_name = world_text.split()[0] if world_text else server

        return {
            "ID": char_id,
            "Name": name_el.get_text(strip=True) if name_el else name,
            "Server": world_name,
        }

    def get_character_bio(self, lodestone_id):
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/",
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        bio_el = soup.select_one(".character__selfintroduction")
        return bio_el.get_text(strip=True) if bio_el else ""
