"""The Gargoyle addon (addon/Gargoyle), run in Lua 5.1 (lupa, like the game's Lua) against a
small stand-in for the game's addon API. The stand-in only knows the widget methods listed
below, so a typo or a method we forgot fails here."""
import sys
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
from lupa import lua51  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
ADDON = PROJECT / "addon" / "Gargoyle"
sys.path.insert(0, str(PROJECT / "helper"))
from sync_file import sync_lua  # noqa: E402

NOW = 1_800_000_000

FAKE_GAME = r"""
fake = { widgets = {}, events = {}, printed = {}, timers = {}, now = %d, player = "Jainamage" }
local methods = {}
local NOOP = { "SetSize", "SetWidth", "SetHeight", "ClearAllPoints", "SetAllPoints", "SetFrameStrata",
  "SetClampedToScreen", "SetMovable", "EnableMouse", "RegisterForDrag", "StartMoving", "StopMovingOrSizing",
  "LockHighlight", "UnlockHighlight", "SetJustifyH", "SetJustifyV", "SetHighlightTexture", "SetColorTexture",
  "EnableMouseWheel", "SetAutoFocus", "SetMaxLetters", "SetTextColor", "SetWordWrap", "SetToplevel", "SetTitle",
  "SetPortraitToAsset", "SetTexture", "SetTexCoord", "SetBlendMode", "SetVertexColor", "SetFrameLevel",
  "RegisterForClicks", "SetMaxLines", "AddMaskTexture", "SetLooping", "SetFromAlpha", "SetToAlpha", "SetDuration",
  "SetSmoothing" }
for _, name in ipairs(NOOP) do methods[name] = function() end end
function methods:SetPoint(...) self.point = { ... } end
function methods:GetWidth() return 140 end
function methods:GetHeight() return 140 end
function methods:GetCenter() return 500, 400 end
function methods:GetEffectiveScale() return 1 end
function methods:CreateMaskTexture() return fake.new("MaskTexture", nil, self) end
function methods:CreateAnimationGroup() return fake.new("AnimationGroup", nil, self) end
function methods:CreateAnimation() return fake.new("Animation", nil, self) end
function methods:Play() self.playing = true end
function methods:Stop() self.playing = false end
function methods:GetStringHeight() return 12 end
-- Dropdowns (the game's DropdownButton): a menu of radio choices, made by a function. The
-- text shown is the chosen one's.
local function showChoice(w)
  w.text = w.defaultText or ""
  for _, r in ipairs(w.radios) do
    if r.isSelected(r.data) then w.text = r.text end
  end
end
function methods:SetDefaultText(text) self.defaultText = text end
function methods:SetupMenu(generator) self.generator = generator; self:GenerateMenu() end
function methods:GenerateMenu()
  self.radios = {}
  local root = { CreateRadio = function(_, text, isSelected, setSelected, data)
    table.insert(self.radios, { text = text, isSelected = isSelected, setSelected = setSelected, data = data })
  end }
  self.generator(self, root)
  showChoice(self)
end
function fake.choose(text) -- open the dropdown that offers it, and pick it
  for _, w in ipairs(fake.widgets) do
    if w.kind == "DropdownButton" and w:IsVisible() and w.enabled then
      w:GenerateMenu()
      for _, r in ipairs(w.radios) do
        if r.text:find(text, 1, true) then
          r.setSelected(r.data)
          showChoice(w)
          return true
        end
      end
    end
  end
end
function methods:SetScript(name, fn) self.scripts[name] = fn end
function methods:GetScript(name) return self.scripts[name] end
function methods:Show() self.shown = true end
function methods:Hide() self.shown = false end
function methods:SetShown(v) self.shown = not not v end
function methods:IsShown() return self.shown end
function methods:IsVisible()
  local w = self
  while w do
    if not w.shown then return false end
    w = w.parent
  end
  return true
end
function methods:SetText(t) self.text = t end
function methods:GetText() return self.text end
function methods:SetChecked(v) self.checked = not not v end
function methods:GetChecked() return self.checked end
function methods:Enable() self.enabled = true end
function methods:Disable() self.enabled = false end
function methods:SetEnabled(v) self.enabled = not not v end
function methods:IsEnabled() return self.enabled end
function methods:HasFocus() return self.focus == true end
function methods:SetFocus() self.focus = true end
function methods:ClearFocus() self.focus = false end
function methods:GetParent() return self.parent end
function methods:Click()
  if self.enabled and self.scripts.OnClick then self.scripts.OnClick(self, "LeftButton") end
end
function methods:CreateFontString() return fake.new("FontString", nil, self) end
function methods:CreateTexture() return fake.new("Texture", nil, self) end
function methods:RegisterEvent(event)
  if fake.unknownEvents and fake.unknownEvents[event] then error("unknown event " .. event) end
  fake.events[event] = fake.events[event] or {}
  table.insert(fake.events[event], self)
end
function methods:UnregisterAllEvents()
  for _, frames in pairs(fake.events) do
    for i = #frames, 1, -1 do
      if frames[i] == self then table.remove(frames, i) end
    end
  end
end
local Widget = { __index = methods }

function fake.new(kind, name, parent)
  local w = setmetatable({ kind = kind, parent = parent, scripts = {}, shown = true, enabled = true, text = "" }, Widget)
  table.insert(fake.widgets, w)
  if name then _G[name] = w end
  return w
end
function fake.fire(event, ...)
  for _, frame in ipairs(fake.events[event] or {}) do frame.scripts.OnEvent(frame, event, ...) end
end
function fake.button(text)
  for _, w in ipairs(fake.widgets) do
    if w.kind == "Button" and w.text == text and w:IsVisible() then return w end
  end
end
function fake.texts()
  local out = {}
  for _, w in ipairs(fake.widgets) do
    if w.kind == "FontString" and w:IsVisible() and w.text ~= "" then table.insert(out, w.text) end
  end
  return table.concat(out, "\n")
end

CreateFrame = function(kind, name, parent) return fake.new(kind, name, parent) end
UIParent = fake.new("Frame")
Minimap = fake.new("Minimap")
fake.cursor = { 0, 0 }
GetCursorPosition = function() return fake.cursor[1], fake.cursor[2] end
GameTooltip = fake.new("GameTooltip")
function GameTooltip:SetOwner(owner) self.owner, self.lines = owner, {} end
function GameTooltip:SetText(text) self.lines = { text } end
function GameTooltip:AddLine(text) table.insert(self.lines, text) end
ReloadUI = function() fake.reloaded = true end
SOUNDKIT = { IG_CHARACTER_INFO_TAB = 841, UI_BNET_TOAST = 18019 }
PlaySound = function(sound) fake.sound = sound end
PanelTemplates_TabResize = function() end
PixelUtil = { SetRoundLayoutToNearestPixelRecursively = function(frame, on) frame.sharp = on end }
function methods:SetRoundLayoutToNearestPixel() end
PanelTemplates_SelectTab = function(tab) tab.selected = true; tab:Disable() end
PanelTemplates_DeselectTab = function(tab) tab.selected = false; tab:Enable() end
UISpecialFrames = {}
tinsert = table.insert
time = function() return fake.now end
date = os.date
print = function(...) table.insert(fake.printed, table.concat({ ... }, " ")) end
strtrim = function(s) return (s:gsub("^%%s+", ""):gsub("%%s+$", "")) end
SlashCmdList = {}
UnitName = function() return fake.player, fake.surname end
RAID_CLASS_COLORS = { MAGE = { colorStr = "ff3fc7eb" } }
LOCALIZED_CLASS_NAMES_MALE = { MAGE = "Mage" }

-- The character being played: a level 60 Human Mage.
fake.char = {
  guid = "Player-1-00ABCDEF", level = 60, unspent = 0,
  gear = { [1] = "|cffa335ee|Hitem:240056::::::::60:::::|h[Fireleaf Circlet]|h|r",
           [9] = "|cffa335ee|Hitem:240052:723:::::::60:::::|h[Fireleaf Bindings]|h|r",
           [16] = "|cffa335ee|Hitem:234571:723:::::::60:::::|h[Grand Marshal's Stave]|h|r" },
  ids = { [1] = 240056, [9] = 240052, [16] = 234571 },
  -- per tree: name, row, column, rank, most ranks, spell
  talents = { { { "Arcane Subtlety", 2, 1, 2, 2, 11210 }, { "Arcane Focus", 1, 2, 0, 5, 11222 } },
              { { "Improved Fireball", 1, 3, 0, 5, 11069 } },
              { { "Improved Frostbolt", 1, 2, 5, 5, 11070 } } },
  -- name, is a heading, unfolded, skill
  skills = { { "Professions", true, true, 0 }, { "Tailoring", false, true, 300 }, { "Enchanting", false, true, 280 },
             { "Weapon Skills", true, true, 0 }, { "Staves", false, true, 300 } },
}
UnitGUID = function() return fake.char.guid end
UnitClass = function() return "Mage", "MAGE", 8 end
UnitRace = function() return "Human", "Human", 1 end
UnitLevel = function() return fake.char.level end
UnitFactionGroup = function() return "Alliance", "Alliance" end
UnitCharacterPoints = function() return fake.char.unspent end
GetInventoryItemLink = function(_, slot) return fake.char.gear[slot] end
GetInventoryItemID = function(_, slot) return fake.char.ids[slot] end
-- Talents as WoW Forever has them: one talent tree (config 77, tree 500) with the class's
-- three trees as groups in it (listed out of order, as nothing promises an order). A
-- talent's node, entry and definition all share one number: tree * 1000 + place.
local function talent(id)
  local tree = fake.char.talents[math.floor(id / 1000)]
  return tree and tree[id - math.floor(id / 1000) * 1000]
end
C_ClassTalents = { GetActiveConfigID = function() return fake.char.configID end }
C_SpecializationInfo = { IsInitialized = function() return fake.char.configID ~= nil end }
C_Traits = {
  GetConfigInfo = function(id) if id == 77 then return { ID = 77, treeIDs = { 500 } } end end,
  GetGroupDisplayInfoByTreeID = function(treeID)
    local groups = {}
    for i = #fake.char.talents, 1, -1 do groups[#groups + 1] = { groupID = 600 + i, treeID = treeID, orderIndex = i } end
    return groups
  end,
  GetTreeNodes = function()
    local ids = {}
    for tree, list in ipairs(fake.char.talents) do
      for place in ipairs(list) do ids[#ids + 1] = tree * 1000 + place end
    end
    return ids
  end,
  GetNodeInfo = function(_, id)
    local t = talent(id)
    return { ID = id, ranksPurchased = t[4], activeRank = t[4], maxRanks = t[5], entryIDs = { id },
             activeEntry = { entryID = id, rank = t[4] }, groupIDs = { 600 + math.floor(id / 1000) } }
  end,
  GetEntryInfo = function(_, id) return { definitionID = id } end,
  GetDefinitionInfo = function(id) return { spellID = talent(id)[6], overrideName = "" } end,
}
C_Spell = {
  GetSpellName = function(spellID)
    for _, tree in ipairs(fake.char.talents) do
      for _, t in ipairs(tree) do
        if t[6] == spellID then return t[1] end
      end
    end
  end,
}
fake.char.configID = 77
-- (and as older clients had them, for test_older_talent_functions)
function fake.olderTalents()
  C_Traits, C_ClassTalents, C_SpecializationInfo = nil, nil, nil
  GetNumTalentTabs = function() return #fake.char.talents end
  GetNumTalents = function(tab) return #fake.char.talents[tab] end
  GetTalentInfo = function(tab, index)
    local t = fake.char.talents[tab][index]
    return t[1], "icon", t[2], t[3], t[4], t[5]
  end
end
GetNumSkillLines = function() return #fake.char.skills end
GetSkillLineInfo = function(i)
  local s = fake.char.skills[i]
  return s[1], s[2], s[3], s[4]
end
InCombatLockdown = function() return fake.combat == true end
C_Timer = { After = function(_, fn) table.insert(fake.timers, fn) end }
function fake.runTimers()
  local due = fake.timers
  fake.timers = {}
  for _, fn in ipairs(due) do fn() end
end
Settings = {
  RegisterCanvasLayoutCategory = function(panel, name) return { name = name, GetID = function() return 7 end } end,
  RegisterAddOnCategory = function(category) fake.category = category end,
  OpenToCategory = function(id) fake.opened = id end,
}
""" % NOW

