"""Gargoyle Loot (addon/Gargoyle_Loot), in the stand-in game of tests/test_addon.py: every item
and where it comes from, search and filters, upgrades, the wishlist, trying items on."""
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("lupa")
from test_addon import ITEMS, JOURNAL, JOURNAL_API, PROJECT, Game, click_row, wishes  # noqa: E402
from sync_file import sync_lua  # noqa: E402

LOOT = """
local _, ns = ...
ns.LOOT_ITEMS = {
  { id = 872, name = "Rockslicer", q = 3, slot = "two_hand", type = "axe", level = 20, ilvl = 25,
    classes = { "warrior", "paladin", "shaman", "hunter" }, from = { { "drop", 1, "Rhahk'Zor", 20 } } },
  { id = 5187, name = "Rhahk'Zor's Hammer", q = 2, slot = "two_hand", type = "mace", level = 15,
    from = { { "drop", 1, "Rhahk'Zor", 80 } } },
  { id = 2041, name = "Tunic of Westfall", q = 2, slot = "chest", type = "leather", level = 18,
    from = { { "quest", "The Defias Brotherhood", 1, "Alliance" } } },
  { id = 10399, name = "Blackened Defias Armor", q = 3, slot = "chest", type = "leather", level = 20, set = "Defias Leather",
    from = { { "drop", 1, "Edwin VanCleef" } } },
  { id = 6087, name = "Chausses of Westfall", q = 2, slot = "legs", type = "mail", level = 22, side = "Horde",
    from = { { "craft", "Leatherworking", 120, "Trainer", { { 2318, 4 } } } } },
  { id = 1156, name = "Lavishly Jeweled Ring", q = 3, slot = "finger", level = 18, new = true,
    from = { { "vendor", "Lisbeth Schneider", "Stormwind City", "Alliance", "Stormwind", "Honored" } } },
  { id = 6392, name = "Belt of Arugal", q = 3, slot = "waist", type = "cloth", level = 62, classes = { "mage", "priest", "warlock" } },
}
ns.LOOT_PLACES = {
  { id = 36, name = "Deadmines", bosses = { { name = "Rhahk'Zor", items = { 872, 5187 } }, { name = "Edwin VanCleef", items = { 10399 } } } },
  { id = 249, name = "Onyxia's Lair", raid = true, when = "Opens December 9", bosses = { { name = "Onyxia", items = { 6392, 872 } } } },
}
ns.LOOT_CRAFTING = { { name = "Leatherworking", items = { 6087 } } }
ns.LOOT_VENDORS = { { name = "Stormwind", rep = true, items = { 1156 } } }
ns.LOOT_SETS = { { name = "Defias Leather", pieces = 5, level = 17, bonuses = { { 2, "+5 Arcane Resistance." } }, items = { 10399 } } }
"""
WISH_API = {**JOURNAL_API, "characters": [{**JOURNAL_API["characters"][0], "wishlist": [5187]},
                                          JOURNAL_API["characters"][1]]}


def loot_game(api=JOURNAL_API, before="", **kwargs):
    game = Game(sync_lua(api, {}), None, journal=JOURNAL, loot=True, loot_data=LOOT, before=ITEMS + "\n" + before, **kwargs)
    game.slash()
    game.click("Loot")
    return game


def rows(game):
    """The item rows shown: {item name: row}."""
    return {re.sub(r"\|c[0-9a-fA-F]{8}", "", w.name.text).split("|r")[0]: w for w in game.fake.widgets.values()
            if w.kind == "Button" and w.IsVisible(w) and w.star and w.star.IsVisible(w.star)}


def names(game):
    return sorted(rows(game))


def search(game, text):
    box = next(w for w in game.fake.widgets.values() if w.kind == "EditBox" and w.IsVisible(w))
    box.SetText(box, text)
    box.scripts.OnTextChanged(box, True)


def checkbox(game, label):
    """The checkbox labelled `label` (its label sits to its right)."""
    return next(f.point[2] for f in game.fake.widgets.values() if f.kind == "FontString" and f.text.startswith(label)
                and f.point and f.point[2] and f.point[2].kind == "CheckButton")


def check(game, label):
    box = checkbox(game, label)
    box.SetChecked(box, not box.GetChecked(box))
    box.scripts.OnClick(box)


