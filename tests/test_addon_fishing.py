"""Gargoyle Fishing (addon/Gargoyle_Fishing), in the stand-in game of tests/test_addon.py: the Cast
Fishing key casts Fishing's cast (not the spell that opens the profession window) through a secure
button, one-key mode makes it Interact With Target with a longer reach while you fish (never in
combat, put back afterwards), nothing ever casts by itself, and /gargoyle fishing test."""
import re
from pathlib import Path

import pytest

pytest.importorskip("lupa")
from test_addon import PROJECT, Game  # noqa: E402

FOLDER = PROJECT / "addon" / "Gargoyle_Fishing"

# What Gargoyle Fishing uses of the game, as WoW Forever's UI code has it (Gethe/wow-ui-source,
# branch forever): key bindings and override bindings, secure action buttons, the character's
# professions, spell channels, and game settings. The game's side is played here as the game does
# it: a key's press and release go to its binding (an override binding first).
FISHING_GAME = r"""
local methods = getmetatable(fake.new("Frame")).__index
local function inCombat(what) if fake.combat then error("Gargoyle Fishing " .. what .. " in combat") end end
function methods:SetAttribute(key, value) inCombat("changed a secure button"); self.attrs = self.attrs or {}; self.attrs[key] = value end
function methods:GetAttribute(key) return (self.attrs or {})[key] end
function methods:RegisterForClicks(...) self.clicks = { ... } end

-- Key bindings: the player's own (key -> command), and the addon's overrides (key -> { owner, command }).
fake.bindings, fake.overrides, fake.bindingChanges = {}, {}, 0
GetBindingKey = function(command)
  local keys = {}
  for key, c in pairs(fake.bindings) do if c == command then table.insert(keys, key) end end
  table.sort(keys)
  return unpack(keys)
end
SetOverrideBinding = function(owner, priority, key, command)
  inCombat("changed a key binding")
  assert(priority == true)
  fake.overrides[key] = command and { owner = owner, command = command } or nil
  fake.bindingChanges = fake.bindingChanges + 1
end
ClearOverrideBindings = function(owner)
  inCombat("changed a key binding")
  for key, o in pairs(fake.overrides) do if o.owner == owner then fake.overrides[key] = nil end end
  fake.bindingChanges = fake.bindingChanges + 1
end

-- What the game did: spells cast (only ever by a secure button) and interactions (INTERACTTARGET).
fake.casts, fake.interacts = {}, {}
fake.cvars = { ActionButtonUseKeyDown = "1", softTargetInteract = "1", SoftTargetInteractRange = "10", SoftTargetInteractArc = "0",
               Sound_EnableAllSound = "1", Sound_MasterVolume = "0.8", Sound_EnableSFX = "1", Sound_SFXVolume = "0.5",
               Sound_MusicVolume = "0.4", Sound_AmbienceVolume = "0.6" }
-- A click on a secure action button, as SecureActionButton_OnClick does it (SecureTemplates.lua):
-- the button only gets the clicks it's registered for, and acts on the press or the release as
-- its useOnKeyDown says (the ActionButtonUseKeyDown setting when it doesn't say).
local function click(button, mouse, down)
  local wanted = false
  for _, c in ipairs(button.clicks or {}) do
    if c == (down and "AnyDown" or "AnyUp") or c == mouse .. (down and "Down" or "Up") then wanted = true end
  end
  if not wanted then return end
  local onPress = button:GetAttribute("useOnKeyDown")
  if onPress == nil then onPress = fake.cvars.ActionButtonUseKeyDown == "1" end
  local spell = button:GetAttribute("spell")
  if down == onPress and button:GetAttribute("type") == "spell" and spell then
    -- (a number is a spell ID; a name is the first spellbook entry with that name, as the game does)
    local id = tonumber(spell)
    if not id then
      for slot = 1, 100 do
        local entry = fake.book[slot]
        if entry and entry.name == spell then id = entry.spellID; break end
      end
    end
    if id and fake.known[id] then
      table.insert(fake.casts, id)
      if fake.opensWindow[id] then fake.windows = fake.windows + 1 end
    end
  end
  if button.scripts.PostClick then button.scripts.PostClick(button, mouse, down) end
end
-- A key press or release going to its binding: an override first.
function fake.press(key, down)
  local command = (fake.overrides[key] or {}).command or fake.bindings[key]
  local name, mouse = (command or ""):match("^CLICK ([^:]+):(.+)$")
  if name then
    click(_G[name], mouse, down)
  elseif command == "INTERACTTARGET" and down then -- (Bindings_Camelot.xml: runs on the press)
    table.insert(fake.interacts, key)
  end
end
function fake.key(key)
  fake.press(key, true)
  fake.press(key, false)
end
-- The character: Fishing learned (its professions, as GetProfessions gives them: in Forever's
-- professions book, Blizzard_ProfessionsBook/Camelot, prof1, prof2, first aid, fishing, cooking).
fake.professions = { [1] = { "Tailoring", 1, 300, 300, 2, 0, 197 }, [4] = { "Fishing", 1, 150, 150, 2, 10, 356 } }
GetProfessions = function() return 1, nil, nil, fake.professions[4] and 4 or nil, nil end
GetProfessionInfo = function(i) return unpack(fake.professions[i]) end
-- Each rank of Fishing is two spells called "Fishing": Apprentice 7620 casts (a 30
-- second channel that throws the bobber, effect 50 on skill 356); 1240948, learned with it, opens the
-- profession window (effect 47, trade skill). The window one comes first in the spellbook, so
-- casting "Fishing" by name opens the window (what Alex saw); the button must cast 7620.
fake.opensWindow = { [1240948] = true, [1240959] = true, [1240970] = true, [1240983] = true }
fake.book = { [11] = { spellID = 1240948, actionID = 1240948, name = "Fishing", isPassive = false, itemType = 1 },
              [12] = { spellID = 7620, actionID = 7620, name = "Fishing", isPassive = false, itemType = 1 } }
fake.known = { [1240948] = true, [7620] = true }
fake.windows = 0
Enum.SpellBookSpellBank = { Player = 0, Pet = 1 }
Enum.SpellBookItemType = { None = 0, Spell = 1, FutureSpell = 2, PetAction = 3, Flyout = 4 }
C_SpellBook = {
  GetSpellBookItemInfo = function(slot, bank) if bank == 0 then return fake.book[slot] end end,
  IsSpellKnown = function(id, bank) assert(bank == nil or bank == 0); return fake.known[id] == true end,
}
C_TradeSkillUI = { CanTradeSkillShowCraftingUI = function(id) return fake.opensWindow[id] == true end }
-- (learning a rank: the spellbook gets it, and the game says so)
function fake.learn(id, event)
  fake.known[id] = true
  fake.book[12] = { spellID = id, actionID = id, name = "Fishing", isPassive = false, itemType = 1 }
  fake.fire(event or "LEARNED_SPELL_IN_SKILL_LINE", id, 5)
end
local spellName = C_Spell.GetSpellName
C_Spell.GetSpellName = function(id)
  if id == 7620 or id == 7731 or id == 7732 or id == 18248 or fake.opensWindow[id] then return "Fishing" end
  return spellName(id)
end
-- Channelled spells (Fishing's bobber), as UnitChannelInfo and the channel events tell them.
fake.channel = nil
UnitChannelInfo = function(unit) if unit == "player" and fake.channel then return "Fishing", "Fishing", 1, 0, 0, true, nil, fake.channel end end
function fake.startFishing(id) fake.channel = id or 7620; fake.fire("UNIT_SPELLCAST_CHANNEL_START", "player", "Cast-1", fake.channel) end
function fake.stopFishing() local id = fake.channel or 7620; fake.channel = nil; fake.fire("UNIT_SPELLCAST_CHANNEL_STOP", "player", "Cast-1", id) end
-- Game settings (CVars): fake.caps says what the game keeps at most.
fake.caps = {}
GetCVar = function(name) return fake.cvars[name] end
fake.cvarChanges = 0
SetCVar = function(name, value)
  inCombat("changed a game setting")
  if fake.cvars[name] == nil then error("no such setting " .. name) end
  fake.cvarChanges = fake.cvarChanges + 1
  local v = tonumber(value)
  fake.cvars[name] = (fake.caps[name] and v > fake.caps[name]) and tostring(fake.caps[name]) or tostring(value)
  return true
end
-- Nothing may ever cast, use or interact but the game's own secure buttons and bindings.
local function never() error("Gargoyle Fishing must never act by itself") end
CastSpellByName, CastSpellByID, UseAction, RunMacroText, InteractUnit = never, never, never, never, never
C_PlayerInteractionManager = { InteractUnit = never }
"""