API = {  # what /api/app/sync answers (see app_api.py)
    "user": "Jaina", "time": NOW - 600,
    "characters": [
        {"id": 11, "name": "Jainamage", "class": "mage", "guild": 5, "role": "healer"},
        {"id": 12, "name": "Jainalt", "class": "mage", "guild": 5, "role": "dps"},
        {"id": 13, "name": "Elsewhere", "class": "mage", "guild": None, "role": None},
    ],
    "guilds": [{"id": 5, "name": "Knights of Forever", "game_name": "Knights EU", "officer": False, "raids": [
        {"id": 2, "title": "Blackwing Lair", "start": NOW + 7 * 86400, "size": 40, "notes": "", "signups": []},
        {"id": 1, "title": "Molten Core", "start": NOW + 86400, "size": 40, "notes": "Bring fire resist",
         "signups": [
             {"name": "Thrallmage", "class": "mage", "role": "tank", "status": "accepted", "note": ""},
             {"name": "Jainamage", "class": "mage", "role": "healer", "status": "tentative", "note": "late",
              "mine": True, "character": 11, "changed": NOW - 3600},
         ]},
        {"id": 3, "title": "Started already", "start": NOW - 60, "size": 20, "notes": "", "signups": []},
    ]}],
}


class Game:
    def __init__(self, sync=None, saved=None, now=NOW):
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FAKE_GAME)
        self.fake = self.lua.globals().fake
        self.fake.now = now
        if sync:
            self.lua.execute(sync)
        if saved:
            self.lua.execute(saved)
        self.ns = self.lua.table()
        run = self.lua.eval('function(src, name, ns) local f = assert(loadstring(src, "@" .. name)); f("Gargoyle", ns) end')
        toc = (ADDON / "Gargoyle.toc").read_text(encoding="utf-8").splitlines()
        for name in (line.strip() for line in toc):
            if name and not name.startswith("#"):
                run((ADDON / name.replace("\\", "/")).read_text(encoding="utf-8"), name, self.ns)
        self.fake.fire("ADDON_LOADED", "Gargoyle")
        self.fake.fire("PLAYER_LOGIN")

    @property
    def db(self):
        return self.lua.globals().GargoyleDB

    def slash(self, text=""):
        self.lua.globals().SlashCmdList.GARGOYLE(text)

    def click(self, text):
        button = self.fake.button(text)
        assert button is not None, f"no button {text!r}"
        button.Click(button)

    def texts(self):
        return self.fake.texts()

    def choose(self, text):
        assert self.fake.choose(text), f"no dropdown offers {text!r}"

    def dropdowns(self):
        return [w.text for w in self.fake.widgets.values() if w.kind == "DropdownButton" and w.IsVisible(w)]

    def printed(self):
        return "\n".join(self.fake.printed.values())

    def outbox(self):
        return [dict(a.items()) for a in self.db.outbox.values()]