def test_the_loot_tab_lists_items_by_group_and_one_by_one():
    game = loot_game()
    assert len(names(game)) == 7 and "Everything" in game.texts()  # (to start with: every item)
    click_row(game, "Wishlist")
    assert "Nothing on Jainamage's wishlist yet: click an item's star to add it." in game.texts()
    # A whole group: every dungeon's items, under each place and boss; it opens its list.
    click_row(game, "Dungeons")
    text = game.texts()
    assert "Deadmines  ·  Rhahk'Zor" in text and "All dungeons" in text and "Onyxia" not in text
    assert names(game) == ["Blackened Defias Armor", "Rhahk'Zor's Hammer", "Rockslicer"]
    assert "3 items, " in text and "2 upgrades" in text and game.db.loot.cat == "dungeon" and game.db.loot.index is None
    click_row(game, "Raids")
    assert names(game) == ["Belt of Arugal", "Rockslicer"] and "Onyxia's Lair  ·  Onyxia" in game.texts()
    # One of its list.
    click_row(game, "Deadmines")
    assert "Rhahk'Zor" in game.texts() and "Deadmines  ·  Rhahk'Zor" not in game.texts() and game.db.loot.index == 1
    # The same place on the Dungeons tab.
    game.click("Open in Dungeons")
    assert game.db.journal.place == 36 and "upgrades|r here for Jainamage" in game.texts()  # (Deadmines, on the Dungeons tab)
    game.ns.ShowModule("loot")  # (the tab: the Dungeons tab has a Loot button of its own)
    # Picking a group that's picked closes its list.
    click_row(game, "Dungeons")
    assert "   Deadmines" in game.texts()
    click_row(game, "Dungeons")
    assert "   Deadmines" not in game.texts() and game.db.loot.open.dungeon is None
    click_row(game, "Professions")
    assert names(game) == ["Chausses of Westfall"] and "Leatherworking (skill 120)" in game.texts()
    click_row(game, "Merchants and reputation")
    assert "Sold by Lisbeth Schneider, Stormwind City · Stormwind, Honored" in game.texts()


def test_search_and_filters():
    game = loot_game()
    search(game, "westfall")  # (everything)
    assert names(game) == ["Chausses of Westfall", "Tunic of Westfall"]
    search(game, "defias")  # (names, and where they come from)
    assert names(game) == ["Blackened Defias Armor", "Tunic of Westfall"]
    search(game, "")
    search(game, "a")
    assert len(names(game)) == 7
    check(game, "Usable by me")  # (a level 60 Alliance mage: no axe, nothing for the Horde)
    assert "Rockslicer" not in names(game) and "Chausses of Westfall" not in names(game) and "Belt of Arugal" in names(game)
    check(game, "Up to my level")
    assert "Belt of Arugal" not in names(game)
    check(game, "Upgrades only")
    assert names(game) == ["Blackened Defias Armor", "Tunic of Westfall"]
    check(game, "Upgrades only")
    game.choose("Finger")
    assert names(game) == ["Lavishly Jeweled Ring"] and game.db.loot.slot == "finger"
    game.choose_in("Finger", "Any slot")
    game.choose("Leather")
    assert names(game) == ["Blackened Defias Armor", "Tunic of Westfall"]
    # The search, within a group.
    game.choose_in("Leather", "Any type")
    check(game, "Usable by me")
    check(game, "Up to my level")
    search(game, "rock")
    click_row(game, "Raids")
    assert names(game) == ["Rockslicer"] and "Search: raids" in game.texts()
    search(game, "westfall")  # (not from a raid)
    assert names(game) == [] and "0 items. Items above the beta's level cap" in game.texts()


def test_stars_clicks_tooltips_and_sets():
    game = loot_game(api=WISH_API)
    click_row(game, "Wishlist")
    assert names(game) == ["Rhahk'Zor's Hammer"] and "Deadmines" in game.texts()  # (the wishlist, by where it drops)
    click_row(game, "Everything")
    search(game, "rock")
    row = rows(game)["Rockslicer"]
    row.star.scripts.OnClick(row.star)
    assert [(w["item"], w["on"]) for w in wishes(game)] == [(872, True)]
    # Pointing at it: the game's tooltip, where it comes from, and what to click.
    row.scripts.OnEnter(row)
    lines = list(game.lua.globals().GameTooltip.lines.values())
    assert lines[0] == "Rockslicer" and "From: Deadmines · Rhahk'Zor · 20%" in lines and "On Jainamage's wishlist" in "\n".join(lines)
    row.scripts.OnClick(row)
    assert list(game.fake.handled.values()) == []
    game.lua.execute('fake.modified = "DRESSUP"')
    row.scripts.OnClick(row)
    assert list(game.fake.handled.values()) == ["link"]
    game.lua.execute("fake.modified = nil")
    search(game, "")
    assert "Wishlist (2)" in game.texts()
    # An old saved choice (the 1.0.0 betas' "place") starts on everything.
    old = Game(sync_lua(JOURNAL_API, {}), "GargoyleDB = { loot = { cat = 'place', index = 1 } }", journal=JOURNAL,
               loot=True, loot_data=LOOT, before=ITEMS)
    assert old.db.loot.cat == "all" and old.db.loot.index is None
    # An item set: its bonuses, and trying it on.
    click_row(game, "Item sets")
    click_row(game, "Defias Leather")
    assert "2 pieces: +5 Arcane Resistance." in game.texts() and "you wear 0" in game.texts()
    game.click("Try on the set")
    assert list(game.fake.dressed.values()) == ["link"]


