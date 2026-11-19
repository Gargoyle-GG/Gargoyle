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
ns.LOOT_VENDORS = { { name = "Stormwind", rep = true, items = { 1156 } }, { name = "Stormwind City", rep = false, items = { 1156 } } }
ns.LOOT_SETS = { { name = "Defias Leather", pieces = 5, level = 17, bonuses = { { 2, "+5 Arcane Resistance." } }, items = { 10399 } },
                 { name = "Arugal's Garb", pieces = 3, level = 60, bonuses = {}, items = { 6392 } } }
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


def plain(text):
    """A text without its colours."""
    return re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", text)


def menu(game, current):
    """The menu of the dropdown showing `current` (made as when it's opened)."""
    w = next(w for w in game.fake.widgets.values() if w.kind == "DropdownButton" and w.IsVisible(w) and w.text == current)
    w.GenerateMenu(w)
    return w.menu


def items(description):
    return list(description["items"].values())


def radios(description):
    return [i.text for i in items(description) if i.kind == "radio"]


def sources(game):
    """The dropdowns along the top that pick where items come from (the group, its list, the
    boss), as shown: the ones before the filters (slot, type) and whose upgrades."""
    return game.dropdowns()[:-3]


def buttons(game):
    return [w.text for w in game.fake.widgets.values() if w.kind == "Button" and w.IsVisible(w)]


def test_the_dropdowns_pick_a_group_one_of_its_list_and_a_boss():
    game = loot_game()
    assert len(names(game)) == 7 and "Everything" in game.texts()  # (to start with: every item)
    assert sources(game) == ["Everything"]  # (no second or third dropdown)
    assert radios(menu(game, "Everything")) == ["Everything", "Wishlist (0)", "Dungeons", "Raids", "Merchants and reputation",
                                                "Professions", "Item sets"]
    game.choose_in("Everything", "Wishlist (0)")
    assert "Nothing on Jainamage's wishlist yet: click an item's star to add it." in game.texts()
    assert sources(game) == ["Wishlist (0)"]
    # A whole group: every dungeon's items, under each place and boss.
    game.choose_in("Wishlist (0)", "Dungeons")
    text = game.texts()
    assert sources(game) == ["Dungeons", "All dungeons"]
    assert "Deadmines  ·  Rhahk'Zor" in text and "All dungeons" in text and "Onyxia" not in text
    assert names(game) == ["Blackened Defias Armor", "Rhahk'Zor's Hammer", "Rockslicer"]
    assert "3 items, " in text and "2 upgrades" in text and game.db.loot.cat == "dungeon" and game.db.loot.index is None
    places = menu(game, "All dungeons")
    assert radios(places) == ["All dungeons", "Deadmines"] and places.scroll == 320  # (a long list scrolls)
    # One of its list, then one boss.
    game.choose_in("All dungeons", "Deadmines")
    assert sources(game) == ["Dungeons", "Deadmines", "All bosses"] and game.db.loot.index == 1
    assert "Rhahk'Zor" in game.texts() and "Deadmines  ·  Rhahk'Zor" not in game.texts()
    bosses = menu(game, "All bosses")
    assert radios(bosses) == ["All bosses", "Rhahk'Zor", "Edwin VanCleef"] and bosses.scroll == 320
    game.choose_in("All bosses", "Edwin VanCleef")
    assert names(game) == ["Blackened Defias Armor"] and "Deadmines  ·  Edwin VanCleef" in game.texts()
    assert game.db.loot.boss == 2 and sources(game) == ["Dungeons", "Deadmines", "Edwin VanCleef"]
    game.choose_in("Edwin VanCleef", "Rhahk'Zor")
    assert names(game) == ["Rhahk'Zor's Hammer", "Rockslicer"]
    # The same place on the Dungeons tab, and back: where it was.
    game.click("Open in Dungeons")
    assert game.db.journal.place == 36 and "upgrades|r here for Jainamage" in game.texts()  # (Deadmines, on the Dungeons tab)
    game.ns.ShowModule("loot")  # (the tab: the Dungeons tab has a Loot button of its own)
    assert sources(game) == ["Dungeons", "Deadmines", "Rhahk'Zor"] and names(game) == ["Rhahk'Zor's Hammer", "Rockslicer"]
    # All the place's bosses again; all the dungeons: no place or boss picked.
    game.choose_in("Rhahk'Zor", "All bosses")
    assert len(names(game)) == 3 and game.db.loot.boss is None
    game.choose_in("All bosses", "Edwin VanCleef")
    game.choose_in("Deadmines", "All dungeons")
    assert sources(game) == ["Dungeons", "All dungeons"] and game.db.loot.index is None and game.db.loot.boss is None
    # Another group: all of it. A raid with one boss: no third dropdown.
    game.choose_in("All dungeons", "Deadmines")
    game.choose_in("Dungeons", "Raids")
    assert sources(game) == ["Raids", "All raids"] and game.db.loot.index is None and game.db.loot.boss is None
    assert names(game) == ["Belt of Arugal", "Rockslicer"] and "Onyxia's Lair  ·  Onyxia" in game.texts()
    game.choose_in("All raids", "Onyxia's Lair")
    assert sources(game) == ["Raids", "Onyxia's Lair"] and names(game) == ["Belt of Arugal", "Rockslicer"]
    assert "Open in Dungeons" in buttons(game)
    game.choose_in("Raids", "Professions")
    assert names(game) == ["Chausses of Westfall"] and "Leatherworking (skill 120)" in game.texts()
    assert sources(game) == ["Professions", "All professions"]
    assert radios(menu(game, "All professions")) == ["All professions", "Leatherworking"]
    assert "Open in Dungeons" not in buttons(game)
    # Merchants and reputation: factions, then merchants by place.
    game.choose_in("Professions", "Merchants and reputation")
    assert "Sold by Lisbeth Schneider, Stormwind City · Stormwind, Honored" in plain(game.texts())
    assert [(i.kind, i.text) for i in items(menu(game, "All merchants and reputation"))] == [
        ("radio", "All merchants and reputation"), ("title", "Reputation"), ("radio", "Stormwind"),
        ("title", "Merchants, by place"), ("radio", "Stormwind City")]
    game.choose_in("All merchants and reputation", "Stormwind City")
    assert names(game) == ["Lavishly Jeweled Ring"] and game.db.loot.index == 2
    assert sources(game) == ["Merchants and reputation", "Stormwind City"]
    game.choose_in("Merchants and reputation", "Everything")
    assert sources(game) == ["Everything"] and len(names(game)) == 7


