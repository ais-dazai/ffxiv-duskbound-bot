"""
External API clients used by the bot:

- FFLogsClient: queries FFLogs (API v2, GraphQL) to find out which Ultimate
  fights a character has already cleared (i.e. has at least one logged kill).
- LodestoneClient: reads character data directly from the official, public
  Lodestone pages (na.finalfantasyxiv.com/lodestone). No API key needed -
  Lodestone is Square Enix's own public website. We only read a couple of
  pages per verification, so we stay well within reasonable, respectful use.
"""

import re
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

    def debug_mount_page_v2(self, lodestone_id):
        """More targeted diagnostic: search the raw HTML for a mount almost
        everyone owns ('Company Chocobo') and show the raw markup around it,
        plus how often a handful of candidate class-name keywords appear
        anywhere in the page. This tells us the real structure directly,
        instead of guessing selectors blind."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/mount/",
            headers=LODESTONE_MOBILE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text

        info = {"html_length": len(html), "keyword_counts": {}, "snippets": []}

        keywords = [
            "character__item",
            "character__inventory",
            "js__tooltip",
            "data-tooltip",
            "mount",
            "Mount",
            "Chocobo",
        ]
        for kw in keywords:
            info["keyword_counts"][kw] = html.count(kw)

        for needle in ["Company Chocobo", "Chocobo"]:
            idx = html.find(needle)
            if idx != -1:
                start = max(0, idx - 200)
                end = min(len(html), idx + 3000)
                info["snippets"].append({"needle": needle, "context": html[start:end]})
                break

        return info

    def get_character_profile(self, lodestone_id):
        """Scrapes the main character page for the fields shown at the top of
        the /profile card: name, race/tribe/gender, world + data center,
        the big character render (portrait), and the currently active
        class/job with its level. Selectors come from the community-maintained
        https://github.com/xivapi/lodestone-css-selectors project."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/",
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        profile = {
            "name": None,
            "race": None,
            "tribe": None,
            "world": None,
            "dc": None,
            "portrait_url": None,
            "active_job_name": None,
            "active_job_level": None,
        }

        name_el = soup.select_one("div.frame__chara__box:nth-child(2) > .frame__chara__name")
        if name_el:
            profile["name"] = name_el.get_text(strip=True)

        race_el = soup.select_one("div.character-block:nth-child(1) > div:nth-child(2) > p:nth-child(2)")
        if race_el:
            # e.g. "Au Ra<br>Xaela / ♂" once rendered - get_text keeps the line break as a gap
            raw = race_el.decode_contents()
            match = re.search(r"(?P<Race>.*?)<br\s*/?>(?P<Tribe>.*?)\s*/", raw)
            if match:
                profile["race"] = BeautifulSoup(match.group("Race"), "html.parser").get_text(strip=True)
                profile["tribe"] = BeautifulSoup(match.group("Tribe"), "html.parser").get_text(strip=True)

        world_el = soup.select_one("p.frame__chara__world")
        if world_el:
            match = re.match(r"(?P<World>\S*)\s*\[(?P<DC>\S*)\]", world_el.get_text(strip=True))
            if match:
                profile["world"] = match.group("World")
                profile["dc"] = match.group("DC")

        portrait_el = soup.select_one(".js__image_popup > img:nth-child(1)")
        if portrait_el:
            profile["portrait_url"] = portrait_el.get("src")

        job_icon_el = soup.select_one(".character__class_icon > img:nth-child(1)")
        if job_icon_el:
            # Lodestone sets the alt text of this icon to the job's display
            # name (e.g. "Dragoon") - much more reliable than trying to
            # reverse-engineer the job from the icon's image filename/id.
            alt = job_icon_el.get("alt", "").strip()
            if alt:
                profile["active_job_name"] = alt

        level_el = soup.select_one(".character__class__data > p:nth-child(1)")
        if level_el:
            match = re.search(r"LEVEL\s*(\d+)", level_el.get_text(strip=True))
            if match:
                profile["active_job_level"] = int(match.group(1))

        return profile

    def get_class_job_levels(self, lodestone_id, job_selectors):
        """job_selectors: list of (key, css_selector) pairs (see jobs_data.py).
        Returns a dict of key -> level (int) or None if that job is unlocked
        but has no level shown ('-'), or wasn't found on the page at all."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/class_job/",
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        levels = {}
        for key, selector in job_selectors:
            el = soup.select_one(selector)
            if el is None:
                levels[key] = None
                continue
            text = el.get_text(strip=True)
            match = re.search(r"\d+", text)
            levels[key] = int(match.group()) if match else None
        return levels

    def get_minion_count(self, lodestone_id):
        return self._get_collection_total(lodestone_id, "minion")

    def get_mount_count(self, lodestone_id):
        return self._get_collection_total(lodestone_id, "mount")

    def _get_collection_total(self, lodestone_id, kind):
        """kind: 'minion' or 'mount'. Both pages show the owned count in a
        '.minion__sort__total' widget (Lodestone reuses that class name on
        both pages) - if that ever changes, /debug-mounts-v2-style inspection
        would be the way to re-tune this."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/{kind}/",
            headers=LODESTONE_MOBILE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.select_one(".minion__sort__total > span:nth-child(1)")
        if el is None:
            return None
        match = re.search(r"\d+", el.get_text(strip=True))
        return int(match.group()) if match else None

    def get_achievement_points(self, lodestone_id):
        """Best-effort: the total achievement points shown at the top of the
        achievement page. Unlike the fields above, there's no selector for
        this in the community-maintained selector reference, and this page
        has occasionally been flakier about automated requests than the
        others - so this returns None on any failure instead of raising, and
        callers should treat None as 'unknown' rather than an error. Use
        /debug-achievements to inspect the raw page if this keeps failing."""
        try:
            resp = requests.get(
                f"{LODESTONE_BASE}/character/{lodestone_id}/achievement/",
                headers=LODESTONE_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        candidates = [
            ".character__achievement__points",
            ".achievement__point--total",
            ".point__total",
            ".achievement-points",
        ]
        for sel in candidates:
            el = soup.select_one(sel)
            if el:
                match = re.search(r"[\d,]+", el.get_text(strip=True))
                if match:
                    return int(match.group().replace(",", ""))

        # Fallback: scan the whole page text for a "N,NNN Points" pattern,
        # which is how the total is displayed visually on the real page.
        match = re.search(r"([\d,]{3,})\s*Points", resp.text)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def debug_class_job_page(self, lodestone_id):
        """Raw diagnostic info for the class/job page, mirroring debug_mount_page."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/class_job/",
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        info = {"status_code": resp.status_code, "url": resp.url, "html_length": len(resp.text)}
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        from jobs_data import JOBS
        info["job_levels"] = {}
        for job in JOBS:
            el = soup.select_one(job["level_selector"])
            info["job_levels"][job["key"]] = el.get_text(strip=True) if el else "(selector matched nothing)"
        return info

    def debug_achievement_page(self, lodestone_id):
        """Raw diagnostic info for the achievement page, mirroring debug_mount_page_v2:
        shows whether the page loads at all, and the raw HTML around the word
        'Points' so we can find the real selector for the total."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/achievement/",
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        info = {"status_code": resp.status_code, "url": resp.url, "html_length": len(resp.text)}
        resp.raise_for_status()
        html = resp.text
        info["snippets"] = []
        for needle in ["Points", "point"]:
            idx = html.find(needle)
            if idx != -1:
                start = max(0, idx - 300)
                end = min(len(html), idx + 300)
                info["snippets"].append({"needle": needle, "context": html[start:end]})
        return info

    def get_character_mounts(self, lodestone_id):
        """Returns the set of mount names this character owns, read from
        their public Lodestone mount page (mobile user agent, so names are
        inlined without extra AJAX calls per item). Confirmed via manual
        debugging: this page only lists mounts the character actually owns,
        each one as <span class="mount__name">Mount Name</span>."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/mount/",
            headers=LODESTONE_MOBILE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        names = set()
        for el in soup.select(".mount__name"):
            text = el.get_text(strip=True)
            if text:
                names.add(text)

        return names
