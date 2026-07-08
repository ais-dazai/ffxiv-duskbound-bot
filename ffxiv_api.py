"""
Client per le due API esterne usate dal bot:

- FFLogsClient: interroga FFLogs (API v2, GraphQL) per sapere quali fight
  Ultimate un personaggio ha già "clearato" (cioè per cui esiste almeno
  un log con una kill registrata).
- LodestoneClient: usa XIVAPI (wrapper pubblico del Lodestone) per cercare
  un personaggio e leggerne la bio, usata per il processo di verifica.
"""

import time
import requests

FFLOGS_TOKEN_URL = "https://www.fflogs.com/oauth/token"
FFLOGS_API_URL = "https://www.fflogs.com/api/v2/client"
XIVAPI_BASE = "https://xivapi.com"


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
            raise RuntimeError(f"Errore FFLogs API: {data['errors']}")
        return data["data"]

    def get_ultimate_encounters(self):
        """Ritorna la lista di tutti i fight che appartengono a una zona
        'Ultimate' su FFLogs (UCoB, UwU, TEA, DSR, TOP, FRU, e futuri).
        Fatto dinamicamente così non serve aggiornare il codice quando
        esce un nuovo ultimate."""
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
        """Converte un nome di server FFXIV (es. 'Odin') nello slug e nella
        regione richiesti da FFLogs. Recuperato dinamicamente, quindi
        funziona per qualunque server senza doverlo aggiungere a mano."""
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
    def __init__(self, api_key=None):
        self.api_key = api_key

    def _params(self, extra=None):
        params = dict(extra) if extra else {}
        if self.api_key:
            params["private_key"] = self.api_key
        return params

    def search_character(self, name, server):
        resp = requests.get(
            f"{XIVAPI_BASE}/character/search",
            params=self._params({"name": name, "server": server}),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("Results", [])
        return results[0] if results else None

    def get_character_bio(self, lodestone_id):
        resp = requests.get(
            f"{XIVAPI_BASE}/character/{lodestone_id}",
            params=self._params(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        char = data.get("Character", {})
        return char.get("Bio", "") or ""