def fishing_game(before="", **kwargs):
    return Game(fishing=True, before=FISHING_GAME + "\n" + before, **kwargs)


def casts(game):
    return list(game.fake.casts.values())


def overrides(game):
    return {k: o.command for k, o in game.fake.overrides.items()}


def test_nothing_casts_from_timers_or_events():
    game = fishing_game()
    fake = game.fake
    for event in ("PLAYER_REGEN_DISABLED", "PLAYER_REGEN_ENABLED", "SKILL_LINES_CHANGED", "SPELLS_CHANGED",
                  "LEARNED_SPELL_IN_SKILL_LINE", "UNIT_SPELLCAST_CHANNEL_START", "UNIT_SPELLCAST_CHANNEL_STOP"):
        fake.fire(event, "player", "Cast-1", 7620)
    fake.startFishing()
    fake.stopFishing()
    fake.runTimers()
    assert casts(game) == [] and list(fake.interacts.values()) == [] and overrides(game) == {}
    assert len(fake.timers) == 0  # (no timers at all)
    assert not any(w.scripts.OnUpdate for w in fake.widgets.values())  # (nor anything run every frame)
    source = (FOLDER / "Fishing.lua").read_text(encoding="utf-8")
    assert not re.search(r"C_Timer|OnUpdate|CastSpell|RunMacro|UseAction|InteractUnit|:Click\(", source)
    # (and the mouse is the game's: no double right-click, nothing bound to a mouse button)
    assert not re.search(r"GLOBAL_MOUSE|BUTTON\d|SetOverrideBindingClick|MouseButton", source)
    assert len([w for w in fake.widgets.values() if w.attrs]) == 1 and game.lua.globals().GargoyleFishingButton.attrs  # (one secure button)


