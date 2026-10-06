"""What the app's window shows about the syncing: your upcoming raids (and whether you've
signed up), signups made in game that haven't reached the website yet, and the characters
picked in game. Plain data in, plain data out (tested in tests/test_helper.py).

- `table` is the GargoyleSync table last written for the game (sync_file.sync_table, or
  read back from Gargoyle_Sync\\Data.lua when the app starts).
- `actions` and `picked` are the signups and characters in the game's saved files
  (Syncer.read_saved); `sent` and `uploaded` are what the website said about them (config).
"""
STATUS = {"accepted": "Coming", "tentative": "Tentative", "declined": "Can't come"}
ROLE = {"tank": "Tank", "healer": "Healer", "dps": "Damage"}
CLASS = {"deathknight": "Death Knight", "death_knight": "Death Knight", "demonhunter": "Demon Hunter"}
RAID_LASTS = 4 * 3600  # a raid that started this long ago is no longer shown


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else None


def class_name(token):
    """"MAGE" or "mage" -> "Mage"."""
    if not isinstance(token, str) or not token:
        return ""
    key = token.lower()
    return CLASS.get(key, key.replace("_", " ").title())


def unsent(actions, sent):
    """Signups made in game the website hasn't answered yet."""
    sent = _dict(sent)
    return [a for a in actions if a.get("id") not in sent]


def raids(table, actions, sent, now, made=()):
    """Every upcoming raid in your guilds, soonest first: {id, title, guild, start, size,
    status (None: not signed up), role, character, waiting (a signup made in game, not sent
    yet)}. Raids made in game and not sent yet (`made`, Syncer.new_raids) are in it too, with
    made=True and no id."""
    table = _dict(table)
    guild_names = {g.get("id"): _str(g.get("name")) for g in _list(table.get("guilds")) if isinstance(g, dict)}
    found = [{"id": None, "title": r["title"] or "Raid", "guild": guild_names.get(r["guild"]) or "", "guild_id": r["guild"],
              "start": r["start"], "size": r["size"], "status": None, "role": None, "character": None, "waiting": True,
              "made": True}
             for r in unsent(made, sent) if isinstance(r.get("start"), int) and r["start"] + RAID_LASTS >= now]
    names = {c.get("id"): c.get("name") for c in _list(table.get("characters")) if isinstance(c, dict) and isinstance(c.get("id"), int)}
    latest = {}
    for a in unsent(actions, sent):
        if isinstance(a.get("raid"), int) and (a["raid"] not in latest or (a.get("at") or 0) >= (latest[a["raid"]].get("at") or 0)):
            latest[a["raid"]] = a
    for guild in _list(table.get("guilds")):
        if not isinstance(guild, dict):
            continue
        for raid in _list(guild.get("raids")):
            if not isinstance(raid, dict) or not isinstance(raid.get("start"), int) or raid["start"] + RAID_LASTS < now:
                continue
            size = raid.get("size")
            entry = {"id": raid.get("id"), "title": _str(raid.get("title")) or "Raid", "guild": _str(guild.get("name")) or "",
                     "guild_id": guild.get("id"), "start": raid["start"],
                     "size": size if isinstance(size, int) and not isinstance(size, bool) else None,
                     "status": None, "role": None, "character": None, "waiting": False}
            mine = next((s for s in _list(raid.get("signups")) if isinstance(s, dict) and s.get("mine") is True), None)
            if mine:
                entry.update(status=_str(mine.get("status")), role=_str(mine.get("role")), character=_str(mine.get("name")))
            action = latest.get(raid.get("id"))
            if action:
                entry.update(status=action.get("status"), role=action.get("role"), waiting=True,
                             character=_str(names.get(action.get("character"))) or entry["character"])
            found.append(entry)
    return sorted(found, key=lambda r: r["start"])


def raid_path(raid):
    """The raid on the website (the guild page scrolls to it), or None."""
    guild, raid_id = raid.get("guild_id"), raid.get("id")
    if not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in (guild, raid_id)):
        return None
    return f"/guilds/{guild}#raid-{raid_id}"


def signup_text(raid):
    """"Coming as Healer on Jaina", "Not signed up", ..."""
    if raid.get("made"):
        return "New raid"
    status = STATUS.get(raid["status"])
    if not status:
        return "Not signed up"
    if raid["status"] == "declined":
        return status
    text = status
    if ROLE.get(raid["role"]):
        text += " as " + ROLE[raid["role"]]
    if raid["character"]:
        text += " on " + raid["character"]
    return text


CHARACTER_STATE = {
    "saved": ("ok", "Up to date on gargoyle.gg"),
    "unchanged": ("ok", "Up to date on gargoyle.gg"),
    "limit": ("problem", "Not saved: you have 50 characters from the game already"),
    "removed": ("problem", "Deleted on gargoyle.gg. Pick it again in game to bring it back"),
    "invalid": ("problem", "The website couldn't read it. Open the Characters tab in game to read it again"),
}


def characters(picked, uploaded):
    """The characters picked in game, by name: {key, name, class, level, read, state
    ("ok", "waiting" or "problem"), text}."""
    uploaded = _dict(uploaded)
    found = []
    for c in picked:
        result = _dict(uploaded.get(c["key"]))
        if result.get("at") == c["at"] and result.get("result") in CHARACTER_STATE:
            state, text = CHARACTER_STATE[result["result"]]
        else:
            state, text = "waiting", "Waiting to send"
        found.append({"key": c["key"], "name": c["name"], "class": class_name(c.get("class")), "token": (c.get("class") or "").lower(),
                      "level": c.get("level"), "read": c["at"], "state": state, "text": text})
    return sorted(found, key=lambda c: c["name"].lower())