def test_each_row_shows_the_item_in_columns():
    game = loot_game()
    search(game, "ring")
    row = rows(game)["Lavishly Jeweled Ring"]
    assert plain(row.name.text) == "Lavishly Jeweled Ring New"
    assert plain(row["from"].text) == "Sold by Lisbeth Schneider, Stormwind City · Stormwind, Honored"  # (in full)
    assert (plain(row.slotText.text), row.typeText.text, plain(row.levelText.text)) == ("Finger", "", "Level 18")
    search(game, "")
    shown = list(rows(game).values())
    assert len(shown) == 7
    for part in ("name", "from", "slotText", "typeText", "levelText"):  # (each in its column: they line up)
        assert len({(r[part].point[1], r[part].point[2], r[part].width) for r in shown}) == 1, part
    # The columns side by side, within the row, the source the widest.
    first = shown[0]
    name, slot, level = first.name, first.slotText, first.levelText
    assert name.point[2] + name.width < slot.point[2] and slot.point[2] + slot.width < level.point[2]
    assert level.point[2] + level.width + first.gain.width + 6 + 16 + 6 <= first.width
    assert first["from"].width >= 450
    tunic = rows(game)["Tunic of Westfall"]
    assert plain(tunic.slotText.text) == "Chest" and plain(tunic.typeText.text) == "Leather"
    assert plain(tunic.gain.text).startswith("+7")
    belt = rows(game)["Belt of Arugal"]
    assert plain(belt.levelText.text) == "Level 62" and belt.levelText.text.startswith("|cffff5f5f")  # (above your level)
    # 12 rows (11 before), the whole width of the window's content (800 wide, less 10 a side), down
    # to the line along the bottom (two lines of 12, 6 from the bottom).
    lines = [w for w in game.fake.widgets.values() if w.kind == "Button" and w.slotText]
    assert len(lines) == 12 and {r.width for r in lines} == {776}
    listed = lines[0].parent
    assert listed.width == 776 and -listed.point[3] + listed.height <= (540 - 62 - 34) - 30