def test_window_shows_upcoming_raids_soonest_first():
    game = Game(sync_lua(API, {}))
    game.slash()
    assert game.lua.globals().GargoyleWindow.IsShown(game.lua.globals().GargoyleWindow)
    text = game.texts()
    assert text.index("Molten Core") < text.index("Blackwing Lair") and "Started already" not in text
    assert "Gargoyle account:|r Jaina" in text and "Last sync:|r 10 min ago" in text and "Nothing waiting to sync." in text
    # The first raid is open: notes, the roster with your own signup, and your status.
    assert "Bring fire resist" in text and "1 coming|r/40 · 1 tentative" in text
    assert "|A:UI-LFG-RoleIcon-Tank-Micro-GroupFinder:16:16|a Tanks (1): |cff3fc7ebThrallmage|r" in text
    assert "|A:UI-LFG-PendingMark:16:16|a |cffe0c040Tentative|r as Healer on Jainamage" in text
    assert game.dropdowns() == ["|cff3fc7ebJainamage|r", "|A:UI-LFG-RoleIcon-Healer-Micro-GroupFinder:16:16|a Healer"]


def test_signing_up_in_game_goes_to_the_outbox():
    game = Game(sync_lua(API, {}))
    game.slash()
    game.click("Coming")
    (action,) = game.outbox()
    assert action["raid"] == 1 and action["character"] == 11 and action["status"] == "accepted"
    assert action["role"] == "healer" and action["at"] == NOW and action["title"] == "Molten Core"
    assert "click Reload UI (or log out) to send it" in game.printed()
    text = game.texts()
    assert "|cff40c040Coming|r as Healer on Jainamage  |cffb0b0b0(waiting to sync)|r" in text
    assert "Waiting to sync: 1 signup. Reload or log out to send." in text
    # Another change to the same raid replaces it; switching character and role works.
    game.choose("Jainalt")
    game.choose("Damage")
    assert game.dropdowns() == ["|cff3fc7ebJainalt|r", "|A:UI-LFG-RoleIcon-DPS-Micro-GroupFinder:16:16|a Damage"]
    game.click("Can't come")
    (action,) = game.outbox()
    assert (action["character"], action["role"], action["status"]) == (12, "dps", "declined")