def test_the_cast_fishing_key():
    game = fishing_game()
    fake = game.fake
    fake.bindings.F = "CLICK GargoyleFishingButton:LeftButton"  # (bound in Key Bindings > Gargoyle)
    fake.key("F")
    assert casts(game) == [7620] and fake.windows == 0  # (once: on the press, not again on the release)
    button = game.lua.globals().GargoyleFishingButton
    assert list(button.clicks.values()) == ["AnyDown"] and button.GetAttribute(button, "useOnKeyDown") is True
    # (without a pole it's the game that says no; the key only ever casts Fishing)
    xml = (FOLDER / "Bindings.xml").read_text(encoding="utf-8")
    assert 'name="CLICK GargoyleFishingButton:LeftButton"' in xml and 'category="BINDING_HEADER_GARGOYLE"' in xml
    g = game.lua.globals()
    assert g["BINDING_NAME_CLICK GargoyleFishingButton:LeftButton"] == "Cast Fishing"
    assert g.BINDING_HEADER_GARGOYLE == "Gargoyle"


def test_the_key_casts_fishing_not_the_profession_window():
    """Forever's two "Fishing" spells: by name the game takes the first spellbook entry, the one that
    opens the profession window; the button casts the cast, by its spell ID."""
    game = fishing_game()
    fake = game.fake
    fake.bindings.F = "CLICK GargoyleFishingButton:LeftButton"
    button = game.lua.globals().GargoyleFishingButton
    assert button.GetAttribute(button, "spell") == 7620
    # (the stand-in plays the bug as Alex saw it: "Fishing" by name opens the window)
    button.SetAttribute(button, "spell", "Fishing")
    fake.key("F")
    assert casts(game) == [1240948] and fake.windows == 1
    fake.fire("SPELLS_CHANGED")  # (and the addon puts its own back)
    assert button.GetAttribute(button, "spell") == 7620