def test_item_sets_by_class():
    game = loot_game()
    game.choose_in("Everything", "Item sets")
    assert sources(game) == ["Item sets", "All item sets"] and names(game) == ["Belt of Arugal", "Blackened Defias Armor"]
    sets = menu(game, "All item sets")
    assert radios(sets) == ["All item sets"]
    groups = [(i.text, radios(i), i.scroll) for i in items(sets) if i.kind == "button"]
    # (Belt of Arugal is for mages, priests and warlocks: its set is under each; Defias Leather's piece is for anyone)
    assert groups == [("Priest (1)", ["Arugal's Garb"], 320), ("Mage (1)", ["Arugal's Garb"], 320),
                      ("Warlock (1)", ["Arugal's Garb"], 320), ("Any class (1)", ["Defias Leather"], 320)]
    game.choose_in("All item sets", "Arugal's Garb")
    assert sources(game) == ["Item sets", "Arugal's Garb"]  # (once, though it's in three lists)
    assert names(game) == ["Belt of Arugal"]
    game.choose_in("Arugal's Garb", "Defias Leather")
    assert "2 pieces: +5 Arcane Resistance." in game.texts() and "you wear 0" in game.texts()
    game.click("Try on the set")
    assert list(game.fake.dressed.values()) == ["link"]


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
    game.choose_in("Everything", "Raids")
    assert names(game) == ["Rockslicer"] and "Search: raids" in game.texts()
    search(game, "westfall")  # (not from a raid)
    assert names(game) == [] and "0 items. Items not seen in play yet" in game.texts()
    # The search and filters within one boss: they stay as you pick.
    search(game, "")
    game.choose_in("Raids", "Dungeons")
    game.choose_in("All dungeons", "Deadmines")
    game.choose_in("All bosses", "Rhahk'Zor")
    assert names(game) == ["Rhahk'Zor's Hammer", "Rockslicer"]
    search(game, "hammer")
    assert names(game) == ["Rhahk'Zor's Hammer"]
    search(game, "")
    check(game, "Usable by me")  # (a mage: no axe)
    assert names(game) == ["Rhahk'Zor's Hammer"]
    check(game, "Upgrades only")  # (the hammer isn't one)
    assert names(game) == [] and sources(game) == ["Dungeons", "Deadmines", "Rhahk'Zor"]
    game.choose_in("Rhahk'Zor", "All bosses")
    assert names(game) == ["Blackened Defias Armor"]


def test_stars_clicks_and_tooltips():
    game = loot_game(api=WISH_API)
    game.choose_in("Everything", "Wishlist (1)")
    assert names(game) == ["Rhahk'Zor's Hammer"] and "Deadmines" in game.texts()  # (the wishlist, by where it drops)
    game.choose_in("Wishlist (1)", "Everything")
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
    assert "Wishlist (2)" in radios(menu(game, "Everything"))
    game.choose_in("Everything", "Wishlist (2)")
    assert names(game) == ["Rhahk'Zor's Hammer", "Rockslicer"] and "Deadmines" in game.texts()