def test_no_roster_character_no_signup():
    api = {**API, "characters": [API["characters"][2]]}
    game = Game(sync_lua(api, {}))
    game.slash()
    assert "Add one of your characters to this guild's roster" in game.texts()
    game.click("Coming")  # (disabled: nothing happens)
    assert game.outbox() == []


def test_answered_signups_leave_the_outbox():
    saved = """GargoyleDB = { modules = {}, outbox = {
      { id = "a", raid = 1, character = 11, status = "accepted", role = "healer", at = %d, title = "Molten Core", start = %d },
      { id = "b", raid = 2, character = 11, status = "accepted", role = "healer", at = %d, title = "Blackwing Lair", start = %d },
      { id = "c", raid = 2, character = 11, status = "declined", role = "healer", at = %d, title = "Blackwing Lair", start = %d },
      { id = "old", raid = 9, character = 11, status = "accepted", role = "dps", at = %d, title = "Gone", start = %d },
    } }""" % (NOW - 50, NOW + 86400, NOW - 40, NOW + 7 * 86400, NOW - 30, NOW + 7 * 86400, NOW - 9000, NOW - 100)
    game = Game(sync_lua(API, {"a": "saved", "b": "stale"}), saved)
    assert [a["id"] for a in game.outbox()] == ["c"]  # still waiting; the started raid's one dropped
    assert "your signup for Blackwing Lair wasn't saved: it was changed on the website" in game.printed()
    assert "Molten Core wasn't saved" not in game.printed()


def test_without_sync_data_it_explains_and_doesnt_break():
    game = Game()
    game.slash()
    assert "No raid data yet. The Gargoyle app brings it in" in game.texts()
    assert "No data from the Gargoyle app yet" in game.texts()
    for junk in ("GargoyleSync = 5", "GargoyleSync = { version = 2, guilds = {} }",
                 'GargoyleSync = { version = 1, guilds = { 5, { id = "x" }, { id = 1, name = "G", raids = { { id = 1 } } } },'
                 ' characters = { "nope" }, done = { [1] = true } }'):
        game = Game(junk, "GargoyleDB = { outbox = 7, modules = 'x' }")
        game.slash()
        assert "No upcoming raids" in game.texts() or "No raid data yet" in game.texts()


def test_other_players_text_is_shown_not_run():
    api = {**API, "guilds": [{**API["guilds"][0], "raids": [
        {"id": 1, "title": 'MC "]] |cffff0000red|r |TInterface\\Icons\\x:0|t', "start": NOW + 86400, "size": 40,
         "notes": "line\nbreak \\ end\0", "signups": []}]}]}
    game = Game(sync_lua(api, {}))
    game.slash()
    text = game.texts()
    assert 'MC "]] ||cffff0000red||r ||TInterface\\Icons\\x:0||t' in text  # pipes doubled: shown as typed
    assert "line\nbreak \\ end\0" in text


def test_features_turn_on_and_off():
    game = Game(sync_lua(API, {}))
    ns = game.ns
    assert game.lua.globals().fake.category.name == "Gargoyle"
    game.slash()
    assert game.fake.button("Raid signups") is not None
    assert game.fake.button("Characters") is not None
    box = ns.optionBoxes.raids
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert game.db.modules.raids is False
    assert game.fake.button("Raid signups") is None and game.fake.button("Characters") is not None
    other = ns.optionBoxes.characters
    other.SetChecked(other, False)
    other.scripts.OnClick(other)
    assert game.fake.button("Characters") is None and "Every feature is turned off" in game.texts()
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    assert game.fake.button("Raid signups") is not None and "Molten Core" in game.texts()
    game.slash("options")
    assert game.fake.opened == 7
    game.slash()  # closes the window
    assert not game.lua.globals().GargoyleWindow.IsShown(game.lua.globals().GargoyleWindow)


def test_scrolling_and_picking_a_raid():
    raids = [{"id": i, "title": f"Raid {i:02d}", "start": NOW + i * 3600, "size": 20, "notes": "", "signups": []}
             for i in range(1, 15)]
    game = Game(sync_lua({**API, "guilds": [{**API["guilds"][0], "raids": raids}]}, {}))
    game.slash()
    assert "Raid 09" in game.texts() and "Raid 10" not in game.texts()
    wheel = next(w for w in game.fake.widgets.values() if w.scripts["OnMouseWheel"])
    wheel.scripts["OnMouseWheel"](wheel, -10)  # scroll down, past the end
    text = game.texts()
    assert "Raid 14" in text and "Raid 05" not in text


def test_an_odd_role_from_the_website_doesnt_break_the_tab():
    api = {**API, "characters": [{**API["characters"][0], "role": "bard"}], "guilds": [{**API["guilds"][0], "raids": [
        {**API["guilds"][0]["raids"][1], "signups": [{**API["guilds"][0]["raids"][1]["signups"][1], "role": "bard"}]}]}]}
    game = Game(sync_lua(api, {}))
    game.slash()
    assert "Damage" in game.dropdowns()[1]
    assert "as bard on Jainamage" in game.texts()


