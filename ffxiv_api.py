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


def normalize_icon_url(url):
    """Strips the cache-busting query string (e.g. '?n7.55') off a Lodestone
    icon URL so two URLs for the same underlying image can be compared with
    a plain '==', even if they were fetched from different pages at slightly
    different times."""
    if not url:
        return None
    return url.split("?")[0]


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

    def get_encounter_ranking(self, char_name, server_slug, server_region, encounter_id):
        """Returns the raw encounterRankings JSON for this character+encounter
        (a dict that includes at least 'totalKills', and - when FFLogs has
        percentile data for this fight - 'rankPercent', the character's best
        parse percentile, and 'medianPercent'), or None if the character has
        no FFLogs data for it at all."""
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
            return None
        rankings = char.get("encounterRankings")
        if not rankings or not isinstance(rankings, dict):
            return None
        return rankings

    def has_clear(self, char_name, server_slug, server_region, encounter_id):
        ranking = self.get_encounter_ranking(char_name, server_slug, server_region, encounter_id)
        if not ranking:
            return False
        total_kills = ranking.get("totalKills", 0)
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

    def get_best_ranking_any(self, char_name, server_slug, server_region, encounter_ids):
        """Like has_clear_any, but in one pass also returns the best 'best
        parse' percentile (0-100) FFLogs has for this fight across the given
        ids - used by /profile to show a small percentile badge under each
        Ultimate. Returns (cleared: bool, best_percent: float or None) -
        best_percent is None if the character has no percentile data at all
        (private logs, or a fight FFLogs doesn't rank by percentile).

        Note: 'rankPercent' is NOT a field of the top-level encounterRankings
        object (that only has aggregate stuff like totalKills/bestAmount) -
        percentiles live per-pull, inside the 'ranks' list. Each entry there
        has 'historicalPercent' (the character's all-time percentile for that
        pull) as well as 'rankPercent'/'todayPercent' (scoped to whatever
        implicit timeframe the API applied). We want "best parse ever", so we
        take the max 'historicalPercent' across every pull in 'ranks'."""
        cleared = False
        best_percent = None
        last_error = None
        for encounter_id in encounter_ids:
            try:
                ranking = self.get_encounter_ranking(char_name, server_slug, server_region, encounter_id)
            except Exception as e:
                last_error = e
                continue
            if not ranking:
                continue
            if ranking.get("totalKills", 0):
                cleared = True
            for rank in ranking.get("ranks") or []:
                pct = rank.get("historicalPercent")
                if isinstance(pct, (int, float)) and pct >= 0 and (best_percent is None or pct > best_percent):
                    best_percent = pct
        if not cleared and best_percent is None and last_error is not None:
            raise last_error
        return cleared, best_percent


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
            "active_job_icon_src": None,
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
            # Lodestone does NOT label this icon with the job's name anywhere
            # (no alt text, no tooltip) - the official selector reference
            # (xivapi/lodestone-css-selectors) only exposes its image 'src'.
            # To turn that into an actual job name, get_class_job_data() below
            # scrapes the same icon image for all 33 jobs on the class_job
            # page, and callers match this src against that list to find
            # which job it is (see bot.py's /profile command).
            profile["active_job_icon_src"] = job_icon_el.get("src")

        level_el = soup.select_one(".character__class__data > p:nth-child(1)")
        if level_el:
            match = re.search(r"LEVEL\s*(\d+)", level_el.get_text(strip=True))
            if match:
                profile["active_job_level"] = int(match.group(1))

        return profile

    def get_class_job_data(self, lodestone_id, job_selectors):
        """job_selectors: list of (key, level_selector) pairs (see jobs_data.py).
        Fetches the class_job page ONCE and returns a dict of
        key -> {"level": int or None, "icon_src": str or None}.

        level: None if that job is unlocked but has no level shown ('-'), or
        wasn't found on the page at all.

        icon_src: each job's row on this page is a <li> like
        '<i class="character__job__icon"><img src=".."></i>
         <div class="character__job__level">100</div> ...'
        - the icon is an <img> inside an <i> (not a <div>!) as the first
        child, with the level div as the second (that's why every
        level_selector in jobs_data.py ends in 'div:nth-child(2)') - so the
        icon lives at the same position with 'i:nth-child(1) > img' instead.
        Confirmed against the real page markup via /debug-classjob (an
        earlier version of this guessed 'div:nth-child(1)' and silently
        matched nothing, since the icon's wrapper is actually an <i> tag).
        This icon is used to identify the *currently equipped* job (see
        get_character_profile's 'active_job_icon_src'), since Lodestone
        doesn't expose that job's name as text anywhere on the main profile
        page (only here, on the full class_job list, as a bonus - each row's
        third child div.character__job__name also holds the plain job name,
        e.g. "Paladin" - not used here since jobs_data.py already has it)."""
        resp = requests.get(
            f"{LODESTONE_BASE}/character/{lodestone_id}/class_job/",
            headers=LODESTONE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        data = {}
        for key, level_selector in job_selectors:
            level = None
            el = soup.select_one(level_selector)
            if el is not None:
                match = re.search(r"\d+", el.get_text(strip=True))
                level = int(match.group()) if match else None

            icon_src = None
            icon_selector = re.sub(r"div:nth-child\(2\)$", "i:nth-child(1) > img", level_selector)
            icon_el = soup.select_one(icon_selector)
            if icon_el is not None:
                icon_src = icon_el.get("src")

            data[key] = {"level": level, "icon_src": icon_src}
        return data

    def get_class_job_levels(self, lodestone_id, job_selectors):
        """Backward-compatible thin wrapper around get_class_job_data() for
        callers (like /debug-classjob) that only care about levels, not
        icons. Returns a dict of key -> level (int or None)."""
        data = self.get_class_job_data(lodestone_id, job_selectors)
        return {key: v["level"] for key, v in data.items()}

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
