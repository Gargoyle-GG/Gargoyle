"""The Data Collector's saved data (addon/Gargoyle_Collector), for Gargoyle's helpers.

Helpers are players who agreed to help keep gargoyle.gg's game data up to date. Once a helper
has typed their helper code into the app's Settings, the app installs the collector addon,
which notes what their game shows them about items, spells, talents and trainers (in
GargoyleCollectorDB, one saved file per WoW account). Nothing is sent on its own: only the
Send collected data button sends it (Syncer.send_collected), in batches, to the website,
which keeps it apart for an admin to look over and merge.

Each saved file has its own id. After sending, the app remembers, for each id, the newest
entry sent, and passes that on in Gargoyle_Sync (GargoyleSync.collected), so the addon clears
what was sent at the next login and only newer entries are sent next time.
"""
import json
import re
from pathlib import Path

from lua_io import LuaError, read_saved

KINDS = ("items", "spells", "talents", "trainers")
FILE_ID = re.compile(r"^[0-9a-f]{1,20}$")
CLASS = re.compile(r"^[A-Z]{2,20}$")
MAX_BYTES = 20 * 1024 * 1024  # (lua_io's limit too; checked before the file is read in)
BATCH_BYTES = 160 * 1024  # in one request (the website takes up to 256 KB)
BATCH_ENTRIES = 400
MAX_SEND = 12000  # entries in one Send (more go with the next one)


def files(game_folder):
    """The collector's saved data, one file per WoW account on this PC."""
    return sorted((Path(game_folder) / "WTF" / "Account").glob("*/SavedVariables/Gargoyle_Collector.lua"))


def _key(kind, key):
    if kind == "talents":
        return key if isinstance(key, str) and CLASS.match(key) else None
    return key if isinstance(key, int) and not isinstance(key, bool) and 0 < key < 10**9 else None


def entries(saved):
    """(the file's id, [{kind, key, build, seen, data}]) from a saved file's variables, or
    (None, []) if it isn't the collector's."""
    db = saved.get("GargoyleCollectorDB") if isinstance(saved, dict) else None
    if not isinstance(db, dict) or db.get("v") != 1 or not isinstance(db.get("id"), str) or not FILE_ID.match(db["id"]):
        return None, []
    found = []
    for kind in KINDS:
        table = db.get(kind)
        if isinstance(table, list):  # (a Lua table numbered 1..n reads as a list)
            table = dict(enumerate(table, 1))
        for key, entry in (table.items() if isinstance(table, dict) else ()):
            if _key(kind, key) is None or not isinstance(entry, dict):
                continue
            seen, build = entry.get("seen"), entry.get("build")
            if not isinstance(seen, int) or isinstance(seen, bool):
                continue
            data = {k: v for k, v in entry.items() if k not in ("seen", "build")}
            found.append({"kind": kind, "key": key, "build": build if isinstance(build, int) else None, "seen": seen,
                          "data": data})
    return db["id"], found


def read(path):
    """(the file's id, its entries); LuaError or OSError if it can't be read."""
    if path.stat().st_size > MAX_BYTES:
        raise LuaError("it's far bigger than the collector's saved data should be")
    return entries(read_saved(path.read_text(encoding="utf-8", errors="replace")))


def waiting(found, marks):
    """The entries not sent yet: newer than the newest one sent from their file."""
    mark = marks.get(found[0]) if isinstance(marks, dict) else None
    return [e for e in found[1] if not isinstance(mark, int) or e["seen"] > mark]


def counts(entries_):
    """{"items": 12, "spells": 30, ...} for what's shown in the app."""
    out = dict.fromkeys(KINDS, 0)
    for e in entries_:
        out[e["kind"]] += 1
    return out


def describe(numbers):
    """"12 items, 30 spells and a talent tree" (or "nothing")."""
    spells = numbers.get("spells", 0) + numbers.get("trainers", 0)
    trees = numbers.get("talents", 0)
    parts = [f"{n:,} {word}{'s' if n != 1 else ''}" for n, word in ((numbers.get("items", 0), "item"), (spells, "spell"))
             if n]
    if trees:
        parts.append("a talent tree" if trees == 1 else f"{trees} talent trees")
    if not parts:
        return "nothing"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def batches(entries_):
    """The entries as the website takes them ({kind, key, build, data}), in batches that fit
    in one request."""
    batch, size = [], 0
    for e in entries_:
        item = {"kind": e["kind"], "key": e["key"], "build": e["build"], "data": e["data"]}
        length = len(json.dumps(item, separators=(",", ":"))) + 1
        if batch and (size + length > BATCH_BYTES or len(batch) == BATCH_ENTRIES):
            yield batch
            batch, size = [], 0
        if length <= BATCH_BYTES:  # (one entry too big to ever send is left out)
            batch.append(item)
            size += length
    if batch:
        yield batch