# ---- Characters (addon/Gargoyle/Modules/Characters.lua) ----

def picked(game):
    return {k: v for k, v in game.db.characters.items()}


def test_picking_the_character_you_play():
    game = Game(sync_lua(API, {}))
    game.fake.fire("PLAYER_ENTERING_WORLD")
    game.fake.runTimers()
    assert picked(game) == {}  # not picked: never read
    game.slash()
    game.click("Characters")
    text = game.texts()
    assert "Jainamage" in text and "Level 60 Mage" in text and "Not on your Gargoyle account." in text
    game.click("Keep it up to date")
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert (entry.picked, entry.at, entry.name, entry["class"], entry.race, entry.faction, entry.level) == \
        (NOW, NOW, "Jainamage", "MAGE", "Human", "Alliance", 60)
    assert [(t.tab, t.rank, t.name, t.spell) for t in entry.talents.values()] == \
        [(1, 2, "Arcane Subtlety", 11210), (3, 5, "Improved Frostbolt", 11070)]
    assert [(g.slot, g.item, g.enchant) for g in entry.gear.values()] == [(1, 240056, None), (9, 240052, 723), (16, 234571, 723)]
    assert [(k.name, k.rank) for k in entry.skills.values()] == [("Tailoring", 300), ("Enchanting", 280), ("Staves", 300)]
    assert "next time you reload (Reload UI) or log out" in game.printed()
    assert "Waiting to sync: 1 character. Reload or log out to send." in game.texts()
    assert game.fake.button("Stop keeping it up to date") is not None


def test_changes_are_read_after_a_moment_and_after_combat():
    saved = 'GargoyleDB = { characters = { ["Player-1-00ABCDEF"] = { picked = %d, at = %d, name = "Jainamage" } } }' % (NOW - 99, NOW - 50)
    game = Game(sync_lua(API, {}), saved)
    game.fake.runTimers()  # (the read when the feature starts)
    game.fake.char.level = 59
    game.fake.now = NOW + 30
    game.fake.combat = True
    game.fake.fire("PLAYER_EQUIPMENT_CHANGED")
    game.fake.fire("PLAYER_EQUIPMENT_CHANGED")
    assert len(game.fake.timers) == 1  # one read for a burst of changes
    game.fake.runTimers()
    assert game.db.characters["Player-1-00ABCDEF"].level == 60  # in combat: waits
    game.fake.combat = False
    game.fake.fire("PLAYER_REGEN_ENABLED")
    game.fake.runTimers()
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert (entry.level, entry.at, entry.picked) == (59, NOW + 30, NOW - 99)
    # Not read at logout (the game reports no gear by then).
    game.lua.execute("fake.char.gear = {}")
    game.fake.fire("PLAYER_LOGOUT")
    game.fake.runTimers()
    assert len(game.db.characters["Player-1-00ABCDEF"].gear) == 3


def test_parts_the_game_hasnt_loaded_are_left_out():
    game = Game(sync_lua(API, {}))
    game.lua.execute("""
      fake.char.talents = { { { "Arcane Focus", 1, 2, 0, 5, 11222 } } } -- nothing spent at level 60: not loaded
      fake.char.skills = { { "Professions", true, false, 0 } } -- folded away
      fake.char.gear = {} -- items without their details yet: read again shortly
    """)
    game.slash()
    game.click("Characters")
    game.click("Keep it up to date")
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert entry.talents is None and entry.skills is None and entry.gear is None
    game.lua.execute('fake.char.gear = { [1] = "|Hitem:240056:0|h" }')
    game.fake.runTimers()
    assert len(game.db.characters["Player-1-00ABCDEF"].gear) == 1


def test_status_from_the_website_and_stopping():
    saved = ('GargoyleDB = { characters = { ["Player-1-00ABCDEF"] = { picked = %d, at = %d, name = "Jainamage", level = 60, class = "MAGE" },'
             ' ["Player-1-0000BEEF"] = { picked = %d, at = %d, name = "Altie", level = 12, class = "MAGE" },'
             ' ["Player-1-0000DEAD"] = { picked = %d, at = %d, name = "Gone", level = 30, class = "MAGE" },'
             ' [5] = "junk" } }') % (NOW - 900, NOW - 800, NOW - 900, NOW - 800, NOW - 900, NOW - 800)
    api = {**API, "characters": API["characters"] + [
        {"id": 20, "name": "Jainamage", "class": "mage", "guild": None, "role": None, "game": "Player-1-00ABCDEF", "read": NOW - 800}],
        "removed": {"Player-1-0000DEAD": NOW - 100}}
    game = Game(sync_lua(api, {}, {"Player-1-0000BEEF": "limit"}), saved)
    assert sorted(picked(game)) == ["Player-1-0000BEEF", "Player-1-00ABCDEF"]  # deleted on the website: let go
    assert "Gone was deleted from your Gargoyle account" in game.printed()
    game.slash()
    game.click("Characters")
    text = game.texts()
    assert "On your Gargoyle account" in text and "Nothing waiting to sync." in text
    assert "|A:classicon-mage:16:16|a |cff3fc7ebAltie|r   |cffb0b0b0Level 12 Mage|r" in text
    assert "|cffe05050not added: your account has as many characters" in text
    game.click("Stop keeping it up to date")
    assert sorted(picked(game)) == ["Player-1-0000BEEF"] and "Not on your Gargoyle account." in game.texts()


