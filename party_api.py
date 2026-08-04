"""
Tiny HTTP API, run alongside the Discord bot, that the companion Dalamud
plugin (running inside players' game clients - not part of this repo)
calls when a player's Party Finder listing fills up to 8/8. The plugin
knows nothing about Discord: it just POSTs the character name + server
that just filled its party, and this module does the rest:

1. Looks up who registered that character via /register (storage.py's
   verified map).
2. If found, pings that Discord user in the configured announcement
   channel. If not found (character never registered), the event is
   silently ignored - there's no Discord account to notify.

Requires two environment variables to actually do anything:
- PARTY_FINDER_API_TOKEN: shared secret the plugin sends as a Bearer
  token. Without this set, the endpoint refuses all requests.
- PARTY_FULL_CHANNEL_ID: the Discord channel id to post notifications in.

This only works once the Railway service has a public domain (so the
plugin, running on players' PCs, can actually reach it) and Railway has
assigned a PORT for this process to listen on.
"""

import os

from aiohttp import web

PARTY_FINDER_API_TOKEN = os.environ.get("PARTY_FINDER_API_TOKEN")
PARTY_FULL_CHANNEL_ID = os.environ.get("PARTY_FULL_CHANNEL_ID")


async def start_party_api(bot, storage):
    """Starts the aiohttp server and returns its AppRunner (kept alive for
    the lifetime of the bot process - there's currently no cleanup path
    since the bot doesn't shut down gracefully anywhere else either)."""

    async def handle_party_full(request):
        if not PARTY_FINDER_API_TOKEN:
            return web.json_response({"error": "server not configured"}, status=503)

        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {PARTY_FINDER_API_TOKEN}":
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON body"}, status=400)

        name = (payload.get("character_name") or "").strip()
        server = (payload.get("server") or "").strip()
        if not name or not server:
            return web.json_response(
                {"error": "character_name and server are required"}, status=400
            )

        if not PARTY_FULL_CHANNEL_ID:
            print("party-full webhook: PARTY_FULL_CHANNEL_ID is not set, dropping event")
            return web.json_response({"error": "server not configured"}, status=503)

        discord_id = storage.find_discord_id_by_character(name, server)
        if discord_id is None:
            print(f"party-full webhook: no /register match for {name} ({server}), ignoring")
            return web.json_response({"status": "ignored", "reason": "character not registered"})

        channel = bot.get_channel(int(PARTY_FULL_CHANNEL_ID))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(PARTY_FULL_CHANNEL_ID))
            except Exception as e:
                print(f"party-full webhook: couldn't reach channel {PARTY_FULL_CHANNEL_ID}: {e}")
                return web.json_response({"error": "channel unreachable"}, status=500)

        try:
            await channel.send(f"🎉 <@{discord_id}>'s party is full! (**{name}**, {server})")
        except Exception as e:
            print(f"party-full webhook: failed to send message: {e}")
            return web.json_response({"error": "failed to notify"}, status=500)

        return web.json_response({"status": "notified", "discord_id": discord_id})

    app = web.Application()
    app.router.add_post("/party-full", handle_party_full)

    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"party-full API listening on 0.0.0.0:{port}")
    return runner