def test_the_best_rank_and_a_new_one():
    game = fishing_game()
    fake = game.fake
    fake.bindings.F = "CLICK GargoyleFishingButton:LeftButton"
    button = game.lua.globals().GargoyleFishingButton
    fake.learn(7731)  # (Journeyman)
    assert button.GetAttribute(button, "spell") == 7731
    fake.key("F")
    assert casts(game) == [7731]
    # Learned in combat: the key changes once the fight is over.
    fake.fire("PLAYER_REGEN_DISABLED")
    fake.combat = True
    fake.learn(7732, "SPELLS_CHANGED")
    fake.fire("SKILL_LINES_CHANGED")
    assert button.GetAttribute(button, "spell") == 7731
    fake.combat = False
    fake.fire("PLAYER_REGEN_ENABLED")
    assert button.GetAttribute(button, "spell") == 7732
    fake.known[18248] = True  # (Artisan, known before Expert is forgotten: the best one wins)
    fake.fire("SKILL_LINES_CHANGED")
    assert button.GetAttribute(button, "spell") == 18248
    # The one-key mode knows a higher rank's channel as Fishing too.
    fake.startFishing(18248)
    assert overrides(game) == {"F": "INTERACTTARGET"}
    fake.stopFishing()
    assert overrides(game) == {}


def test_no_known_rank_the_spellbook_entry_that_casts():
    """Without a way to ask what's known, or with a rank this addon doesn't list: the Fishing
    profession's spellbook entry that isn't passive and doesn't open the window."""
    game = fishing_game(before="C_SpellBook.IsSpellKnown = nil")
    button = game.lua.globals().GargoyleFishingButton
    assert button.GetAttribute(button, "spell") == 7620
    game = fishing_game(before="""
fake.book[12] = { spellID = 88888, name = "Fishing Poles", isPassive = true, itemType = 1 }
fake.book[13] = { spellID = 99999, name = "Fishing", isPassive = false, itemType = 1 }
fake.professions[4][5] = 3
fake.known = { [1240948] = true, [99999] = true, [88888] = true }""")
    button = game.lua.globals().GargoyleFishingButton
    assert button.GetAttribute(button, "spell") == 99999
    # No Fishing at all: the key does nothing.
    game = fishing_game(before="fake.professions[4] = nil; fake.known = {}; fake.book = {}")
    button = game.lua.globals().GargoyleFishingButton
    assert button.GetAttribute(button, "spell") is None


REACH_BEFORE = {"softTargetInteract": "1", "SoftTargetInteractRange": "10", "SoftTargetInteractArc": "0"}
REACH_FISHING = {"softTargetInteract": "3", "SoftTargetInteractRange": "30", "SoftTargetInteractArc": "2"}


def reach(game):
    return {name: game.fake.cvars[name] for name in REACH_BEFORE}