def test_raid_signups_default_to_the_imported_character_you_play():
    api = {**API, "characters": [
        {"id": 11, "name": "Jainamage", "class": "mage", "guild": 5, "role": "healer"},
        {"id": 12, "name": "Jaina In Game", "class": "mage", "guild": 5, "role": "tank", "game": "Player-1-00ABCDEF", "read": NOW}]}
    api["guilds"] = [{**API["guilds"][0], "raids": [{**API["guilds"][0]["raids"][0]}]}]
    game = Game(sync_lua(api, {}))
    game.slash()
    assert "Jaina In Game" in game.dropdowns()[0]


def test_events_the_game_doesnt_have_are_skipped():
    game = Game(sync_lua(API, {}), 'fake.unknownEvents = { CHARACTER_POINTS_CHANGED = true }')
    assert game.lua.eval("#fake.events.PLAYER_EQUIPMENT_CHANGED") == 1
    assert game.lua.eval("fake.events.CHARACTER_POINTS_CHANGED") is None


def test_older_talent_functions():
    game = Game(sync_lua(API, {}), "fake.olderTalents()")
    game.slash()
    game.click("Characters")
    game.click("Keep it up to date")
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert [(t.tab, t.row, t.col, t.rank, t.name) for t in entry.talents.values()] ==         [(1, 2, 1, 2, "Arcane Subtlety"), (3, 1, 2, 5, "Improved Frostbolt")]


def test_professions_without_the_skills_page():
    game = Game(sync_lua(API, {}), """
      GetNumSkillLines, GetSkillLineInfo = nil, nil
      GetProfessions = function() return 3, nil, nil, 5 end
      GetProfessionInfo = function(index)
        if index == 3 then return "Tailoring", 1, 290, 300 end
        if index == 5 then return "Fishing", 1, 75, 150 end
      end
    """)
    game.slash()
    game.click("Characters")
    game.click("Keep it up to date")
    assert [(k.name, k.rank) for k in game.db.characters["Player-1-00ABCDEF"].skills.values()] == [("Tailoring", 290), ("Fishing", 75)]


def test_debug_command_saves_what_the_game_answers():
    game = Game(sync_lua(API, {}))
    game.slash("debug")
    report = game.db.debug
    assert report.names.UnitName[1] == "Jainamage" and report.names.UnitFullName.missing is True
    assert report.talents.configID == 77 and report.talents.nodes == 4 and len(report.talents.groups) == 3
    assert report.talents.spent[1].definition.spellID == 11210 and report.read.talents == 2
    assert "/reload (or log out) to save the answers" in game.printed()


def test_talents_wait_for_the_game_to_load_them_and_full_names():
    game = Game(sync_lua(API, {}), 'fake.char.configID = nil; fake.surname = "Proudmoore"')
    game.slash()
    game.click("Characters")
    assert "Jainamage Proudmoore" in game.texts()
    game.click("Keep it up to date")
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert entry.talents is None and entry.name == "Jainamage Proudmoore"
    game.fake.char.configID = 77
    game.fake.fire("TRAIT_CONFIG_UPDATED")
    game.fake.runTimers()
    assert len(game.db.characters["Player-1-00ABCDEF"].talents) == 2


# ---- The window's buttons and the minimap button ----

def test_reload_button_and_tabs():
    game = Game(sync_lua(API, {}))
    game.slash()
    tabs = {w.text: w for w in game.fake.widgets.values() if w.kind == "Button" and w.text in ("Raid signups", "Characters")}
    assert tabs["Raid signups"].selected and not tabs["Characters"].selected
    game.click("Characters")
    assert tabs["Characters"].selected and not tabs["Raid signups"].selected and game.fake.sound == 841
    game.click("Reload UI")
    assert game.fake.reloaded is True
    assert game.lua.globals().GargoyleWindow.sharp and game.lua.globals().GargoyleMinimapButton.sharp


def test_role_dropdown_shows_role_icons_and_a_typed_note_stays():
    game = Game(sync_lua(API, {}))
    game.slash()
    role = next(w for w in game.fake.widgets.values() if w.kind == "DropdownButton" and "Healer" in w.text)
    role.GenerateMenu(role)
    assert [r.text for r in role.radios.values()] == [
        "|A:UI-LFG-RoleIcon-Tank-Micro-GroupFinder:16:16|a Tank", "|A:UI-LFG-RoleIcon-Healer-Micro-GroupFinder:16:16|a Healer",
        "|A:UI-LFG-RoleIcon-DPS-Micro-GroupFinder:16:16|a Damage"]
    note = next(w for w in game.fake.widgets.values() if w.kind == "EditBox")
    note.SetText(note, "bringing flasks")
    game.choose("Tank")
    game.click("Coming")
    (action,) = game.outbox()
    assert (action["role"], action["note"]) == ("tank", "bringing flasks")


def test_minimap_button():
    game = Game(sync_lua(API, {}))
    button = game.lua.globals().GargoyleMinimapButton
    assert button.shown and button.point[4] == pytest.approx(-57.45, abs=0.01)  # 220 degrees: down and to the left
    # Hovering shows the next raid; a click opens the window, a right-click the options.
    button.scripts.OnEnter(button)
    lines = list(game.lua.globals().GameTooltip.lines.values())
    assert lines[0] == "Gargoyle" and lines[1].startswith("Next raid: Molten Core, ")
    button.scripts.OnClick(button, "LeftButton")
    assert game.lua.globals().GargoyleWindow.shown
    button.scripts.OnClick(button, "RightButton")
    assert game.fake.opened == 7
    # Dragging it round the minimap: it follows the cursor (here straight above the middle).
    game.fake.cursor[1], game.fake.cursor[2] = 500, 600
    button.scripts.OnDragStart(button)
    button.scripts.OnUpdate(button)
    button.scripts.OnDragStop(button)
    assert game.db.minimap.angle == pytest.approx(90) and button.scripts.OnUpdate is None
    assert button.point[4] == pytest.approx(0, abs=0.01) and button.point[5] == pytest.approx(75)
    # Hidden from the options, and back with /gargoyle minimap.
    box = game.ns.minimapBox
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert not button.shown and game.db.minimap.hide is True
    game.slash("minimap")
    assert button.shown and game.db.minimap.hide is None and box.checked


