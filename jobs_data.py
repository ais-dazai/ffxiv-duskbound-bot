"""
Static reference data for every playable job: display name, abbreviation,
local icon file (see assets/job_icons/), role category (used for the color
of its level badge on the /profile card), and the CSS selector used to
read that job's level off the Lodestone class_job page.

The selectors are taken from the community-maintained, public-domain
https://github.com/xivapi/lodestone-css-selectors project (profile/classjob.json).
They rely on the exact position of each job in the page (e.g. "5th <li> in the")
2nd tank/healer/dps <ul>"), so if Square Enix ever reorders that page these could
break - if job levels look wrong on the card, check with /debug-classjob.
"""

ROLE_COLORS = {
    "tank": "#3b6fa8",
    "healer": "#3f9d6b",
    "melee": "#b5482f",
    "ranged": "#3f7d3f",
    "caster": "#7d4fae",
    "crafter": "#a8752f",
    "gatherer": "#2f8f8a",
}

JOBS = [
    {"key": "PALADIN", "display": "Paladin", "abbrev": "PLD", "icon": "paladin", "role": "tank", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "WARRIOR", "display": "Warrior", "abbrev": "WAR", "icon": "warrior", "role": "tank", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "DARKKNIGHT", "display": "Dark Knight", "abbrev": "DRK", "icon": "darkknight", "role": "tank", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(3) > div:nth-child(2)'},
    {"key": "GUNBREAKER", "display": "Gunbreaker", "abbrev": "GNB", "icon": "gunbreaker", "role": "tank", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(4) > div:nth-child(2)'},
    {"key": "WHITEMAGE", "display": "White Mage", "abbrev": "WHM", "icon": "whitemage", "role": "healer", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "SCHOLAR", "display": "Scholar", "abbrev": "SCH", "icon": "scholar", "role": "healer", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "ASTROLOGIAN", "display": "Astrologian", "abbrev": "AST", "icon": "astrologian", "role": "healer", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(3) > div:nth-child(2)'},
    {"key": "SAGE", "display": "Sage", "abbrev": "SGE", "icon": "sage", "role": "healer", "level_selector": '.character__content > div:nth-child(2) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(4) > div:nth-child(2)'},
    {"key": "MONK", "display": "Monk", "abbrev": "MNK", "icon": "monk", "role": "melee", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "DRAGOON", "display": "Dragoon", "abbrev": "DRG", "icon": "dragoon", "role": "melee", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "NINJA", "display": "Ninja", "abbrev": "NIN", "icon": "ninja", "role": "melee", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(3) > div:nth-child(2)'},
    {"key": "SAMURAI", "display": "Samurai", "abbrev": "SAM", "icon": "samurai", "role": "melee", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(4) > div:nth-child(2)'},
    {"key": "REAPER", "display": "Reaper", "abbrev": "RPR", "icon": "reaper", "role": "melee", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(5) > div:nth-child(2)'},
    {"key": "VIPER", "display": "Viper", "abbrev": "VPR", "icon": "viper", "role": "melee", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(6) > div:nth-child(2)'},
    {"key": "BARD", "display": "Bard", "abbrev": "BRD", "icon": "bard", "role": "ranged", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "MACHINIST", "display": "Machinist", "abbrev": "MCH", "icon": "machinist", "role": "ranged", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "DANCER", "display": "Dancer", "abbrev": "DNC", "icon": "dancer", "role": "ranged", "level_selector": 'div.clearfix:nth-child(3) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(3) > div:nth-child(2)'},
    {"key": "BLACKMAGE", "display": "Black Mage", "abbrev": "BLM", "icon": "blackmage", "role": "caster", "level_selector": 'ul.character__job:nth-child(4) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "SUMMONER", "display": "Summoner", "abbrev": "SMN", "icon": "summoner", "role": "caster", "level_selector": 'ul.character__job:nth-child(4) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "REDMAGE", "display": "Red Mage", "abbrev": "RDM", "icon": "redmage", "role": "caster", "level_selector": 'ul.character__job:nth-child(4) > li:nth-child(3) > div:nth-child(2)'},
    {"key": "PICTOMANCER", "display": "Pictomancer", "abbrev": "PCT", "icon": "pictomancer", "role": "caster", "level_selector": 'ul.character__job:nth-child(4) > li:nth-child(4) > div:nth-child(2)'},
    {"key": "BLUEMAGE", "display": "Blue Mage", "abbrev": "BLU", "icon": "bluemage", "role": "caster", "level_selector": 'ul.character__job:nth-child(4) > li:nth-child(5) > div:nth-child(2)'},
    {"key": "CARPENTER", "display": "Carpenter", "abbrev": "CRP", "icon": "carpenter", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "BLACKSMITH", "display": "Blacksmith", "abbrev": "BSM", "icon": "blacksmith", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "ARMORER", "display": "Armorer", "abbrev": "ARM", "icon": "armorer", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(3) > div:nth-child(2)'},
    {"key": "GOLDSMITH", "display": "Goldsmith", "abbrev": "GSM", "icon": "goldsmith", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(4) > div:nth-child(2)'},
    {"key": "LEATHERWORKER", "display": "Leatherworker", "abbrev": "LTW", "icon": "leatherworker", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(5) > div:nth-child(2)'},
    {"key": "WEAVER", "display": "Weaver", "abbrev": "WVR", "icon": "weaver", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(6) > div:nth-child(2)'},
    {"key": "ALCHEMIST", "display": "Alchemist", "abbrev": "ALC", "icon": "alchemist", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(7) > div:nth-child(2)'},
    {"key": "CULINARIAN", "display": "Culinarian", "abbrev": "CUL", "icon": "culinarian", "role": "crafter", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(1) > ul:nth-child(2) > li:nth-child(8) > div:nth-child(2)'},
    {"key": "MINER", "display": "Miner", "abbrev": "MIN", "icon": "miner", "role": "gatherer", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(1) > div:nth-child(2)'},
    {"key": "BOTANIST", "display": "Botanist", "abbrev": "BTN", "icon": "botanist", "role": "gatherer", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(2) > div:nth-child(2)'},
    {"key": "FISHER", "display": "Fisher", "abbrev": "FSH", "icon": "fisher", "role": "gatherer", "level_selector": 'div.clearfix:nth-child(5) > div:nth-child(2) > ul:nth-child(2) > li:nth-child(3) > div:nth-child(2)'},
]