def test_one_key_mode_reels_in_with_the_same_key():
    game = fishing_game(saved="GargoyleDB = { fishing = { louder = false } }")  # (this one is about the reach)
    fake = game.fake
    fake.bindings.F = "CLICK GargoyleFishingButton:LeftButton"
    game.slash("options")
    box = next(f.point[2] for f in fake.widgets.values() if f.kind == "FontString" and f.text.startswith("One key")
               and f.point and f.point[2] and f.point[2].kind == "CheckButton")
    assert box.GetChecked(box)  # (on to start with)
    label = ("One key: the Cast Fishing key also reels in (the game's Interact key, with its reach set to 30 "
             "yards while you fish)")
    assert label in game.texts()
    fake.key("F")
    fake.startFishing()
    assert overrides(game) == {"F": "INTERACTTARGET"}
    assert reach(game) == REACH_FISHING and dict(game.db.fishing.reach) == REACH_BEFORE
    fake.press("F", True)  # (a bite: the player presses the key to reel in)
    assert list(fake.interacts.values()) == ["F"]
    fake.stopFishing()  # (the loot: fishing ends, and so do the override and the reach)
    fake.press("F", False)  # (the release doesn't cast again)
    assert overrides(game) == {} and casts(game) == [7620]
    assert reach(game) == REACH_BEFORE and game.db.fishing.reach is None
    # Combat clears it; and it's never set in combat
    fake.key("F")
    fake.startFishing()
    fake.fire("PLAYER_REGEN_DISABLED")
    assert overrides(game) == {} and reach(game) == REACH_BEFORE
    fake.combat = True
    fake.startFishing()
    fake.stopFishing()
    assert overrides(game) == {} and reach(game) == REACH_BEFORE
    # Turned off: the key only casts, and the game's settings are left alone
    fake.combat = False
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert game.db.fishing.oneKey is False
    changes = fake.cvarChanges
    fake.startFishing()
    fake.press("F", True)
    assert overrides(game) == {} and list(fake.interacts.values()) == ["F"] and fake.cvarChanges == changes
    fake.stopFishing()
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    # Turned off while fishing: put back straight away
    fake.startFishing()
    assert reach(game) == REACH_FISHING
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert overrides(game) == {} and reach(game) == REACH_BEFORE and game.db.fishing.reach is None
    fake.stopFishing()
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    # No key bound: it says so once
    fake.bindings.F = None
    fake.startFishing()
    fake.stopFishing()
    fake.startFishing()
    assert game.printed().count("one-key fishing needs a key") == 1


def test_the_reach_is_put_back():
    game = fishing_game(saved="GargoyleDB = { fishing = { louder = false } }")
    fake = game.fake
    fake.bindings.F = "CLICK GargoyleFishingButton:LeftButton"
    # Soft targeting already on for anything (3) stays so; it's only ever raised.
    fake.cvars.softTargetInteract = "3"
    fake.startFishing()
    assert reach(game) == REACH_FISHING
    fake.stopFishing()
    assert fake.cvars.softTargetInteract == "3" and fake.cvars.SoftTargetInteractRange == "10"
    fake.cvars.softTargetInteract = "1"
    # Fishing stops in combat (a mob hits you): the settings go back as soon as the fight ends.
    fake.startFishing()
    fake.combat = True  # (the game locked things without PLAYER_REGEN_DISABLED reaching us first)
    fake.stopFishing()
    assert reach(game) == REACH_FISHING
    fake.combat = False
    fake.fire("PLAYER_REGEN_ENABLED")
    assert reach(game) == REACH_BEFORE and overrides(game) == {}
    # A second channel start before a stop keeps the game's own values to put back.
    fake.startFishing()
    fake.startFishing()
    fake.stopFishing()
    assert reach(game) == REACH_BEFORE
    # Logging out mid-cast: put back, and kept in GargoyleDB until the next login.
    fake.startFishing()
    fake.fire("PLAYER_LOGOUT")
    assert reach(game) == REACH_BEFORE and dict(game.db.fishing.reach) == REACH_BEFORE
    # Gargoyle Fishing turned off mid-cast: put back too.
    fake.cvars.SoftTargetInteractRange = "30"
    game.slash("options")
    switch(game, False)
    assert reach(game)["SoftTargetInteractRange"] == "10" and game.db.fishing.reach is None


def test_a_crash_mid_cast_is_put_right_at_the_next_login():
    game = fishing_game(saved="""GargoyleDB = { fishing = { reach = { softTargetInteract = "1",
        SoftTargetInteractRange = "10", SoftTargetInteractArc = "0" } } }""",
                        before='fake.cvars.softTargetInteract = "3"; fake.cvars.SoftTargetInteractRange = "30"; '
                               'fake.cvars.SoftTargetInteractArc = "2"')
    assert reach(game) == REACH_BEFORE and game.db.fishing.reach is None