def test_minimap_button_remembers_its_place():
    game = Game(sync_lua(API, {}), "GargoyleDB = { minimap = { angle = 0, hide = true } }")
    button = game.lua.globals().GargoyleMinimapButton
    assert list(button.point.values())[3:] == [75, 0] and not button.shown


def test_a_character_read_again_unchanged_keeps_its_time():
    api = {**API, "characters": API["characters"] + [
        {"id": 20, "name": "Jainamage", "class": "mage", "guild": None, "role": None, "game": "Player-1-00ABCDEF", "read": NOW}]}
    game = Game(sync_lua(api, {}))
    game.slash()
    game.click("Characters")
    game.click("Keep it up to date")
    assert game.db.characters["Player-1-00ABCDEF"].at == NOW and "Nothing waiting to sync." in game.texts()
    # Read again later (after a reload, say) with nothing changed: still the same, nothing to send.
    game.fake.now = NOW + 600
    game.fake.fire("PLAYER_ENTERING_WORLD")
    game.fake.runTimers()
    assert game.db.characters["Player-1-00ABCDEF"].at == NOW and "Nothing waiting to sync." in game.texts()
    # Talents not loaded this time: kept as they were, still unchanged.
    game.fake.char.configID = None
    game.fake.fire("TRAIT_CONFIG_UPDATED")
    game.fake.runTimers()
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert entry.at == NOW and len(entry.talents) == 2
    # A real change is a new read.
    game.fake.char.level = 59
    game.fake.fire("PLAYER_LEVEL_UP")
    game.fake.runTimers()
    assert game.db.characters["Player-1-00ABCDEF"].at == NOW + 600 and "Waiting to sync: 1 character" in game.texts()


def test_text_is_cut_by_letters_not_bytes():
    title = "Огненные Недра " * 6  # 90 letters of 2 bytes (Cyrillic)
    api = {**API, "guilds": [{**API["guilds"][0], "raids": [
        {"id": 1, "title": title, "start": NOW + 86400, "size": 40, "notes": "", "signups": []}]}]}
    game = Game(sync_lua(api, {}))
    game.slash()
    assert title[:80] in game.texts()  # (80 letters, the website's limit: not 80 bytes)
    note = next(w for w in game.fake.widgets.values() if w.kind == "EditBox")
    note.SetText(note, "é" * 199 + "😀🙂")
    game.click("Coming")
    assert game.outbox()[0]["note"] == "é" * 199 + "😀"


# ---- Raid alerts: new raids and reminders ----

def glow(game):
    return next(w for w in game.fake.widgets.values() if w.kind == "AnimationGroup").parent


def in_game(game, combat=False):
    """Past the loading screen, a few seconds in."""
    game.fake.combat = combat
    game.fake.fire("PLAYER_ENTERING_WORLD")
    game.fake.runTimers()


def not_signed_up(**changes):
    """API, with your signup for Molten Core (tomorrow) taken away."""
    raids = [dict(r) for r in API["guilds"][0]["raids"]]
    raids[1]["signups"] = [s for s in raids[1]["signups"] if not s.get("mine")]
    raids[1].update(changes)
    return {**API, "guilds": [{**API["guilds"][0], "raids": raids}]}


def test_new_raids_glow_with_a_bubble_once():
    game = Game(sync_lua(API, {}))
    in_game(game)
    g, bubble, button = glow(game), game.lua.globals().GargoyleMinimapBubble, game.lua.globals().GargoyleMinimapButton
    # Blackwing Lair is new (Molten Core you've signed up for already: not new, and no reminder).
    assert g.shown and g.pulse.playing and bubble.shown and game.fake.sound == 18019
    assert bubble.title.text == "You have unseen raids scheduled!" and bubble.detail.text.startswith("Blackwing Lair, ")
    assert "and 1 more" not in bubble.detail.text and game.lua.globals().GargoyleReminder is None
    # (Below the button and reaching left, as the minimap is top right; pointing at the button.)
    point = list(bubble.point.values())
    assert point[0] == "TOPRIGHT" and point[2:4] == ["BOTTOM", 32] and game.lua.eval("GargoyleMinimapBubble.point[2] == GargoyleMinimapButton")
    assert bubble.arrowUp.shown and not bubble.arrowDown.shown
    button.scripts.OnEnter(button)
    assert "1 new raid you haven't seen" in list(game.lua.globals().GameTooltip.lines.values())
    # Once: the next check (and the next login) doesn't tell you again, but it glows until you look.
    bubble.Hide(bubble)
    game.fake.sound = None
    game.fake.runTimers()
    assert not bubble.shown and game.fake.sound is None and g.shown
    # Clicking the glowing button opens the Raids tab, marks the raid new there, and the glow stops.
    button.scripts.OnClick(button, "LeftButton")
    assert "|cff19ff19New|r  Blackwing Lair" in game.texts() and "New|r  Molten Core" not in game.texts()
    assert not g.shown and not g.pulse.playing and game.db.alerts.seen[2] == NOW + 7 * 86400
    game.fake.runTimers()
    assert not g.shown and game.fake.sound is None


