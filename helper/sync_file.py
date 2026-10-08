"""The Gargoyle_Sync data addon the app writes, and what it reads from GargoyleDB: the
signups made in game (the outbox), the raids officers made in game (newRaids) and the
characters picked to keep up to date.

The website's answer (/api/app/sync) becomes the GargoyleSync table that the Gargoyle
addon reads at login (addon/Gargoyle/Core.lua, ns.ReadSync). Only the fields the addon
uses are copied, each checked for its type and cut to length on the way.
"""
import re

from lua_io import to_lua

VERSION = 1  # GargoyleSync.version; the addon ignores a table it doesn't know
ACTION_ID = re.compile(r"^[A-Za-z0-9:._-]{1,40}$")  # what the website accepts (app_api.py)
MAX_TALENTS, MAX_SPELLS = 60, 10  # per character's talent plan, per talent
MAX_UPGRADES = 700  # per character: the drops that are upgrades for it (the website's limit too)
STATUSES = ("accepted", "tentative", "declined")
ROLES = ("tank", "healer", "dps")


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _list(value):
    return value if isinstance(value, list) else []


def _signup(s):
    if not isinstance(s, dict) or not _text(s.get("name"), 60):
        return None
    out = {"name": _text(s["name"], 60), "class": _text(s.get("class"), 20), "role": _text(s.get("role"), 10),
           "status": _text(s.get("status"), 10), "note": _text(s.get("note"), 200)}
    if s.get("mine") is True:
        out.update(mine=True, character=_int(s.get("character")), changed=_int(s.get("changed")))
    return out


def _raid(r):
    if not isinstance(r, dict) or _int(r.get("id")) is None or _int(r.get("start")) is None:
        return None
    return {"id": r["id"], "title": _text(r.get("title"), 80), "start": r["start"], "size": _int(r.get("size")),
            "notes": _text(r.get("notes"), 1000),
            "signups": [x for x in map(_signup, _list(r.get("signups"))) if x]}


def _guild(g):
    if not isinstance(g, dict) or _int(g.get("id")) is None or not _text(g.get("name"), 60):
        return None
    return {"id": g["id"], "name": _text(g["name"], 60), "game": _text(g.get("game_name"), 60),
            "officer": g.get("officer") is True, "raids": [x for x in map(_raid, _list(g.get("raids"))) if x]}


def _talent(t):
    if not isinstance(t, dict) or not _text(t.get("name"), 60):
        return None
    tree, rank = _int(t.get("tree")), _int(t.get("rank"))
    if tree is None or not 1 <= tree <= 5 or rank is None or not 1 <= rank <= 10:
        return None
    return {"tree": tree, "name": _text(t["name"], 60), "rank": rank,
            "spells": [s for s in _list(t.get("spells")) if _int(s) is not None and s > 0][:MAX_SPELLS]}


def _number(value, low, high):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high
    return value if ok else None


def _upgrades(u):
    """The drops the website's planner found are upgrades: [[item id, gain, gain %]], best first."""
    if not isinstance(u, dict):
        return None
    rows = []
    for row in _list(u.get("items"))[:MAX_UPGRADES]:
        if (isinstance(row, list) and len(row) == 3 and _int(row[0]) is not None and 0 < row[0] < 10_000_000
                and _number(row[1], 0, 100_000) is not None and _number(row[2], 0, 1000) is not None):
            rows.append([row[0], row[1], row[2]])
    level = _int(u.get("level"))
    return {"items": rows, "spec": _text(u.get("spec"), 40), "level": level if level and 1 <= level <= 60 else None,
            "stale": u.get("stale") is True, "at": _int(u.get("at"))}


def _character(c):
    if not isinstance(c, dict) or _int(c.get("id")) is None or not _text(c.get("name"), 60):
        return None
    out = {"id": c["id"], "name": _text(c["name"], 60), "class": _text(c.get("class"), 20),
           "guild": _int(c.get("guild")), "role": _text(c.get("role"), 10),
           "talents": [x for x in map(_talent, _list(c.get("talents"))) if x][:MAX_TALENTS]}
    if _text(c.get("game"), 80):
        out.update(game=_text(c["game"], 80), read=_int(c.get("read")))
    upgrades = _upgrades(c.get("upgrades"))
    if upgrades:
        out["upgrades"] = upgrades
    return out


def _strings(table, value_type):
    return {k[:80]: v for k, v in (table if isinstance(table, dict) else {}).items()
            if isinstance(k, str) and isinstance(v, value_type) and not isinstance(v, bool)}