SOUND_BEFORE = {"Sound_EnableSFX": "1", "Sound_SFXVolume": "0.5", "Sound_MusicVolume": "0.4", "Sound_AmbienceVolume": "0.6"}
SOUND_FISHING = {"Sound_EnableSFX": "1", "Sound_SFXVolume": "1", "Sound_MusicVolume": "0", "Sound_AmbienceVolume": "0"}
LOUDER_LABEL = ("Louder splash: while you fish, sound effects go up to full and music and ambient sounds go down, "
                "so you can hear the bite")


def sound(game):
    return {name: game.fake.cvars[name] for name in SOUND_BEFORE}


def louder_box(game):
    game.slash("options")
    return next(f.point[2] for f in game.fake.widgets.values() if f.kind == "FontString" and f.text.startswith("Louder splash")
                and f.point and f.point[2] and f.point[2].kind == "CheckButton")


def test_louder_splash_sets_the_sound_and_puts_it_back():
    game = fishing_game()
    fake = game.fake
    box = louder_box(game)
    assert box.GetChecked(box) and LOUDER_LABEL in game.texts()  # (on to start with)
    fake.startFishing()
    assert sound(game) == SOUND_FISHING and dict(game.db.fishing.sound) == SOUND_BEFORE
    # the master volume and "all sound" are the player's own
    assert fake.cvars.Sound_MasterVolume == "0.8" and fake.cvars.Sound_EnableAllSound == "1"
    fake.stopFishing()
    assert sound(game) == SOUND_BEFORE and game.db.fishing.sound is None
    # sound effects switched off are switched on while you fish, then off again
    fake.cvars.Sound_EnableSFX = "0"
    fake.startFishing()
    assert fake.cvars.Sound_EnableSFX == "1"
    fake.stopFishing()
    assert fake.cvars.Sound_EnableSFX == "0"
    # everything muted (all sound off) stays the player's choice
    fake.cvars.Sound_EnableSFX, fake.cvars.Sound_EnableAllSound = "1", "0"
    fake.startFishing()
    fake.stopFishing()
    assert fake.cvars.Sound_EnableAllSound == "0"


def test_a_recast_keeps_the_original_sound_and_sets_nothing_twice():
    game = fishing_game(saved="GargoyleDB = { fishing = { oneKey = false } }")  # (only the sound changes here)
    fake = game.fake
    fake.startFishing()
    changes = fake.cvarChanges
    assert changes == 3  # (effects were on already: volumes only)
    fake.startFishing()  # (a new cast before the stop: the settings are the raised ones now)
    fake.startFishing()
    assert dict(game.db.fishing.sound) == SOUND_BEFORE and fake.cvarChanges == changes  # (already set: not set again)
    fake.stopFishing()
    assert sound(game) == SOUND_BEFORE
    # (the next cast right after: saved again from the game's own values, which are back)
    fake.startFishing()
    assert dict(game.db.fishing.sound) == SOUND_BEFORE and sound(game) == SOUND_FISHING
    fake.stopFishing()
    # a volume already where it should be is left alone
    fake.cvars.Sound_MusicVolume = "0"
    before = fake.cvarChanges
    fake.startFishing()
    assert fake.cvarChanges == before + 2
    fake.stopFishing()
    assert fake.cvars.Sound_MusicVolume == "0"


def test_louder_splash_and_combat():
    game = fishing_game()
    fake = game.fake
    # Combat starting while you fish: put back first, as the fight starts
    fake.startFishing()
    fake.fire("PLAYER_REGEN_DISABLED")
    assert sound(game) == SOUND_BEFORE and game.db.fishing.sound is None
    # Never set in combat
    fake.combat = True
    fake.startFishing()
    fake.stopFishing()
    assert sound(game) == SOUND_BEFORE and game.db.fishing.sound is None
    fake.combat = False
    fake.fire("PLAYER_REGEN_ENABLED")
    # The game locked things before we heard of the fight: put back once it is over
    fake.startFishing()
    fake.combat = True
    fake.stopFishing()
    assert sound(game) == SOUND_FISHING
    fake.combat = False
    fake.fire("PLAYER_REGEN_ENABLED")
    assert sound(game) == SOUND_BEFORE and game.db.fishing.sound is None