def test_new_raids_after_a_reload():
    told = Game(sync_lua(API, {}), f"GargoyleDB = {{ alerts = {{ told = {{ [2] = {NOW + 7 * 86400} }} }} }}")
    in_game(told)
    assert glow(told).shown and told.lua.globals().GargoyleMinimapBubble is None and told.fake.sound is None
    seen = Game(sync_lua(API, {}), f"GargoyleDB = {{ alerts = {{ seen = {{ [2] = {NOW + 7 * 86400} }} }} }}")
    in_game(seen)
    assert not glow(seen).shown and seen.fake.sound is None


def test_the_bubble_opens_the_raids_tab_and_hidden_buttons_say_it_in_chat():
    game = Game(sync_lua(API, {}))
    in_game(game)
    game.slash()
    game.click("Characters")
    game.slash()  # (closed again, on the Characters tab)
    bubble = game.lua.globals().GargoyleMinimapBubble
    bubble.scripts.OnClick(bubble)
    assert not bubble.shown and "|cff19ff19New|r  Blackwing Lair" in game.texts() and not glow(game).shown
    hidden = Game(sync_lua(API, {}), "GargoyleDB = { minimap = { hide = true } }")
    in_game(hidden)
    assert hidden.lua.globals().GargoyleMinimapBubble is None
    assert "you have unseen raids scheduled! Blackwing Lair, " in hidden.printed() and hidden.fake.sound == 18019


def test_a_reminder_a_day_before_a_raid_you_havent_signed_up_for():
    game = Game(sync_lua(not_signed_up(), {}))
    in_game(game)
    reminder, bubble = game.lua.globals().GargoyleReminder, game.lua.globals().GargoyleMinimapBubble
    text = game.texts()
    assert reminder.shown and "Your next raid is in 24 hours" in text and "Molten Core" in text
    assert "You haven't signed up yet." in text and "You can turn these reminders off in Gargoyle's options." in text
    # Molten Core got the reminder, so the new-raid bubble is only about Blackwing Lair. One chime.
    assert bubble.detail.text.startswith("Blackwing Lair, ") and "more" not in bubble.detail.text
    assert game.db.alerts.reminded[1] == NOW + 86400
    # Its one button opens Gargoyle on that raid (even with another raid picked before).
    game.slash()
    row = next(w for w in game.fake.widgets.values() if w.kind == "Button" and w.raid and w.raid.title == "Blackwing Lair")
    row.scripts.OnClick(row)
    game.slash()
    assert "Bring fire resist" not in game.texts()
    game.click("Open Gargoyle")
    assert not reminder.shown and game.lua.globals().GargoyleWindow.shown and "Bring fire resist" in game.texts()
    # Once per raid.
    game.lua.globals().GargoyleWindow.Hide(game.lua.globals().GargoyleWindow)
    game.fake.runTimers()
    assert not reminder.shown


def test_reminders_wait_for_the_day_and_for_combat_to_end():
    game = Game(sync_lua(not_signed_up(start=NOW + 86400 + 120), {}))
    in_game(game, combat=True)
    assert game.lua.globals().GargoyleReminder is None and game.lua.globals().GargoyleMinimapBubble is None
    game.fake.combat = False
    game.fake.fire("PLAYER_REGEN_ENABLED")
    assert game.lua.globals().GargoyleReminder is None  # (a day and 2 minutes away: not yet)
    assert game.lua.globals().GargoyleMinimapBubble.shown
    game.fake.now = NOW + 120
    game.fake.runTimers()
    assert game.lua.globals().GargoyleReminder.shown and "Your next raid is in 24 hours" in game.texts()
    soon = Game(sync_lua(not_signed_up(start=NOW + 40 * 60), {}))
    in_game(soon)
    assert "Your next raid is in 40 minutes" in soon.texts()
    later = Game(sync_lua(not_signed_up(start=NOW + 3 * 3600 + 100), {}))
    in_game(later)
    assert "Your next raid is in 3 hours" in later.texts()


def test_a_signup_made_in_game_counts():
    game = Game(sync_lua(not_signed_up(), {}))
    game.slash()
    game.click("Can't come")
    in_game(game)
    assert game.lua.globals().GargoyleReminder is None


def test_raid_alerts_can_be_turned_off():
    game = Game(sync_lua(not_signed_up(), {}))
    for box in (game.ns.newRaidsBox, game.ns.remindersBox):
        assert box.checked
        box.SetChecked(box, False)
        box.scripts.OnClick(box)
    assert game.db.alerts.newRaids is False and game.db.alerts.reminders is False
    in_game(game)
    assert game.lua.globals().GargoyleReminder is None and game.lua.globals().GargoyleMinimapBubble is None
    assert not glow(game).shown and game.fake.sound is None
    # Back on: the glow is back straight away (the bubble and reminder come with the next check).
    box = game.ns.newRaidsBox
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    assert glow(game).shown and game.db.alerts.newRaids is None
    # The raid feature off: no glow either.
    game.ns.optionBoxes.raids.SetChecked(game.ns.optionBoxes.raids, False)
    game.ns.optionBoxes.raids.scripts.OnClick(game.ns.optionBoxes.raids)
    assert not glow(game).shown


def test_old_and_odd_alert_records_are_dropped():
    game = Game(sync_lua(API, {}), f'GargoyleDB = {{ alerts = {{ seen = {{ [1] = 5, x = {NOW}, [3] = "a", [9] = {NOW} }}, told = 7 }} }}')
    in_game(game)
    assert dict(game.db.alerts.seen.items()) == {9: NOW}
    assert game.db.alerts.told[2] == NOW + 7 * 86400