def sync_table(api, done, imports=None):
    """GargoyleSync from the website's /api/app/sync answer, plus the outbox ids the
    website has answered ({id: "saved" / "stale" / ...}) so the addon can let them go, and
    what the website said about each picked character ({key: "saved" / "limit" / ...}).
    can_make_raids tells the addon this app sends raids made in game, sends_talents that it
    passes on each character's talents for talent plans, and sends_upgrades that it passes on
    their upgrade picks for the dungeon journal (older ones do none of these)."""
    api = api if isinstance(api, dict) else {}
    return {
        "version": VERSION,
        "can_make_raids": True,
        "sends_talents": True,
        "sends_upgrades": True,
        "synced": _int(api.get("time")),
        "user": _text(api.get("user"), 60),
        "characters": [x for x in map(_character, _list(api.get("characters"))) if x],
        "guilds": [x for x in map(_guild, _list(api.get("guilds"))) if x],
        "done": _strings(done, str),
        "removed": _strings(api.get("removed"), int),
        "imports": _strings(imports, str),
    }


def sync_lua(api, done, imports=None):
    """The whole Data.lua file."""
    return ("-- Written by the Gargoyle app from your Gargoyle account. Don't edit: it's replaced\n"
            "-- on every sync. The Gargoyle addon reads it when you log in or /reload.\n"
            "GargoyleSync = " + to_lua(sync_table(api, done, imports)) + "\n")


def toc(interface):
    """Gargoyle_Sync.toc, with the same game version as the installed Gargoyle addon so
    the game never marks it out of date."""
    return (f"## Interface: {interface}\n"
            "## Title: Gargoyle Sync\n"
            "## Notes: Raid data for the Gargoyle addon, written by the Gargoyle app.\n"
            "## Author: Gargoyle\n"
            "\nData.lua\n")


def outbox(saved):
    """Signups made in game and not yet confirmed, from a read GargoyleDB file
    (lua_io.read_saved), as the website's /api/app/signups wants them."""
    db = saved.get("GargoyleDB") if isinstance(saved, dict) else None
    actions = []
    for a in _list(db.get("outbox")) if isinstance(db, dict) else []:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not ACTION_ID.match(a["id"]):
            continue
        actions.append({"id": a["id"], "raid": _int(a.get("raid")), "character": _int(a.get("character")),
                        "status": _text(a.get("status"), 10), "role": _text(a.get("role"), 10),
                        "note": _text(a.get("note"), 200) or "", "at": _int(a.get("at"))})
    return actions


def new_raids(saved):
    """Raids officers made in game and the website hasn't confirmed yet (GargoyleDB.newRaids),
    as the website's /api/app/raids wants them, from a read GargoyleDB file."""
    db = saved.get("GargoyleDB") if isinstance(saved, dict) else None
    raids = []
    for r in _list(db.get("newRaids")) if isinstance(db, dict) else []:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not ACTION_ID.match(r["id"]):
            continue
        raids.append({"id": r["id"], "guild": _int(r.get("guild")), "title": _text(r.get("title"), 80) or "",
                      "start": _int(r.get("start")), "size": _int(r.get("size")),
                      "notes": _text(r.get("notes"), 1000) or "", "at": _int(r.get("at"))})
    return raids


def _parts(value, fields, limit):
    """A list of small tables with number and text fields, as the website wants them; None
    (the addon couldn't read that part) stays None."""
    if not isinstance(value, list):
        return None
    return [{f: _text(entry.get(f), 60) if kind is str else _int(entry.get(f)) for f, kind in fields.items()}
            for entry in value[:limit] if isinstance(entry, dict)]


def characters(saved):
    """The characters picked in game to keep up to date (GargoyleDB.characters), as the
    website's /api/app/characters wants them, from a read GargoyleDB file."""
    db = saved.get("GargoyleDB") if isinstance(saved, dict) else None
    table = db.get("characters") if isinstance(db, dict) else None
    found = []
    for key, c in (table if isinstance(table, dict) else {}).items():
        if not isinstance(key, str) or not 0 < len(key) <= 80 or not isinstance(c, dict):
            continue
        if _int(c.get("picked")) is None or _int(c.get("at")) is None or not _text(c.get("name"), 60):
            continue  # (just picked, not read yet)
        found.append({
            "key": key, "picked": c["picked"], "at": c["at"], "name": _text(c["name"], 60),
            "class": _text(c.get("class"), 20), "race": _text(c.get("race"), 30),
            "race_name": _text(c.get("race_name"), 40), "faction": _text(c.get("faction"), 20),
            "level": _int(c.get("level")),
            "talents": _parts(c.get("talents"), {"tab": int, "row": int, "col": int, "rank": int, "name": str, "spell": int}, 150),
            "gear": _parts(c.get("gear"), {"slot": int, "item": int, "enchant": int}, 25),
            "skills": _parts(c.get("skills"), {"name": str, "rank": int}, 80),
        })
    return found