def test_louder_splash_at_logout_and_after_a_crash():
    game = fishing_game()
    fake = game.fake
    fake.startFishing()
    fake.fire("PLAYER_LOGOUT")  # (put back, and kept in GargoyleDB until the next login)
    assert sound(game) == SOUND_BEFORE and dict(game.db.fishing.sound) == SOUND_BEFORE
    # A crash or /reload mid-cast: the next login puts the game's own back
    game = fishing_game(saved="""GargoyleDB = { fishing = { sound = { Sound_EnableSFX = "1", Sound_SFXVolume = "0.5",
        Sound_MusicVolume = "0.4", Sound_AmbienceVolume = "0.6" } } }""",
                        before='fake.cvars.Sound_SFXVolume = "1"; fake.cvars.Sound_MusicVolume = "0"; '
                               'fake.cvars.Sound_AmbienceVolume = "0"')
    assert sound(game) == SOUND_BEFORE and game.db.fishing.sound is None


def test_louder_splash_turned_off():
    game = fishing_game()
    fake = game.fake
    box = louder_box(game)
    # Turned off while fishing: put back straight away
    fake.startFishing()
    assert sound(game) == SOUND_FISHING
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert game.db.fishing.louder is False and sound(game) == SOUND_BEFORE and game.db.fishing.sound is None
    fake.stopFishing()
    # Off: fishing leaves the sound alone
    changes = fake.cvarChanges
    fake.startFishing()
    fake.stopFishing()
    sound_changes = [n for n in SOUND_BEFORE if fake.cvars[n] != SOUND_BEFORE[n]]
    assert sound(game) == SOUND_BEFORE and sound_changes == []
    assert fake.cvarChanges - changes == 6  # (only the reach: set, then put back)
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    fake.startFishing()
    assert sound(game) == SOUND_FISHING
    # The whole of Gargoyle Fishing turned off mid-cast: put back too
    game.slash("options")
    switch(game, False)
    assert sound(game) == SOUND_BEFORE and game.db.fishing.sound is None
    # The reach and the sound are independent: one key off leaves the sound raised while fishing
    switch(game, True)
    fake.stopFishing()
    game.db.fishing.oneKey = False
    fake.startFishing()
    assert sound(game) == SOUND_FISHING and fake.cvars.SoftTargetInteractRange == "10"
    fake.stopFishing()


def test_louder_splash_skips_settings_this_game_does_not_have():
    game = fishing_game(before="fake.cvars.Sound_AmbienceVolume = nil; fake.cvars.Sound_EnableSFX = nil")
    fake = game.fake
    fake.startFishing()  # (no error: SetCVar would complain about an unknown setting)
    assert fake.cvars.Sound_SFXVolume == "1" and fake.cvars.Sound_MusicVolume == "0"
    assert fake.cvars.Sound_AmbienceVolume is None and fake.cvars.Sound_EnableSFX is None
    assert dict(game.db.fishing.sound) == {"Sound_SFXVolume": "0.5", "Sound_MusicVolume": "0.4"}
    fake.stopFishing()
    assert fake.cvars.Sound_SFXVolume == "0.5" and fake.cvars.Sound_MusicVolume == "0.4"
    # none of them at all
    game = fishing_game(before="for _, n in ipairs({ 'Sound_EnableSFX', 'Sound_SFXVolume', 'Sound_MusicVolume', "
                               "'Sound_AmbienceVolume' }) do fake.cvars[n] = nil end")
    game.fake.startFishing()
    game.fake.stopFishing()
    assert game.db.fishing.sound is None or dict(game.db.fishing.sound) == {}


def switch(game, on):
    box = game.ns.optionBoxes.fishing
    box.SetChecked(box, on)
    box.scripts.OnClick(box)


