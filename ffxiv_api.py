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
# The mount/minion pages only inline the item names when requested with a
# mobile user agent - with a desktop UA the names are loaded separately via
# AJAX per item, which we want to avoid (would mean dozens of extra requests).
LODESTONE_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
}


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

    def get_all_encounters(self):
        """Returns every encounter on FFLogs, across every zone, together with
        the zone it belongs to. We fetch everything and let the caller decide
        which ones are Ultimates, because FFLogs zone naming is inconsistent:
        older Ultimates get grouped into retrospective zones whose name
        contains 'Ultimate' (e.g. 'Ultimates (Legacy)'), while the current
        tier's Ultimate often lives in a zone named just after the raid
        itself (e.g. 'Futures Rewritten', no 'Ultimate' in the name)."""
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
            for enc in zone["encounters"]:
                encounters.append({"id": enc["id"], "name": enc["name"], "zone": zone["name"]})
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

    def has_clear_any(self, char_name, server_slug, server_region, encounter_ids):
        """Returns True if the character has a logged clear on ANY of the
        given encounter ids. Raises the last error only if every single id
        failed to query (so a valid 'no clear' on one id doesn't get hidden
        behind an unrelated error on another id)."""
        last_error = None
        for encounter_id in encounter_ids:
            try:
                if self.has_clear(char_name, server_slug, server_region, encounter_id):
                    return True
            except Exception as e:
                last_error = e
        if last_error is not None:
            raise last_error
        return False


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
        target_server = server.strip().lower()
        best = None
        for entry in entries:
            name_el = entry.select_one(".entry__name")
            world_el = entry.select_one(".entry__world")
            if not name_el or not world_el:
                continue
            entry_name = name_el.get_text(strip=True).lower()
            entry_world = world_el.get_text(strip=True).lower()
            if entry_name == target_name and entry_world.startswith(target_server):
                best = entry
                break

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

    def debug_search(self, name, server):
        """Raw diagnostic info for troubleshooting: HTTP status, how many
        <a class="entry__link"> elements were found, and the exact name/world
        text extracted from each (repr()'d so hidden characters are visible)."""
        params = {"q": name, "worldname": server}
        resp = requests.get(
            f"{LODESTONE_BASE}/character/",
            params=params,
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        info = {"status_code": resp.status_code, "url": resp.url, "entries": []}
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = soup.select("a.entry__link")
        info["raw_entry_count"] = len(entries)
        for entry in entries[:30]:
            name_el = entry.select_one(".entry__name")
            world_el = entry.select_one(".entry__world")
            info["entries"].append({
                "name": repr(name_el.get_text(strip=True)) if name_el else None,
                "world": repr(world_el.get_text(strip=True)) if world_el else None,
            })
        return info

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

    def debug_mount_page(self, lodestone_id):
        """Raw diagnostic info for the mount page, used to figure out the
        correct selectors before relying on this in a real command (the
        mount page structure has never been tested live for this bot)."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/mount/",
            headers=LODESTONE_MOBILE_HEADERS,
            timeout=15,
        )
        info = {
            "status_code": resp.status_code,
            "url": resp.url,
            "html_length": len(resp.text),
        }
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try a handful of plausible selectors and report how many matches
        # each gets, plus a sample of extracted text, so we can tell which
        # one (if any) actually matches the real page structure.
        candidate_selectors = [
            ".character__item_icon",
            ".character__inventory--Mounts .character__item_icon",
            "li",
            ".character__item_text",
            "[data-tooltip]",
        ]
        info["selector_counts"] = {}
        info["samples"] = {}
        for sel in candidate_selectors:
            found = soup.select(sel)
            info["selector_counts"][sel] = len(found)
            samples = []
            for el in found[:8]:
                text = el.get_text(strip=True)
                tooltip = el.get("data-tooltip")
                if text or tooltip:
                    samples.append({"text": text or None, "tooltip": tooltip})
            info["samples"][sel] = samples

        return info

    def get_character_mounts(self, lodestone_id):
        """Returns the set of mount names this character owns, read from
        their public Lodestone mount page (mobile user agent, so names are
        inlined without extra AJAX calls per item)."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/mount/",
            headers=LODESTONE_MOBILE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        names = set()
        for el in soup.select(".character__item_icon"):
            tooltip = el.get("data-tooltip")
            if tooltip:
                names.add(tooltip.strip())
        for el in soup.select(".character__item_text"):
            text = el.get_text(strip=True)
            if text:
                names.add(text)

        return names