def test_wishlist_items_are_named_on_entering_their_dungeon():
    game = loot_game(api=WISH_API)
    game.lua.execute('fake.instance = { "Deadmines", "party", 1, "Normal", 5, 0, false, 36 }')
    game.fake.fire("PLAYER_ENTERING_WORLD")
    assert "on Jainamage's wishlist, from Deadmines: link (Rhahk'Zor)." in game.printed()
    check(game, "Tell me in chat which wishlist items")  # (Gargoyle's options)
    assert game.db.loot.tell is False
    game.lua.execute('fake.printed = {}; fake.instance = { "Elwynn Forest", "none", 0, "", 5, 0, false, 0 }')
    game.fake.fire("PLAYER_ENTERING_WORLD")
    game.lua.execute('fake.instance = { "Deadmines", "party", 1, "Normal", 5, 0, false, 36 }')
    game.fake.fire("PLAYER_ENTERING_WORLD")
    assert "wishlist" not in game.printed()


def test_the_real_loot_data():
    game = Game(sync_lua(JOURNAL_API, {}), None, journal=JOURNAL, loot=True, before=ITEMS)
    ns = game.lns
    items = list(ns.LOOT_ITEMS.values())
    ids = {it.id for it in items}
    assert len(items) > 2000 and len(ids) == len(items)
    data = PROJECT / "data" / "items.json"  # (the website's: not in the addon's own repository)
    if data.exists():
        speculative = {int(i["id"]) for i in json.loads(data.read_text(encoding="utf-8"))["items"] if i.get("speculative")}
        assert not ids & speculative
    for name in ("LOOT_PLACES", "LOOT_CRAFTING", "LOOT_VENDORS", "LOOT_SETS"):
        groups = list(ns[name].values())
        assert groups, name
        for g in groups:
            lists = [b["items"] for b in g.bosses.values()] if name == "LOOT_PLACES" else [g["items"]]
            assert all(i in ids for lst in lists for i in lst.values()), (name, g.name)
    assert all(p.id for p in ns.LOOT_PLACES.values())
    game.slash()
    game.click("Loot")
    search(game, "of the")
    assert "items" in game.texts()
    assert Path(PROJECT / "addon" / "Gargoyle_Loot" / "Gargoyle_Loot.toc").read_text(encoding="utf-8").count("## Dependencies: Gargoyle") == 1


def test_stars_only_on_items_in_the_game_now():
    game = loot_game()
    game.click("Dungeons")
    click_row(game, "Deadmines")
    stars = {w.name.text: w.star.IsVisible(w.star) for w in game.fake.widgets.values()
             if w.kind == "Button" and w.IsVisible(w) and w.star and w.name and w.name.text}
    shown = {re.sub(r"\|c[0-9a-fA-F]{8}", "", k).split("|r")[0]: v for k, v in stars.items()}
    # (Rockslicer is in Gargoyle Loot's data; Cruel Barb, which the journal lists, isn't: not in the game yet)
    assert shown["Rockslicer"] is True
    game.lua.execute("GargoyleDB.journal.part = 'loot'")
    game.ns.Journal.PickBoss(2)
    shown = {re.sub(r"\|c[0-9a-fA-F]{8}", "", w.name.text).split("|r")[0]: w.star.IsVisible(w.star)
             for w in game.fake.widgets.values() if w.kind == "Button" and w.IsVisible(w) and w.star and w.name and w.name.text}
    assert shown["Cruel Barb"] is False and shown["Blackened Defias Armor"] is True