def test_saved_choices_from_before_the_dropdowns():
    def start(saved):
        game = Game(sync_lua(JOURNAL_API, {}), "GargoyleDB = { loot = " + saved + " }", journal=JOURNAL, loot=True,
                    loot_data=LOOT, before=ITEMS)
        game.slash()
        game.click("Loot")
        return game
    # 1.0.6 and before: a dungeon picked, and the groups open on the left (kept no more).
    game = start("{ cat = 'dungeon', index = 1, open = { dungeon = true, set = true }, slot = 'chest' }")
    assert game.db.loot.open is None and game.db.loot.cat == "dungeon" and game.db.loot.index == 1 and game.db.loot.boss is None
    assert sources(game) == ["Dungeons", "Deadmines", "All bosses"] and names(game) == ["Blackened Defias Armor"]
    # A whole group, open or not.
    game = start("{ cat = 'set', open = { set = true } }")
    assert sources(game) == ["Item sets", "All item sets"] and len(names(game)) == 2
    # A place or boss that's gone, or odd values: all of it.
    game = start("{ cat = 'dungeon', index = 9, boss = 2, slot = 5 }")
    assert game.db.loot.index is None and game.db.loot.boss is None and game.db.loot.slot is None
    assert sources(game) == ["Dungeons", "All dungeons"] and len(names(game)) == 3
    game = start("{ cat = 'raid', index = 1, boss = 'Onyxia' }")
    assert game.db.loot.boss is None and sources(game) == ["Raids", "Onyxia's Lair"]
    # A boss picked last time, kept.
    game = start("{ cat = 'dungeon', index = 1, boss = 2 }")
    assert sources(game) == ["Dungeons", "Deadmines", "Edwin VanCleef"] and names(game) == ["Blackened Defias Armor"]
    # The 1.0.0 betas' "place": everything.
    game = start("{ cat = 'place', index = 1 }")
    assert game.db.loot.cat == "all" and game.db.loot.index is None and sources(game) == ["Everything"]


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
    every = list(ns.LOOT_ITEMS.values())
    ids = {it.id for it in every}
    assert len(every) > 2000 and len(ids) == len(every)
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
    # (the launch dungeons the game data doesn't list have no game id yet: the addon finds them by name)
    no_id = {p.name for p in ns.LOOT_PLACES.values() if not p.id}
    assert no_id <= {"The Drowned City", "Krol'dok Stronghold", "Alcaz Prison", "Blackmaw Hold", "Shaper's Terrace"}
    game.slash()
    game.click("Loot")
    search(game, "of the")
    assert "items" in game.texts()
    search(game, "")
    # Every group, each of its list (sets by class), and each boss: picked from the dropdowns.
    group = "Everything"
    for g in radios(menu(game, group)):
        game.choose_in(group, g)
        group = g
        assert sources(game)[0] == g and "item" in game.texts()
        if len(sources(game)) == 1:
            continue
        place = sources(game)[1]
        listed = menu(game, place)
        choices = radios(listed) + [r for i in items(listed) if i.kind == "button" for r in radios(i)]
        assert len(choices) > 1, g
        if g == "Item sets":  # (by class, each long list scrolling)
            subs = [i for i in items(listed) if i.kind == "button"]
            assert len(subs) >= 9 and all(i.scroll == 320 for i in subs)
            assert sum(len(radios(i)) for i in subs) >= len(ns.LOOT_SETS)
        for c in choices[1:]:
            game.choose_in(place, c)
            place = c
            assert sources(game)[1] == c and "item" in game.texts(), (g, c)
            if len(sources(game)) == 3:
                boss = "All bosses"
                for b in radios(menu(game, boss))[1:]:
                    game.choose_in(boss, b)
                    boss = b
                    assert sources(game)[2] == b and names(game), (c, b)
                game.choose_in(boss, "All bosses")
    # Each row's source in full, and room for the longest (the game's small font: about 5.5 wide a letter).
    places = list(ns.LOOT_PLACES.values())

    def source(s):
        kind = s[1]
        if kind == "drop":
            return f"{places[s[2] - 1].name} · {s[3]}" + (f" · {chance(s[4])}" if s[4] is not None else "")
        if kind == "quest":
            return f"Quest: {s[2]}" + (f" ({places[s[3] - 1].name})" if s[3] is not None and 0 < s[3] <= len(places) else "")
        if kind == "craft":
            return f"{s[2]} (skill {s[3] or 0})"
        if kind == "vendor":
            return f"Sold by {s[2]}, {s[3]}" + (f" · {s[5]}, {s[6]}" if s[5] else "")
        return f"{s[2]}, {s[3]}"

    def chance(pct):
        return f"{int(pct + 0.5)}%" if pct >= 10 else f"{pct:.1f}".removesuffix(".0") + "%"

    def where(it):
        froms = list(it["from"].values())
        return source(froms[0]) + (f" (and {len(froms) - 1} more)" if len(froms) > 1 else "")

    longest = max((it for it in every if it["from"]), key=lambda it: len(where(it)))
    game.choose_in(group, "Everything")
    search(game, longest.name)
    shown = [plain(w["from"].text) for w in game.fake.widgets.values() if w.kind == "Button" and w.IsVisible(w) and w.slotText
             and plain(w.name.text).startswith(longest.name)]
    assert where(longest) in shown
    width = next(w["from"].width for w in game.fake.widgets.values() if w.kind == "Button" and w.slotText)
    assert len(where(longest)) * 5.5 <= width, where(longest)
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