def test_turned_off_in_gargoyles_options():
    """Off, the Cast Fishing key does nothing and one-key mode stops; on again, both are back."""
    game = fishing_game()
    fake = game.fake
    fake.bindings.F = "CLICK GargoyleFishingButton:LeftButton"
    game.db.fishing.oneKey = True
    game.slash("options")
    assert ("Cast Fishing with one key (set it in Key Bindings > Gargoyle), and press it again to reel in (or "
            "right-click the bobber).") in game.texts()
    box = game.ns.optionBoxes.fishing
    assert box.GetChecked(box)  # (on to start with)
    fake.startFishing()
    assert overrides(game) == {"F": "INTERACTTARGET"}
    switch(game, False)  # (while fishing: one key stops straight away)
    assert game.db.modules.fishing is False and overrides(game) == {}
    fake.stopFishing()
    fake.key("F")
    fake.startFishing()
    assert casts(game) == [] and overrides(game) == {}
    fake.stopFishing()
    switch(game, True)
    fake.key("F")
    fake.startFishing()
    assert casts(game) == [7620] and overrides(game) == {"F": "INTERACTTARGET"}
    fake.stopFishing()
    # Turned off in combat: the key's spell goes as soon as the fight ends.
    fake.fire("PLAYER_REGEN_DISABLED")
    fake.combat = True
    switch(game, False)
    fake.combat = False
    fake.fire("PLAYER_REGEN_ENABLED")
    fake.casts = game.lua.table()
    fake.key("F")
    assert casts(game) == []
    # Gargoyle without Gargoyle Fishing says how to get it
    other = Game()
    other.slash("options")
    assert "Fishing isn't installed: tick it in the Gargoyle app's Settings" in other.texts()


def test_fishing_test_shows_and_tries_the_interact_range_settings():
    game = fishing_game()
    fake = game.fake
    fake.caps.SoftTargetInteractRange = 15  # (the game keeps at most 15)
    game.slash("fishing test")
    said = game.printed()
    assert "softTargetInteract is 1" in said and "SoftTargetInteractRange is 10" in said
    assert "SoftTargetInteractArc is 0" in said and "SoftTargetInteractRangeIsHard is not in this game" in said
    assert "set SoftTargetInteractRange to 30: the game kept 15" in said
    assert "set SoftTargetInteractArc to 2: the game kept 2" in said
    assert fake.cvars.SoftTargetInteractArc == "2"
    game.slash("fishing test")  # (a second test keeps the game's own values to put back)
    game.slash("fishing restore")
    assert fake.cvars.SoftTargetInteractRange == "10" and fake.cvars.SoftTargetInteractArc == "0"
    assert "nothing to put back" not in game.printed()
    game.slash("fishing restore")
    assert "nothing to put back" in game.printed()
    # Not in combat; the rest of /gargoyle is the core's
    fake.combat = True
    fake.printed = game.lua.table()
    game.slash("fishing test")
    assert "not in combat" in game.printed() and fake.cvars.SoftTargetInteractArc == "0"
    fake.combat = False
    game.slash("help")
    assert "/gargoyle options" in game.printed() and "/gargoyle fishing test" in game.printed()


def test_the_addon_files_are_as_the_game_and_the_app_need():
    toc = (FOLDER / "Gargoyle_Fishing.toc").read_text(encoding="utf-8")
    assert re.search(r"^## Version: 1\.0\.0$", toc, re.M) and re.search(r"^## Dependencies: Gargoyle$", toc, re.M)
    files = [line.strip() for line in toc.splitlines() if line.strip() and not line.startswith("#")]
    assert files == ["Fishing.lua"] and all((FOLDER / f).is_file() for f in files)
    assert (FOLDER / "Media" / "Badge.tga").is_file() and (FOLDER / "Bindings.xml").is_file()
    # The core knows it (Options say how to get it when it isn't there).
    core = (PROJECT / "addon" / "Gargoyle" / "Core.lua").read_text(encoding="utf-8")
    assert '{ key = "fishing", title = "Fishing", addon = "Gargoyle_Fishing" }' in core
    assert Path(PROJECT / "addon" / "Gargoyle_Fishing").is_dir()
