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
TOOLTIPS = PROJECT / "addon" / "Gargoyle_Tooltips"
COLLECTOR = PROJECT / "addon" / "Gargoyle_Collector"
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
  "SetSmoothing", "Raise" }
for _, name in ipairs(NOOP) do methods[name] = function() end end
function methods:SetPoint(...) self.point = { ... } end
function methods:SetAllPoints(target) self.over = target end
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
function fake.chooseIn(current, text) -- the dropdown showing `current`: pick exactly `text`
  for _, w in ipairs(fake.widgets) do
    if w.kind == "DropdownButton" and w:IsVisible() and w.enabled and w.text == current then
      w:GenerateMenu()
      for _, r in ipairs(w.radios) do
        if r.text == text then
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
time = function(t) if t then return os.time(t) end return fake.now end
date = function(format, t) return os.date(format, t or fake.now) end
function methods:GetFrameLevel() return self.level or 1 end
function methods:SetFrameLevel(level) self.level = level end
-- hooksecurefunc("Name", fn): fn runs after the game's function, with the same arguments.
hooksecurefunc = function(name, fn)
  local original = _G[name]
  _G[name] = function(...) original(...); fn(...) end
end
-- The game's calendar (Blizzard_Calendar, loaded when it's first opened): fake.openCalendar(year,
-- month) loads it and shows that month, with the days before and after as the game does.
function fake.openCalendar(year, month)
  if not CalendarFrame then
    CalendarFrame = fake.new("Frame", "CalendarFrame", UIParent)
    for i = 1, 42 do fake.new("Button", "CalendarDayButton" .. i, CalendarFrame) end
    CalendarFrame_Update = function()
      local first = os.date("*t", os.time({ year = CalendarFrame.viewedYear, month = CalendarFrame.viewedMonth, day = 1, hour = 12 }))
      local before = (first.wday - 1) -- (weeks start on Sunday)
      for i = 1, 42 do
        local d = os.date("*t", os.time({ year = first.year, month = first.month, day = i - before, hour = 12 }))
        local button = _G["CalendarDayButton" .. i]
        button.day = d.day
        button.monthOffset = (d.month == first.month and 0) or ((d.year * 12 + d.month < first.year * 12 + first.month) and -1 or 1)
      end
    end
    fake.fire("ADDON_LOADED", "Blizzard_Calendar")
  end
  CalendarFrame.viewedYear, CalendarFrame.viewedMonth = year, month
  CalendarFrame_Update()
end
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
  -- { name, header, unfolded, rank, can be unlearned } (as GetSkillLineInfo's 1st-4th and 8th)
  skills = { { "Professions", true, true, 0 }, { "Tailoring", false, true, 300, true }, { "Enchanting", false, true, 280, true },
             { "Weapon Skills", true, true, 0 }, { "Staves", false, true, 300, false } },
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
  GetNodeInfo = function(_, id) -- (a talent with a 7th value true can't take a point yet)
    local t = talent(id)
    return { ID = id, ranksPurchased = t[4], activeRank = t[4], maxRanks = t[5], entryIDs = { id },
             activeEntry = { entryID = id, rank = t[4] }, groupIDs = { 600 + math.floor(id / 1000) },
             canPurchaseRank = t[4] < t[5] and not t[7] }
  end,
  GetTreeCurrencyInfo = function() return { { traitCurrencyID = 1, quantity = fake.char.unspent, spent = 0 } } end,
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
-- The game's talent window (Blizzard_PlayerSpells, loaded when it's first opened):
-- fake.openTalents() loads it and shows it, with a button for each talent, as the game draws
-- it; fake.redrawTalents() is the game redrawing it after a change. Nothing that changes
-- talents may ever be called.
EventRegistry = { callbacks = {} }
function EventRegistry:RegisterCallback(event, fn, owner)
  self.callbacks[event] = self.callbacks[event] or {}
  table.insert(self.callbacks[event], { fn = fn, owner = owner })
end
function EventRegistry:TriggerEvent(event, ...)
  for _, c in ipairs(self.callbacks[event] or {}) do c.fn(c.owner, ...) end
end
local function never() error("Gargoyle must never change talents") end
C_Traits.PurchaseRank, C_Traits.RefundRank, C_Traits.CommitConfig, C_ClassTalents.CommitConfig = never, never, never, never
function fake.redrawTalents()
  EventRegistry:TriggerEvent("TalentFrameBase.ButtonsUpdated", 500)
end
function fake.openTalents()
  if not PlayerSpellsFrame then
    PlayerSpellsFrame = fake.new("Frame", "PlayerSpellsFrame", UIParent)
    local frame = fake.new("Frame", nil, PlayerSpellsFrame)
    PlayerSpellsFrame.TalentsFrame = frame
    frame.ButtonsParent = fake.new("Frame", nil, frame)
    frame.Background = fake.new("Texture", nil, frame)
    frame.buttons = {}
    function frame:GetConfigID() return fake.talentFrameConfig or fake.char.configID end
    function frame:EnumerateAllTalentButtons() return pairs(self.buttons) end
    frame.PurchaseRank, frame.CommitConfig = never, never
    fake.fire("ADDON_LOADED", "Blizzard_PlayerSpells")
  end
  local frame = PlayerSpellsFrame.TalentsFrame
  frame.buttons = {}
  for _, id in ipairs(C_Traits.GetTreeNodes(500)) do
    local button = fake.new("Button", nil, frame.ButtonsParent)
    button.nodeID = id
    function button:GetNodeID() return self.nodeID end
    frame.buttons[button] = true
  end
  frame:Show()
  fake.redrawTalents()
end
GetNumSkillLines = function() return #fake.char.skills end
GetSkillLineInfo = function(i)
  local s = fake.char.skills[i]
  return s[1], s[2], s[3], s[4], 0, 0, 0, s[5]
end
InCombatLockdown = function() return fake.combat == true end
C_Timer = { After = function(_, fn) table.insert(fake.timers, fn) end }
function fake.runTimers()
  local due = fake.timers
  fake.timers = {}
  for _, fn in ipairs(due) do fn() end
end
-- What Gargoyle Damage Tooltips reads: the character's spell damage (by school), healing,
-- crit, attack power and weapon damage, and a spell's cast time and cost.
fake.stats = { spellDamage = {}, healing = 0, spellCrit = 0, crit = 0, ap = 0, weapon = { 0, 0 } }
fake.castTimes, fake.costs, fake.tooltipHooks = {}, {}, {}
GetSpellBonusDamage = function(school) return fake.stats.spellDamage[school] or 0 end
GetSpellBonusHealing = function() return fake.stats.healing end
GetSpellCritChance = function() return fake.stats.spellCrit end
GetCritChance = function() return fake.stats.crit end
GetRangedCritChance = function() return fake.stats.crit end
UnitAttackPower = function() return fake.stats.ap, 0, 0 end
UnitRangedAttackPower = function() return fake.stats.ap, 0, 0 end
UnitDamage = function() return fake.stats.weapon[1], fake.stats.weapon[2] end
UnitRangedDamage = function() return 3, fake.stats.weapon[1], fake.stats.weapon[2] end
C_Spell.GetSpellInfo = function(id) return { spellID = id, castTime = fake.castTimes[id] or 0 } end
C_Spell.GetSpellPowerCost = function(id) return fake.costs[id] and { { type = 0, name = "MANA", cost = fake.costs[id] } } or {} end
Enum = { TooltipDataType = { Item = 0, Spell = 1 } }
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn) fake.tooltipHooks[kind] = fn end }
function GameTooltip:AddDoubleLine(left, right) table.insert(self.lines, left .. " | " .. right) end
function fake.spellTooltip(spellID) -- hover a spell: the tooltip's lines
  GameTooltip:SetOwner(UIParent)
  GameTooltip:SetText("A spell")
  if fake.tooltipHooks[1] then fake.tooltipHooks[1](GameTooltip, { type = 1, id = spellID }) end
  return table.concat(GameTooltip.lines, "\n")
end
-- The dungeon journal's side of the game: where you are (GetInstanceInfo), and items as the
-- game knows them. An item in fake.uncached isn't loaded yet: it answers nothing until
-- fake.loadItems(). Hovering an item runs the item tooltip hooks, as the game does.
fake.instance = { "Elwynn Forest", "none", 0, "", 5, 0, false, 0 }
GetInstanceInfo = function() return unpack(fake.instance) end
fake.items, fake.uncached, fake.itemWaits, fake.worn = {}, {}, {}, {}
C_Item = {
  GetItemInfo = function(id)
    local it = fake.items[id]
    if not it or fake.uncached[id] then return nil end
    return it[1], "link", it[2], 30, 25, "Armor", "Cloth", 1, "INVTYPE_CHEST", it[3]
  end,
  IsEquippedItem = function(id) return fake.worn[id] == true end,
  GetItemQualityColor = function(q) return 1, 1, 1, "ff00000" .. q end,
}
Item = {}
function Item:CreateFromItemID(id)
  return { ContinueOnItemLoad = function(_, fn) table.insert(fake.itemWaits, { id = id, fn = fn }) end }
end
function fake.loadItems()
  local waits = fake.itemWaits
  fake.itemWaits = {}
  for _, w in ipairs(waits) do
    fake.uncached[w.id] = nil
    w.fn()
  end
end
function GameTooltip:SetItemByID(id)
  self.lines = { (fake.items[id] or { "?" })[1] }
  if fake.tooltipHooks[0] then fake.tooltipHooks[0](self, { type = 0, id = id }) end
end
function GameTooltip:SetSpellByID(id) self.lines = { "spell " .. id } end
function fake.itemTooltip(id) -- hover an item anywhere: the tooltip's lines
  GameTooltip:SetOwner(UIParent)
  GameTooltip:SetItemByID(id)
  return table.concat(GameTooltip.lines, "\n")
end
function methods:SetTexture(t) self.texture = t end
function methods:SetTexCoord(...) self.coords = string.format("%%g,%%g,%%g,%%g", ...) end
-- Quests done (C_QuestLog), abilities' text (C_Spell.GetSpellDescription), and the game's own
-- map pin, which records where it was put (only "Show on map" may set it).
fake.questsDone, fake.spellText, fake.pins = {}, {}, {}
C_QuestLog = { IsQuestFlaggedCompleted = function(id) return fake.questsDone[id] == true end }
C_Spell.GetSpellDescription = function(id) return fake.spellText[id] or "" end
UiMapPoint = { CreateFromCoordinates = function(map, x, y) return { uiMapID = map, x = x, y = y } end }
C_Map = { CanSetUserWaypointOnMap = function(map) return map ~= 9999 end,
          SetUserWaypoint = function(point) table.insert(fake.pins, point) end }
C_SuperTrack = { SetSuperTrackedUserWaypoint = function(on) fake.tracking = on end }
-- (nothing may ever equip, use or pick up an item)
local function noTouching() error("Gargoyle must never change your items") end
EquipItemByName, UseItemByName, PickupItem, C_Item.EquipItemByName, C_Item.PickupItemByID = noTouching, noTouching, noTouching, noTouching, noTouching
Settings = {
  RegisterCanvasLayoutCategory = function(panel, name) return { name = name, GetID = function() return 7 end } end,
  RegisterAddOnCategory = function(category) fake.category = category end,
  OpenToCategory = function(id) fake.opened = id end,
}
""" % NOW

# What the data collector (addon/Gargoyle_Collector) also reads: the game's version, tooltip
# data, bags, the spellbook, trainers, vendors and loot windows. fake.asked records every item
# the game was asked about (it must only ever be ones you came across).
COLLECTOR_GAME = r"""
fake.build, fake.asked, fake.bags, fake.book, fake.trainer, fake.merchant, fake.loot = 60001, {}, {}, {}, {}, {}, {}
fake.spellNames = { [133] = "Fireball", [116] = "Frostbolt", [10] = "Blizzard" }
GetBuildInfo = function() return "1.16.1", tostring(fake.build), "Oct 1 2026", 11601 end
debugprofilestop = function() return 0 end
local itemInfo = C_Item.GetItemInfo
C_Item.GetItemInfo = function(id) table.insert(fake.asked, id); return itemInfo(id) end
C_Item.GetItemStats = function() return { ITEM_MOD_STAMINA_SHORT = 10, ITEM_MOD_INTELLECT_SHORT = 7 } end
C_TooltipInfo = {
  GetItemByID = function(id)
    local it = fake.items[id]
    return it and { id = id, lines = {
      { leftText = it[1], leftColor = { r = 0.64, g = 0.21, b = 0.93 } },
      { leftText = "Equip: Restores 5 mana per 5 sec.", leftColor = { r = 0, g = 1, b = 0 } },
      { leftText = "Requires Level 60", leftColor = { r = 1, g = 0.13, b = 0.13 } },
      { type = 1, args = { { field = "leftText", stringVal = it.flavor or "\"Shiny.\"" } } } } }
  end,
  GetSpellByID = function(id) return { id = id, lines = { { leftText = C_Spell.GetSpellName(id), rightText = "Rank 1" } } } end,
  GetTrainerService = function(i) return fake.trainer[i] and { id = fake.trainer[i][1] } end,
}
local talentName = C_Spell.GetSpellName
C_Spell.GetSpellName = function(id) return fake.spellNames[id] or talentName(id) end
C_Spell.GetSpellSubtext = function() return "Rank 1" end
GetSpellBaseCooldown = function() return 0, 1500 end
C_Traits.GetTraitDescription = function(entry, rank) return "Rank " .. rank .. " of talent " .. entry end
C_Container = {
  GetContainerNumSlots = function(bag) return fake.bags[bag] and 16 or 0 end,
  GetContainerItemID = function(bag, slot) return fake.bags[bag] and fake.bags[bag][slot] end,
}
GetNumSpellTabs = function() return 1 end
GetSpellTabInfo = function() return "Mage", "icon", 0, #fake.book end
GetSpellBookItemInfo = function(i) return "SPELL", fake.book[i] end
GetNumTrainerServices = function() return #fake.trainer end
GetTrainerServiceInfo = function(i) return fake.trainer[i][2], fake.trainer[i][3], "available" end
GetTrainerServiceLevelReq = function(i) return fake.trainer[i][4] end
GetTrainerServiceCost = function(i) return fake.trainer[i][5] end
GetMerchantNumItems = function() return #fake.merchant end
GetMerchantItemID = function(i) return fake.merchant[i] end
GetNumLootItems = function() return #fake.loot end
GetLootSlotLink = function(i) return "|cff1eff00|Hitem:" .. fake.loot[i] .. "::::::::60:::::|h[Loot]|h|r" end
"""

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
    def __init__(self, sync=None, saved=None, now=NOW, tooltips=False, journal=None, before=None, collector=False):
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FAKE_GAME)
        self.fake = self.lua.globals().fake
        self.fake.now = now
        if collector:
            self.lua.execute(COLLECTOR_GAME)
        if sync:
            self.lua.execute(sync)
        if saved:
            self.lua.execute(saved)
        if before:  # (game state from before the login: where you are...)
            self.lua.execute(before)
        self.ns = self.lua.table()
        run = self.lua.eval('function(src, name, ns) local f = assert(loadstring(src, "@" .. name)); f("Gargoyle", ns) end')
        toc = (ADDON / "Gargoyle.toc").read_text(encoding="utf-8").splitlines()
        for name in (line.strip() for line in toc):
            if name and not name.startswith("#"):
                source = (ADDON / name.replace("\\", "/")).read_text(encoding="utf-8")
                if journal is not None and name == "Data\\Journal.lua":
                    source = journal  # (a small journal for the test, in place of the real one)
                run(source, name, self.ns)
        self.fake.fire("ADDON_LOADED", "Gargoyle")
        if tooltips:  # (the game loads it after Gargoyle: its name comes later)
            self.tips_ns = self.lua.table()
            toc = (TOOLTIPS / "Gargoyle_Tooltips.toc").read_text(encoding="utf-8").splitlines()
            for name in (line.strip() for line in toc):
                if name and not name.startswith("#"):
                    run((TOOLTIPS / name.replace("\\", "/")).read_text(encoding="utf-8"), name, self.tips_ns)
            self.fake.fire("ADDON_LOADED", "Gargoyle_Tooltips")
        if collector:  # (and the data collector, after Gargoyle too)
            load = self.lua.eval('function(src, name) local f = assert(loadstring(src, "@" .. name)); f("Gargoyle_Collector", {}) end')
            toc = (COLLECTOR / "Gargoyle_Collector.toc").read_text(encoding="utf-8").splitlines()
            for name in (line.strip() for line in toc):
                if name and not name.startswith("#"):
                    load((COLLECTOR / name.replace("\\", "/")).read_text(encoding="utf-8"), name)
            self.fake.fire("ADDON_LOADED", "Gargoyle_Collector")
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

    def choose_in(self, current, text):
        assert self.fake.chooseIn(current, text), f"no dropdown showing {current!r} offers {text!r}"

    def type_in(self, n, text):
        """Types into the n-th edit box on screen (0: the first)."""
        boxes = [w for w in self.fake.widgets.values() if w.kind == "EditBox" and w.IsVisible(w)]
        boxes[n].SetText(boxes[n], text)

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
    assert game.fake.button("Talent plans") is not None
    assert game.fake.button("Dungeons") is not None
    for key in ("characters", "talents", "journal"):
        other = ns.optionBoxes[key]
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
    assert [(k.name, k.rank) for k in entry.skills.values()] == [("Tailoring", 300), ("Enchanting", 280)]  # (no weapon skills)
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


def test_only_picked_characters_are_watched():
    game = Game(sync_lua(API, {}))
    watching = lambda: game.lua.eval("#(fake.events.PLAYER_EQUIPMENT_CHANGED or {})")  # noqa: E731
    assert watching() == 0  # not picked: nothing is watched at all
    game.slash()
    game.click("Characters")
    game.click("Keep it up to date")
    assert watching() == 1
    game.click("Stop keeping it up to date")
    assert watching() == 0
    game.click("Keep it up to date")
    game.ns.SetEnabled("characters", False)
    assert watching() == 0
    game.ns.SetEnabled("characters", True)
    assert watching() == 1


def test_a_change_reads_only_what_it_touches():
    saved = 'GargoyleDB = { characters = { ["Player-1-00ABCDEF"] = { picked = %d, at = %d, name = "Jainamage" } } }' % (NOW - 99, NOW - 50)
    game = Game(sync_lua(API, {}), saved)
    game.fake.runTimers()
    game.lua.execute("""
      fake.reads = {}
      local gear, talents = GetInventoryItemLink, C_ClassTalents.GetActiveConfigID
      GetInventoryItemLink = function(...) fake.reads.gear = true; return gear(...) end
      C_ClassTalents.GetActiveConfigID = function(...) fake.reads.talents = true; return talents(...) end
    """)
    game.fake.fire("PLAYER_EQUIPMENT_CHANGED")
    game.fake.runTimers()
    assert game.lua.eval("fake.reads.gear == true and fake.reads.talents == nil")
    # Weapon skills going up aren't a change; a profession going up is.
    game.fake.now = NOW + 60
    game.lua.execute("fake.char.skills[5][4] = 301")
    game.fake.fire("SKILL_LINES_CHANGED")
    game.fake.runTimers()
    entry = game.db.characters["Player-1-00ABCDEF"]
    assert entry.at == NOW and game.lua.eval("fake.reads.talents == nil")
    game.lua.execute("fake.char.skills[2][4] = 301")
    game.fake.fire("SKILL_LINES_CHANGED")
    game.fake.runTimers()
    assert game.db.characters["Player-1-00ABCDEF"].at == NOW + 60
    # A game that doesn't say which skills can be unlearned: every skill is kept, as before.
    game.lua.execute("for _, s in ipairs(fake.char.skills) do s[5] = nil end")
    game.fake.fire("SKILL_LINES_CHANGED")
    game.fake.runTimers()
    assert [k.name for k in game.db.characters["Player-1-00ABCDEF"].skills.values()] == ["Tailoring", "Enchanting", "Staves"]


def test_gear_retries_start_over_once_it_loads():
    game = Game(sync_lua(API, {}))
    game.lua.execute("fake.char.gear = {}; fake.slotIDs = { [1] = 240056 }; GetInventoryItemID = function(_, s) return fake.slotIDs[s] end")
    game.slash()
    game.click("Characters")
    game.click("Keep it up to date")
    for _ in range(5):
        game.fake.runTimers()
    assert game.db.characters["Player-1-00ABCDEF"].gear is None and len(game.fake.timers) == 0  # gave up after a few
    game.lua.execute('fake.char.gear = { [1] = "|Hitem:240056:0|h" }')
    game.fake.fire("PLAYER_EQUIPMENT_CHANGED")
    game.fake.runTimers()
    assert len(game.db.characters["Player-1-00ABCDEF"].gear) == 1
    # Later, an item not loaded again: it's retried again (the count started over).
    game.lua.execute("fake.char.gear = {}")
    game.fake.fire("PLAYER_EQUIPMENT_CHANGED")
    game.fake.runTimers()
    assert len(game.fake.timers) == 1


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
    saved = 'fake.unknownEvents = { CHARACTER_POINTS_CHANGED = true }; GargoyleDB = { characters = { ["Player-1-00ABCDEF"] = { picked = 1 } } }'
    game = Game(sync_lua(API, {}), saved)
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


def test_the_addons_own_images_are_there_for_the_game():
    """Every image the addons name is in them, as a TGA the game reads: uncompressed, 32-bit
    (so it can be see-through), square, sides a power of two."""
    import re
    import struct
    window = (ADDON / "Window.lua").read_text(encoding="utf-8")
    assert re.search(r'local MEDIA = "([^"]+)"', window).group(1) == r"Interface\\AddOns\\Gargoyle\\Media\\"
    images = [ADDON / "Media" / f"{name}.tga" for name in re.findall(r'MEDIA \.\. "(\w+)"', window)]
    for toc in (ADDON / "Gargoyle.toc", TOOLTIPS / "Gargoyle_Tooltips.toc", COLLECTOR / "Gargoyle_Collector.toc"):
        icon = re.search(r"^## IconTexture: Interface\\AddOns\\(\S+)$", toc.read_text(encoding="utf-8"), re.M).group(1)
        images.append(PROJECT / "addon" / (icon.replace("\\", "/") + ".tga"))
    assert len(images) == 6
    for image in images:
        data = image.read_bytes()
        kind, (width, height), depth = data[2], struct.unpack("<HH", data[12:16]), data[16]
        assert kind == 2 and depth == 32 and width == height and width & (width - 1) == 0, image
        assert len(data) >= 18 + data[0] + width * height * 4, image


def test_debug_command_saves_what_the_game_answers():
    game = Game(sync_lua(API, {}))
    game.slash("debug")
    report = game.db.debug
    assert report.names.UnitName[1] == "Jainamage" and report.names.UnitFullName.missing is True
    assert report.talents.configID == 77 and report.talents.nodes == 4 and len(report.talents.groups) == 3
    assert report.talents.spent[1].definition.spellID == 11210 and report.read.talents == 2
    assert report.plans.currency[1].quantity == 0 and report.plans.firstNode.canPurchaseRank is False
    assert report.plans.window == "<not loaded>" and report.plans.progress == "<no plan>"
    assert "/reload (or log out) to save the answers" in game.printed()
    game.fake.openTalents()
    game.slash("debug")
    assert game.db.debug.plans.window.config[1] == 77 and game.db.debug.plans.window.enumerate == "function"


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
    note = next(w for w in game.fake.widgets.values() if w.kind == "EditBox" and w.IsVisible(w))
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
    note = next(w for w in game.fake.widgets.values() if w.kind == "EditBox" and w.IsVisible(w))
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


# ---- New raids made in game (officers) ----

def officer(**changes):
    """API, as an officer of the guild sees it."""
    return {**API, "guilds": [{**API["guilds"][0], "officer": True, **changes}]}


def local_start(days, hour, minute):
    """A day from NOW (0: that day) at a time of day, in this PC's own time, as the addon works it out."""
    import time as clock
    today = clock.localtime(NOW)
    return int(clock.mktime((today.tm_year, today.tm_mon, today.tm_mday + days, hour, minute, 0, 0, 0, -1)))


def first_day():
    """What the New raid form's Day shows when it opens: today, unless 20:00 has passed."""
    return "Today" if local_start(0, 20, 0) > NOW else "Tomorrow"


def made(game):
    return [dict(r.items()) for r in game.db.newRaids.values()]


def test_officers_make_raids_in_game():
    game = Game(sync_lua(officer(), {}))
    game.slash()
    game.click("New raid")
    assert "New raid" in game.texts() and game.fake.button("Coming") is None  # (the form, in place of the raid)
    game.type_in(0, "  Zul'Gurub  ")
    game.type_in(1, "Bring |cffff0000 nature resist")
    game.choose_in(first_day(), "Tomorrow")
    game.choose_in("20", "21")
    game.choose_in("00", "30")
    game.choose_in("Not set", "20 players")
    assert "your time  ·  Knights of Forever  ·  20 players" in game.texts()
    game.click("Make raid")
    (raid,) = made(game)
    assert (raid["guild"], raid["title"], raid["size"], raid["at"]) == (5, "Zul'Gurub", 20, NOW)
    assert raid["start"] == local_start(1, 21, 30) and raid["notes"] == "Bring |cffff0000 nature resist"
    assert raid["id"].startswith("r")
    # It's in the list, waiting to sync, and open: no signing up until the website has it.
    text = game.texts()
    assert "Zul'Gurub" in text and "Waiting to sync" in text and "Made in game. It goes to the website" in text
    assert "Bring ||cffff0000 nature resist" in text  # (shown as typed)
    assert game.fake.button("Coming") is None and game.fake.button("Don't make it") is not None
    assert "Waiting to sync: 1 new raid. Reload or log out to send." in text
    assert "new raid saved. With the Gargoyle app running, click Reload UI" in game.printed()
    # Changed your mind before reloading: take it back.
    game.click("Don't make it")
    assert made(game) == [] and "Zul'Gurub" not in game.texts() and "Molten Core" in game.texts()


def test_new_raid_problems():
    game = Game(sync_lua(officer(), {}))
    game.slash()
    game.click("New raid")
    game.click("Make raid")
    assert "Give the raid a name." in game.texts() and made(game) == []
    game.type_in(0, "MC")
    game.choose_in(first_day(), "Today")
    game.choose_in("20", "00")
    game.click("Make raid")  # (midnight today has passed)
    assert "Pick a time that hasn't passed yet." in game.texts() and made(game) == []
    game.click("Cancel")
    assert "Bring fire resist" in game.texts()
    # Not an officer: no button.
    member = Game(sync_lua(API, {}))
    member.slash()
    assert member.fake.button("New raid") is None
    # An app from before raids could be made in game: says to update it.
    old = Game(sync_lua(officer(), {}).replace("can_make_raids", "something_else"))
    old.slash()
    old.click("New raid")
    assert "making raids in game needs the newest Gargoyle app" in old.printed() and "Make raid" not in old.texts()


def test_made_raids_after_a_sync():
    start = NOW + 3 * 86400
    saved = f"""GargoyleDB = {{ newRaids = {{
      {{ id = "ra", guild = 5, title = "Onyxia", start = {start}, at = {NOW - 60} }},
      {{ id = "rb", guild = 5, title = "AQ40", start = {start}, size = 40, at = {NOW - 50} }},
      {{ id = "rc", guild = 5, title = "Naxx", start = {start + 3600}, notes = "", at = {NOW - 40} }},
      {{ id = "rd", guild = 5, title = "Gone by", start = {NOW - 10}, at = {NOW - 9000} }},
      {{ id = 7, guild = "x" }},
    }} }}"""
    onyxia = {"id": 9, "title": "Onyxia", "start": start, "size": None, "notes": "", "signups": []}
    api = officer(raids=API["guilds"][0]["raids"] + [onyxia])
    game = Game(sync_lua(api, {"ra": "saved", "rb": "full"}), saved)
    assert [r["id"] for r in made(game)] == ["rc"]  # the started and the odd ones dropped too
    assert "your new raid AQ40 wasn't made: the guild has as many upcoming raids as it can have." in game.printed()
    assert game.db.alerts.seen[9] == start  # (you made it: not a "new raid" to tell you about)
    in_game(game)
    assert "Onyxia" not in game.lua.globals().GargoyleMinimapBubble.detail.text
    game.slash()
    assert "Naxx" in game.texts() and "Waiting to sync: 1 new raid" in game.texts()
    naxx = next(w for w in game.fake.widgets.values() if w.kind == "Button" and w.raid and w.raid.title == "Naxx")
    naxx.scripts.OnClick(naxx)
    assert game.fake.button("Don't make it") is None  # (made before the reload: the app may have sent it)


# ---- Raids on the game's calendar ----

def calendar_day(game, when):
    """The game's calendar opened on the month of `when` (seconds), and that day's button."""
    import time as clock
    day = clock.localtime(when)
    game.fake.openCalendar(day.tm_year, day.tm_mon)
    lua = game.lua.globals()
    buttons = [lua["CalendarDayButton%d" % i] for i in range(1, 43)]
    return next(b for b in buttons if b.day == day.tm_mday and b.monthOffset == 0)


def mark_on(game, button):
    find = game.lua.eval("function(b) for _, w in ipairs(fake.widgets) do if w.parent == b and w.kind == 'Button' then return w end end end")
    return find(button)


def test_raids_are_marked_on_the_game_calendar():
    game = Game(sync_lua(API, {}))
    mark = mark_on(game, calendar_day(game, NOW + 86400))
    assert mark.shown and mark.count.text == ""
    mark.scripts.OnEnter(mark)
    lines = list(game.lua.globals().GameTooltip.lines.values())
    assert lines[0] == "Gargoyle" and lines[1] == "Molten Core"
    assert "Knights of Forever" in lines[2] and "Tentative" in lines[2] and lines[-1] == "Click to open it in Gargoyle."
    # A click opens Gargoyle on that raid.
    bwl = mark_on(game, calendar_day(game, NOW + 7 * 86400))
    bwl.scripts.OnClick(bwl)
    assert game.lua.globals().GargoyleWindow.shown and "|cff19ff19New|r  Blackwing Lair" in game.texts()
    assert "No one is coming yet." in game.texts()  # (Blackwing Lair's details, not Molten Core's)
    # Days without raids have no mark.
    other = mark_on(game, calendar_day(game, NOW + 3 * 86400))
    assert other is None or not other.shown
    # Two raids on one day: a count.
    api = {**API, "guilds": [{**API["guilds"][0], "raids": API["guilds"][0]["raids"] + [
        {"id": 4, "title": "Onyxia", "start": NOW + 86400 + 60, "size": 40, "notes": "", "signups": []}]}]}
    two = Game(sync_lua(api, {}))
    mark = mark_on(two, calendar_day(two, NOW + 86400))
    assert mark.count.text == "2" and len(mark.raids) == 2


def test_calendar_marks_can_be_turned_off_and_follow_new_raids():
    game = Game(sync_lua(officer(), {}))
    button = calendar_day(game, NOW + 86400)
    box = game.ns.calendarBox
    assert box.checked
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert game.db.calendar is False and not mark_on(game, button).shown
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    assert game.db.calendar is None and mark_on(game, button).shown
    # The raid feature off: no marks.
    raids = game.ns.optionBoxes.raids
    raids.SetChecked(raids, False)
    raids.scripts.OnClick(raids)
    assert not mark_on(game, button).shown
    raids.SetChecked(raids, True)
    raids.scripts.OnClick(raids)
    # A raid made in game is marked straight away.
    day = calendar_day(game, local_start(2, 20, 0))
    assert mark_on(game, day) is None
    game.slash()
    game.click("New raid")
    game.type_in(0, "Ruins of Ahn'Qiraj")
    game.choose_in(first_day(), game.lua.eval("os.date('%a %d %b', " + str(local_start(2, 12, 0)) + ")"))
    game.click("Make raid")
    mark = mark_on(game, day)
    assert mark.shown
    mark.scripts.OnEnter(mark)
    assert "Waiting to sync" in list(game.lua.globals().GameTooltip.lines.values())[2]


def test_the_calendar_loaded_before_gargoyle():
    game = Game(sync_lua(API, {}), "fake.openCalendar(2027, 1)")
    assert mark_on(game, calendar_day(game, NOW + 86400)).shown


# ---- Talent plans ----

PLAN = [  # a build saved on the website, as /api/app/sync sends its talents
    {"tree": 1, "name": "Arcane Subtlety", "spells": [11210], "rank": 2},  # (the game has 2: done)
    {"tree": 1, "name": "Arcane Focus", "spells": [11222], "rank": 3},  # found by its spell
    {"tree": 2, "name": "Improved Fireball", "spells": [1], "rank": 5},  # by its name, in its own tree
    {"tree": 3, "name": "Improved Frostbolt", "spells": [11070], "rank": 2},  # the game has 5: more than planned
    {"tree": 1, "name": "Not In The Game", "spells": [5], "rank": 1},
]
PLANS_API = {**API, "characters": API["characters"] + [
    {"id": 14, "name": "Fire build", "class": "mage", "guild": None, "role": None, "talents": PLAN},
    {"id": 15, "name": "Kept up to date", "class": "mage", "guild": None, "role": None, "game": "Player-1-00ABCDEF",
     "talents": PLAN},  # (this character itself: its talents are the game's)
    {"id": 16, "name": "Warlock build", "class": "warlock", "guild": None, "role": None, "talents": PLAN},
    {"id": 17, "name": "No talents", "class": "mage", "guild": None, "role": None, "talents": []},
]}
# The same name in another tree: the plan's Improved Fireball is the one in its own tree.
SAME_NAME = 'table.insert(fake.char.talents[1], { "Improved Fireball", 3, 1, 0, 5, 7777 })'
CHOSEN = 'GargoyleDB = { talentPlans = { ["Player-1-00ABCDEF#1"] = 14 } }'


def talent_marks(game):
    """Gargoyle's marks on the talent window: talent (node id) -> (state, planned points)."""
    return {w.over.nodeID: (w.state, w.want.text) for w in game.fake.widgets.values()
            if w.kind == "Frame" and w.state and w.over and w.IsVisible(w)}


def on_the_bar(game, kind):
    """Gargoyle's widgets of that kind on its bar on the talent window."""
    find = game.lua.eval("""function(kind)
      local found = {}
      for _, w in ipairs(fake.widgets) do
        if w.kind == kind and w.parent and w.parent.parent == PlayerSpellsFrame.TalentsFrame then table.insert(found, w) end
      end
      return found
    end""")
    return list(find(kind).values())


def plan_menu(game):
    """What the talent window's plan picker offers, and what it shows."""
    (menu,) = on_the_bar(game, "DropdownButton")
    menu.GenerateMenu(menu)
    return [r.text for r in menu.radios.values()], menu.text


def bar_text(game):
    (status,) = [w for w in on_the_bar(game, "FontString") if w.text != "Talent plan"]
    return status.text if status.IsVisible(status) else None


def test_a_talent_plan_marks_the_talent_window():
    game = Game(sync_lua(PLANS_API, {}), SAME_NAME)
    game.fake.openTalents()
    assert plan_menu(game) == (["No plan", "Fire build"], "No plan") and talent_marks(game) == {}
    assert bar_text(game) == "Pick one of your Gargoyle characters to follow its talents."
    game.choose_in("No plan", "Fire build")
    assert game.db.talentPlans["Player-1-00ABCDEF#1"] == 14
    # No points to spend: marked, not glowing. Arcane Subtlety is done; Frostbolt has too many.
    assert talent_marks(game) == {1002: ("later", "|cffffffff3|r"), 2001: ("later", "|cffffffff5|r"),
                                  3001: ("over", "|cffff50502|r")}
    assert bar_text(game) == "4 of 12 planned points spent  ·  |cffe05050" "1 with more points than the plan|r"
    # A point to spend: the talents it can go in glow, until the plan's points are in.
    game.lua.execute("fake.char.unspent = 1")
    game.fake.redrawTalents()
    assert talent_marks(game)[1002][0] == "now" and talent_marks(game)[2001][0] == "now"
    assert "glowing: a point can go in now" in bar_text(game)
    game.lua.execute("fake.char.talents[1][2][4] = 3; fake.char.talents[2][1][7] = true")  # (and Fireball locked)
    game.fake.redrawTalents()
    assert talent_marks(game) == {2001: ("later", "|cffffffff5|r"), 3001: ("over", "|cffff50502|r")}
    game.lua.execute("fake.char.talents[2][1][4] = 5; fake.char.talents[3][1][4] = 2")
    game.fake.redrawTalents()
    assert talent_marks(game) == {} and bar_text(game) == "|cff40c040Plan done|r"
    # Back to no plan: no marks.
    game.choose_in("Fire build", "No plan")
    assert talent_marks(game) == {} and game.db.talentPlans["Player-1-00ABCDEF#1"] is None


def test_the_talent_plans_tab():
    game = Game(sync_lua(PLANS_API, {}), SAME_NAME)
    game.slash()
    game.click("Talent plans")
    assert "Pick one of your Gargoyle characters to follow its talents." in game.texts()
    game.choose_in("No plan", "Fire build")
    text = game.texts()
    assert "Follow the talents of" in text and "4 of 12 planned points spent" in text
    assert "|cffffffffArcane Focus|r  |cffb0b0b00/3|r\n|cffffffffImproved Fireball|r  |cffb0b0b00/5|r" in text
    assert "|cffe05050Improved Frostbolt|r  |cffb0b0b05/2|r\n|cffb0b0b0Not In The Game (not in the game's talents)|r" in text
    # Picked here, it's picked on the talent window too.
    game.fake.openTalents()
    assert plan_menu(game)[1] == "Fire build" and len(talent_marks(game)) == 3


def test_a_plan_for_each_character_and_set_of_talents_kept_after_a_reload():
    game = Game(sync_lua(PLANS_API, {}), CHOSEN)
    game.fake.openTalents()
    assert len(talent_marks(game)) == 3
    # The second set of talents (dual spec) has its own plan: none yet.
    game.lua.execute('C_SpecializationInfo.GetActiveSpecGroup = function() return 2 end')
    game.lua.globals().fake.fire("ACTIVE_TALENT_GROUP_CHANGED")
    assert talent_marks(game) == {} and plan_menu(game)[1] == "No plan"
    # Another character on the same game account: none either.
    other = Game(sync_lua(PLANS_API, {}), CHOSEN + '; fake.char.guid = "Player-1-00000002"')
    other.fake.openTalents()
    assert talent_marks(other) == {}


def test_talent_marks_only_on_the_talents_in_use_and_when_turned_on():
    game = Game(sync_lua(PLANS_API, {}), CHOSEN)
    game.fake.openTalents()
    game.lua.execute("fake.talentFrameConfig = 78")  # the other set of talents, shown locked
    game.fake.redrawTalents()
    assert talent_marks(game) == {}
    game.lua.execute("fake.talentFrameConfig = nil")
    game.ns.SetEnabled("talents", False)
    assert talent_marks(game) == {} and bar_text(game) is None
    game.ns.SetEnabled("talents", True)
    assert len(talent_marks(game)) == 3
    # In combat nothing is redrawn (talents can't change then), until it ends.
    game.lua.execute("fake.combat = true; fake.char.talents[1][2][4] = 3")
    game.fake.redrawTalents()
    assert len(talent_marks(game)) == 3
    game.lua.execute("fake.combat = false")
    game.fake.fire("PLAYER_REGEN_ENABLED")
    assert len(talent_marks(game)) == 2


def test_the_talent_window_loaded_before_gargoyle():
    game = Game(sync_lua(PLANS_API, {}), CHOSEN + "; fake.openTalents()")
    assert len(talent_marks(game)) == 3


def test_talent_plans_without_data_or_with_an_older_app():
    game = Game()
    game.fake.openTalents()
    assert bar_text(game) == "No data from the Gargoyle app yet." and plan_menu(game)[0] == ["No plan"]
    old_app = sync_lua(PLANS_API, {}).replace("sends_talents = true,", "")
    assert old_app != sync_lua(PLANS_API, {})
    game = Game(old_app)
    game.fake.openTalents()
    assert bar_text(game) == "Update the Gargoyle app to follow talent plans."
    junk = ('GargoyleSync = { version = 1, sends_talents = true, characters = {'
            ' { id = 1, name = "A", class = "mage", talents = "junk" },'
            ' { id = 2, name = "B", class = "mage", talents = { 5, { tree = "x", name = 1, rank = 99 }, { tree = 1, name = "Arcane Focus", rank = 0 } } },'
            ' { id = 3, name = "C", class = "mage", talents = { { tree = 1, name = "Arcane Focus", rank = 2, spells = "x" } } } } }')
    game = Game(junk, 'GargoyleDB = { talentPlans = { ["Player-1-00ABCDEF#1"] = 3 } }')
    game.fake.openTalents()
    assert plan_menu(game) == (["No plan", "C"], "C")
    # (and the talents with points the plan doesn't have: none planned)
    assert talent_marks(game) == {1002: ("later", "|cffffffff2|r"), 1001: ("over", "|cffff50500|r"),
                                  3001: ("over", "|cffff50500|r")}


def test_plan_talents_are_found_by_spell_then_name_in_their_tree_then_name():
    game = Game()
    match = game.lua.eval("""function(ns)
      local nodes = { { id = 1, tab = 1, name = "Focus", spell = 10, max = 5 }, { id = 2, tab = 2, name = "Focus", spell = 20, max = 5 },
                      { id = 3, tab = 3, name = "Other", spell = 30, max = 3 } }
      local plan = { talents = { { tree = 2, name = "focus", spells = { 99 }, rank = 2 }, { tree = 3, name = "Focus", spells = {}, rank = 1 },
                                 { tree = 1, name = "x", spells = { 30 }, rank = 9 }, { tree = 1, name = "Gone", spells = {}, rank = 1 } } }
      local wanted, missing = ns.Talents.Match(plan, nodes)
      return wanted[1], wanted[2], wanted[3], #missing, missing[1].name
    end""")
    assert match(game.ns) == (1, 2, 3, 1, "Gone")


# ---- Gargoyle Damage Tooltips (addon/Gargoyle_Tooltips) ----

def tooltip_game(**kw):
    game = Game(tooltips=True, **kw)
    game.lua.execute("""
        fake.char.talents = { { { "Arcane Instability", 1, 1, 3, 3, 15058 } }, {},
                              { { "Piercing Ice", 1, 1, 3, 3, 11151 }, { "Ice Shards", 1, 2, 5, 5, 11207 } } }
        fake.stats.spellDamage[5] = 200   -- (Frost)
        fake.stats.spellCrit = 10
        fake.castTimes[116], fake.costs[116] = 1500, 25
    """)
    return game


def test_frostbolt_breakdown():
    game = tooltip_game()
    text = game.fake.spellTooltip(116)  # Frostbolt rank 1: 20 to 22, 40.7% of spell damage
    # (20 + 81.4) x 1.06 Piercing Ice x 1.03 Arcane Instability; crits do 200% with Ice Shards.
    assert text.splitlines() == [
        "A spell", " ", "Direct damage · Frost",
        "Base | 20 – 22",
        "Spell damage 200 × 40.7% | +81",
        "Talents | × 1.09",
        "  Arcane Instability +3%, Piercing Ice +6%",
        "Total damage | 111 – 113",
        "Crit 10% for 200% | avg 123",
        "Average damage per cast | 123",
        "Per second of casting (1.5 sec) | 82",
        "Per mana (25 mana) | 4.92",
    ]


def test_talents_are_read_again_after_they_change():
    game = tooltip_game()
    assert "Piercing Ice" in game.fake.spellTooltip(116)
    game.lua.execute("fake.char.talents[3] = {}")
    assert "Piercing Ice" in game.fake.spellTooltip(116)  # (until the game says they changed)
    game.fake.fire("TRAIT_CONFIG_UPDATED")
    text = game.fake.spellTooltip(116)
    assert "Piercing Ice" not in text and "Crit 10% for 150% | avg 111" in text


def test_spells_without_a_breakdown_and_secret_numbers_add_nothing():
    game = tooltip_game()
    assert game.fake.spellTooltip(1) == "A spell"  # (not a spell it knows)
    game.lua.execute("issecretvalue = function(v) return v == 116 end")
    assert game.fake.spellTooltip(116) == "A spell"
    game.lua.execute("issecretvalue = function() return false end; GetSpellBonusDamage = function() error('boom') end")
    assert game.fake.spellTooltip(116) == "A spell"  # (a problem adds nothing, half or otherwise)


def test_turned_on_and_off_in_gargoyles_options():
    game = tooltip_game()
    box = game.ns.tooltipsBox
    assert box.enabled and box.GetChecked(box)
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert game.lua.globals().GargoyleTooltipsDB.on is False
    assert game.fake.spellTooltip(116) == "A spell"
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    assert "Average damage per cast" in game.fake.spellTooltip(116)


def test_switched_off_stays_off_after_a_reload():
    game = tooltip_game(saved="GargoyleTooltipsDB = { on = false }")
    assert not game.ns.tooltipsBox.GetChecked(game.ns.tooltipsBox)
    assert game.fake.spellTooltip(116) == "A spell"


def test_gargoyle_without_damage_tooltips_says_how_to_get_them():
    game = Game()
    box = game.ns.tooltipsBox
    assert not box.enabled and not box.GetChecked(box)
    assert "Damage tooltips aren't loaded (install them from the Gargoyle app's Settings" in game.texts()


def test_only_your_own_classs_data_is_kept():
    game = tooltip_game()
    data = game.tips_ns.data
    assert data.MAGE is not None and data.WARLOCK is None and data.PRIEST is None


@pytest.mark.parametrize("token", ["DRUID", "HUNTER", "MAGE", "PALADIN", "PRIEST", "ROGUE", "SHAMAN", "WARLOCK", "WARRIOR"])
def test_every_spell_of_every_class_has_a_breakdown(token):
    game = Game(tooltips=False)
    game.lua.execute("""
        UnitClass = function() return "X", "%s", 1 end
        fake.stats = { spellDamage = { 300, 300, 300, 300, 300, 300, 300 }, healing = 500, spellCrit = 8, crit = 12,
                       ap = 1200, weapon = { 150, 250 } }
    """ % token)
    tips = game.lua.table()
    run = game.lua.eval('function(src, name, ns) local f = assert(loadstring(src, "@" .. name)); f("Gargoyle_Tooltips", ns) end')
    for name in (line.strip() for line in (TOOLTIPS / "Gargoyle_Tooltips.toc").read_text(encoding="utf-8").splitlines()):
        if name and not name.startswith("#"):
            run((TOOLTIPS / name.replace("\\\\", "/").replace("\\", "/")).read_text(encoding="utf-8"), name, tips)
    lines = game.lua.eval("function(id) local ok, lines = pcall(GargoyleTooltips.Lines, id); assert(ok, lines); return lines end")
    spells = getattr(tips.data, token).spells
    assert len(list(spells.keys())) > 10
    for spell_id in spells.keys():
        result = lines(spell_id)
        assert result is not None, spell_id
        rows = [r[1] for r in result.values()]
        assert any(r.startswith("Average") for r in rows), (spell_id, rows)


# ---- The dungeon journal (Modules/Journal.lua) ----

JOURNAL = """
local _, ns = ...
ns.JOURNAL_MAPS = {
  { id = 1414, name = "Kalimdor", crop = { 318, 0, 690, 668 } },
  { id = 1415, name = "Eastern Kingdoms", crop = { 300, 0, 672, 668 } },
}
ns.JOURNAL = {
  { id = 36, name = "Deadmines", kind = "dungeon", size = 5, min = 17, max = 26, zone = "Westfall",
    pin = { map = 1415, x = 28.9, y = 79.6 },
    bosses = {
      { name = "Rhahk'Zor", loot = { { 872, 20 }, { 5187, 80 } }, abilities = { { 6304, "Rhahk'Zor Slam" } } },
      { name = "Edwin VanCleef", loot = { { 5193, 15 }, { 5191, 15 }, { 10399 } }, abilities = {} },
    },
    other = { { 1156, 1.5 } },
    quests = {
      { id = 166, title = "The Defias Brotherhood", level = 22, min = 14, side = "Alliance", type = "Dungeon",
        obj = "Kill Edwin VanCleef and bring his head to Gryan Stoutmantle.",
        start = { kind = "npc", name = "Gryan Stoutmantle", map = 1436, x = 56.3, y = 47.5, zone = "Westfall" },
        rewards = { 6087, 2041 },
        chain = {
          { id = 65, title = "The Defias Brotherhood", level = 18,
            start = { kind = "npc", name = "Gryan Stoutmantle", map = 1436, x = 56.3, y = 47.5, zone = "Westfall" } },
          { id = 132, title = "The Defias Brotherhood", level = 18,
            start = { kind = "npc", name = "Wiley the Black", map = 1433, x = 21.4, y = 45.3, zone = "Redridge Mountains" } },
        } },
      { id = 373, title = "The Unsent Letter", level = 22, side = "Alliance",
        start = { kind = "item", name = "An Unsent Letter", drop = "Edwin VanCleef, Deadmines" }, rewards = {}, chain = {} },
      { id = 2040, title = "Underground Assault", level = 20, side = "Horde",
        start = { kind = "npc", name = "Shoni the Shilent", map = 1453, x = 55, y = 12, zone = "Orgrimmar" }, rewards = {}, chain = {} },
    },
  },
  { id = 33, name = "Shadowfang Keep", kind = "dungeon", size = 5, min = 20, max = 30, zone = "Silverpine Forest",
    pin = { map = 1415, x = 29.8, y = 32.8 },
    bosses = { { name = "Archmage Arugal", loot = { { 6392, 10 } }, abilities = {} } }, other = {} },
  { name = "Alcaz Prison", kind = "dungeon", size = 5, min = 48, max = 53, zone = "Dustwallow Marsh", new = true,
    when = "Coming at launch", expected = true, pin = { map = 1414, x = 75.6, y = 62.4 }, bosses = {}, other = {} },
  { name = "Hyjal Summit", kind = "raid", size = 20, min = 60, max = 60, zone = "Mount Hyjal", new = true, bossCount = 13,
    when = "Opens December 9", pin = { map = 1414, x = 58.9, y = 31.2, zone = true }, bosses = {}, other = {} },
  { id = 409, name = "Molten Core", kind = "raid", size = 40, min = 60, max = 60, when = "Not yet released", later = true,
    bosses = {}, other = {} },
}
"""
# The game's world map art: 4x3 tiles of 256 for each continent (what the world map draws with).
MAP_ART = """C_Map.GetMapArtLayers = function(map)
  return { { layerWidth = 1002, layerHeight = 668, tileWidth = 256, tileHeight = 256, minScale = 1, maxScale = 1 } }
end
C_Map.GetMapArtLayerTextures = function(map, layer)
  local t = {}
  for i = 1, 12 do t[i] = map * 100 + i end
  return t
end
"""
ITEMS = """fake.items = { [872] = { "Rockslicer", 3, 135321 }, [5187] = { "Rhahk'Zor's Hammer", 2, 1 },
  [5193] = { "Cape of the Brotherhood", 3, 1 }, [5191] = { "Cruel Barb", 3, 1 }, [10399] = { "Blackened Defias Armor", 3, 1 },
  [1156] = { "Lavishly Jeweled Ring", 3, 1 }, [6392] = { "Belt of Arugal", 3, 1 }, [6087] = { "Chausses of Westfall", 2, 1 },
  [2041] = { "Tunic of Westfall", 2, 1 } }
fake.spellText[6304] = "Stuns an enemy for 3 sec." """
PICKS = {"items": [[10399, 40, 9], [872, 12.4, 3.1], [6392, 5, 1.2], [2041, 7, 2]], "spec": "Fire", "level": 60,
         "stale": False, "at": NOW - 100}
# Jainamage is kept up to date from the character being played; Jainalt has no picks yet.
JOURNAL_API = {**API, "characters": [{**API["characters"][0], "game": "Player-1-00ABCDEF", "upgrades": PICKS},
                                     API["characters"][1]]}


def journal_game(api=JOURNAL_API, before="", saved=None, **kwargs):
    game = Game(sync_lua(api, {}) if api is not None else None, saved, journal=JOURNAL, before=ITEMS + "\n" + before, **kwargs)
    game.slash()
    game.click("Dungeons")
    return game


def click_row(game, text):
    """Clicks the list row (a button) showing `text`."""
    for w in game.fake.widgets.values():
        if w.kind == "FontString" and text in w.text and w.IsVisible(w) and w.parent.kind == "Button":
            w.parent.scripts["OnClick"](w.parent)
            return
    raise AssertionError(f"no row shows {text!r}")


def view_button(game, starts):
    return next(w for w in game.fake.widgets.values() if w.kind == "Button" and w.text.startswith(starts) and w.IsVisible(w))


def test_the_bosses_view_lists_bosses_and_shows_their_loot_and_abilities():
    game = journal_game()
    text = game.texts()
    assert "Deadmines" in text and "Level 17-26  ·  5 players  ·  Dungeon  ·  Westfall" in text
    assert "1. Rhahk'Zor" in text and "2. Edwin VanCleef" in text and "Other drops" in text
    assert "Rockslicer" in text and "20%" in text and "Rhahk'Zor's Hammer" in text
    assert "Molten Core" in text and "Raid" in text
    click_row(game, "2. Edwin VanCleef")
    text = game.texts()
    assert "Cruel Barb" in text and "Rockslicer" not in text
    click_row(game, "Other drops")
    assert "Lavishly Jeweled Ring" in game.texts() and "1.5%" in game.texts()
    click_row(game, "1. Rhahk'Zor")
    game.click("Abilities")
    text = game.texts()
    assert "Rhahk'Zor Slam" in text and "Stuns an enemy for 3 sec." in text and "Rockslicer" not in text
    assert game.db.journal.part == "abilities"
    game.click("Loot")
    assert "Rockslicer" in game.texts()


def test_upgrades_are_marked_for_the_character_you_play():
    game = journal_game()
    text = game.texts()
    assert "+12 (3.1%)" in text  # Rockslicer
    # Deadmines: two drops and a quest reward.
    assert "3 upgrades|r here for Jainamage (Fire, level 60). Best: Blackened Defias Armor +40 (9.0%)." in text
    marks = [w.text for w in game.fake.widgets.values() if w.kind == "FontString" and w.IsVisible(w) and w.text.startswith("|cff3fd35c+")]
    assert "|cff3fd35c+3|r" in marks and "|cff3fd35c+1|r" in marks  # (the place list: Deadmines, Shadowfang Keep)
    game.lua.execute("fake.worn[10399] = true")  # put it on: no longer an upgrade
    click_row(game, "1. Rhahk'Zor")
    assert "2 upgrades|r here for Jainamage" in game.texts()


def map_pins(game):
    """{place name: its pin} on the Map view."""
    places = game.ns.JOURNAL
    return {places[w.index].name: w for w in game.fake.widgets.values() if w.kind == "Button" and w.glow and w.index}


def test_the_map_view_shows_the_games_maps_with_a_pin_on_each_entrance():
    game = journal_game(before=MAP_ART)
    game.click("Map")
    assert game.db.journal.view == "map"
    # The game's own art: each continent's 12 tiles (no pictures of our own).
    tiles = {w.texture for w in game.fake.widgets.values() if w.kind == "Texture" and isinstance(w.texture, int)}
    assert {141400 + i for i in range(1, 13)} <= tiles and {141500 + i for i in range(1, 13)} <= tiles
    pins = map_pins(game)
    assert set(pins) == {"Deadmines", "Shadowfang Keep", "Alcaz Prison", "Hyjal Summit"}  # (Molten Core: not released)
    assert pins["Deadmines"].glow.shown and not pins["Shadowfang Keep"].glow.shown  # (the one picked)
    assert pins["Deadmines"].up.shown and not pins["Alcaz Prison"].up.shown  # (upgrades for Jainamage)
    text = game.texts()
    assert "Deadmines" in text and "Not on the map yet" not in text and "Raids not released yet aren't on the map." in text
    # Pointing at a pin names the place.
    pin = pins["Hyjal Summit"]
    pin.scripts["OnEnter"](pin)
    lines = list(game.lua.globals().GameTooltip.lines.values())
    assert lines[0] == "Hyjal Summit" and "somewhere in Mount Hyjal" in lines[1] and "20 players  ·  13 bosses" in lines
    assert "Opens December 9" in lines and lines[-1] == "Click to open it."
    # Pointing at a place in the list lights its pin and shows it beside the map.
    row = next(w.parent for w in game.fake.widgets.values() if w.kind == "FontString" and w.text == "Shadowfang Keep"
               and w.parent.kind == "Button" and w.IsVisible(w))
    row.scripts["OnEnter"](row)
    assert pins["Shadowfang Keep"].glow.shown and "Level 20-30" in game.texts()
    row.scripts["OnLeave"](row)
    assert not pins["Shadowfang Keep"].glow.shown
    # Clicking a pin opens the place.
    pin = pins["Alcaz Prison"]
    pin.scripts["OnClick"](pin)
    text = game.texts()
    assert game.db.journal.view == "bosses" and game.db.journal.place == "Alcaz Prison"
    assert "Level 48-53 (expected)" in text and "Coming at launch" in text and "Its bosses aren't known yet." in text


def test_not_yet_released_raids_and_a_game_without_the_map_art():
    game = journal_game()  # (no map art from the game)
    text = game.texts()
    assert "Not yet" in text  # Molten Core in the list
    click_row(game, "Molten Core")
    assert "Not yet released" in game.texts()
    game.click("Map")
    assert "The game didn't give its map pictures" in game.texts() and len(map_pins(game)) == 4
    game.lua.execute('GargoyleDB.journal.view = "map"')  # (saved by 0.8.0, when it was taken out: fine now)
    game.ns.Journal.Refresh(game.ns.Journal)
    assert "Raids not released yet aren't on the map." in game.texts()


def test_the_quests_view_shows_how_to_get_each_quest_and_its_chain():
    game = journal_game(before="fake.questsDone[65] = true")
    view_button(game, "Quests (2)").Click(view_button(game, "Quests (2)"))  # (the Horde quest isn't for a Human)
    text = game.texts()
    assert "The Defias Brotherhood" in text and "Underground Assault" not in text
    assert "Level 22 (from 14)  ·  Alliance  ·  Dungeon" in text
    assert "Get it from |rGryan Stoutmantle, Westfall (56.3, 47.5)" in text
    assert "Kill Edwin VanCleef and bring his head to Gryan Stoutmantle." in text and "Chain (3 quests)" in text
    lines = [w.text for w in game.fake.widgets.values() if w.kind == "FontString" and w.IsVisible(w) and ". The Defias" in w.text]
    assert lines[0].startswith("|A:UI-LFG-ReadyMark") and "1. The Defias Brotherhood" in lines[0]  # done
    assert "|cffffd100>|r |cffffd1002. The Defias Brotherhood|r" in lines[1] and "Wiley the Black, Redridge Mountains" in lines[1]
    assert "(this quest)" in lines[2]
    rewards = [w for w in game.fake.widgets.values() if w.kind == "Button" and w.IsVisible(w) and w.itemID in (6087, 2041)]
    assert len(rewards) == 2 and [r.upgrade.shown for r in sorted(rewards, key=lambda r: r.itemID)] == [True, False]
    click_row(game, "The Unsent Letter")
    assert "Starts from |ran item, An Unsent Letter, which drops from Edwin VanCleef, Deadmines" in game.texts()
    assert not game.fake.button("Show on map").enabled  # (nowhere to pin)


def test_show_on_map_pins_the_next_step_only_when_clicked():
    game = journal_game(before="fake.questsDone[65] = true")
    view_button(game, "Quests").Click(view_button(game, "Quests"))
    assert list(game.fake.pins.values()) == []  # (never on its own)
    game.click("Show next step on map")
    (pin,) = game.fake.pins.values()
    assert (pin.uiMapID, round(pin.x, 3), round(pin.y, 3)) == (1433, 0.214, 0.453) and game.fake.tracking is True
    assert "map pin set: Wiley the Black, Redridge Mountains (21.4, 45.3)." in game.printed()


def test_the_view_part_and_character_are_kept():
    game = journal_game()
    game.choose_in("Jainamage", "Jainalt")
    assert "Jainalt's upgrades haven't been worked out yet: open it in the planner on the website" in game.texts()
    game.choose_in("Jainalt", "No one")
    assert "Pick one of your Gargoyle characters above" in game.texts()
    assert game.db.journal.chars["Player-1-00ABCDEF"] is False
    saved = ("GargoyleDB = { journal = { chars = { ['Player-1-00ABCDEF'] = 12 }, place = 33, view = 'bosses',"
             " part = 'loot' } }")
    game = journal_game(saved=saved)
    assert "Jainalt" in game.dropdowns() and "Shadowfang Keep" in game.texts() and "Belt of Arugal" in game.texts()
    game = journal_game(saved="GargoyleDB = { journal = { view = 7, part = {}, place = 'x' } }")  # (odd values)
    assert "1. Rhahk'Zor" in game.texts()


def test_out_of_date_upgrades_say_so():
    game = journal_game({**JOURNAL_API, "characters": [{**JOURNAL_API["characters"][0], "upgrades": {**PICKS, "stale": True}}]})
    assert "Jainamage has changed since: open it in the planner on the website to update." in game.texts()


def test_items_the_game_hasnt_loaded_show_when_they_arrive():
    game = journal_game(before="fake.uncached[872] = true")
    assert "Loading..." in game.texts() and "Rockslicer" not in game.texts()
    game.lua.execute("fake.loadItems()")
    game.fake.runTimers()
    assert "Rockslicer" in game.texts() and "Loading..." not in game.texts()


def test_the_journal_opens_on_the_dungeon_you_are_in():
    game = journal_game(before='fake.instance = { "Shadowfang Keep", "party", 1, "Normal", 5, 0, false, 33 }')
    assert "Belt of Arugal" in game.texts() and "(here)" in game.texts()
    game.lua.execute('fake.instance = { "Molten Core", "raid", 9, "40 Player", 40, 0, false, 409 }')
    game.fake.fire("PLAYER_ENTERING_WORLD")
    assert "Its bosses aren't known yet." in game.texts() and "Belt of Arugal" not in game.texts()
    game.lua.execute('fake.instance = { "Westfall", "none", 0, "", 5, 0, false, 0 }')
    game.fake.fire("ZONE_CHANGED_NEW_AREA")  # (leaving keeps what's shown)
    assert "(here)" not in game.texts() and "Its bosses aren't known yet." in game.texts()


def test_item_tooltips_say_when_an_item_is_an_upgrade():
    game = journal_game()
    assert "Gargoyle: upgrade for Jainamage, +12 (3.1%)" in game.fake.itemTooltip(872)
    assert "Gargoyle" not in game.fake.itemTooltip(5187)  # (not an upgrade)
    game.lua.execute("fake.worn[872] = true")
    assert "Gargoyle" not in game.fake.itemTooltip(872)
    game.lua.execute("fake.worn[872] = false")
    box = game.ns.optionBoxes.journal
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    assert "Gargoyle" not in game.fake.itemTooltip(872) and game.fake.button("Dungeons") is None


def test_the_journal_without_app_data_or_with_an_older_app():
    game = journal_game(api=None)
    assert "Upgrade marks come from your Gargoyle account" in game.texts() and "Rockslicer" in game.texts()
    old = sync_lua(JOURNAL_API, {}).replace("sends_upgrades = true,", "")
    assert old != sync_lua(JOURNAL_API, {})
    game = Game(old, journal=JOURNAL, before=ITEMS)
    game.slash()
    game.click("Dungeons")
    assert "Upgrade marks need the newest Gargoyle app" in game.texts()


def test_odd_upgrade_data_is_skipped():
    sync = """GargoyleSync = { version = 1, sends_upgrades = true, user = "Jaina", characters = {
      { id = 11, name = "Jainamage", class = "mage", game = "Player-1-00ABCDEF",
        upgrades = { items = { "x", { "a", 1 }, { 5187, 3 }, { 872 } }, spec = 5, level = "60" } } } }"""
    game = Game(sync, journal=JOURNAL, before=ITEMS)
    game.slash()
    game.click("Dungeons")
    text = game.texts()
    assert "+3.0 (0.0%)" in text and "1 upgrade|r here for Jainamage." in text


def test_the_real_journal_data_loads_and_scrolls():
    game = Game(sync_lua(API, {}))
    places = list(game.ns.JOURNAL.values())
    ids = [p.id for p in places if p.id is not None]
    assert len(places) > 20 and len(set(ids)) == len(ids) and len(ids) > 25
    game.slash()
    game.click("Dungeons")
    assert "Ragefire Chasm" in game.texts() and "Naxxramas" not in game.texts()
    wheel = [w for w in game.fake.widgets.values() if w.scripts["OnMouseWheel"] and w.IsVisible(w)][0]  # (the list)
    for _ in range(10):
        wheel.scripts["OnMouseWheel"](wheel, -1)
    assert "Naxxramas" in game.texts()
    journal = game.ns.Journal
    for i in range(1, len(places) + 1):  # (every view of every place draws)
        journal.PickPlace(i)
        for view in ("bosses", "quests", "map"):
            journal.ShowView(view)
    assert len(list(game.ns.JOURNAL_MAPS.values())) == 2


# ---- The data collector (addon/Gargoyle_Collector) ----

COLLECTOR_ITEMS = """fake.items = { [240056] = { "Fireleaf Circlet", 4, 1 }, [240052] = { "Fireleaf Bindings", 4, 2 },
  [234571] = { "Grand Marshal's Stave", 4, 3 }, [6948] = { "Hearthstone", 1, 4 }, [5187] = { "Whirlwind Axe", 2, 5 },
  [872] = { "Rockslicer", 3, 6 } }
fake.book = { 133, 116 }
fake.spellText = { [133] = "Hurls a fiery ball." }"""


def collector(**kw):
    kw.setdefault("before", COLLECTOR_ITEMS)
    return Game(collector=True, **kw)


def settle(game, rounds=200):
    """Lets the game run until the collector has nothing left to do (timers, a step at a time)."""
    for _ in range(rounds):
        if not list(game.fake.timers.values()):
            return
        game.fake.runTimers()
    raise AssertionError("still busy")


def collected(game):
    return game.lua.globals().GargoyleCollectorDB


def test_the_collector_notes_your_gear_spells_and_talents():
    game = collector()
    settle(game)
    db = collected(game)
    assert db.v == 1 and len(db.id) >= 10
    circlet = db["items"][240056]
    assert (circlet.name, circlet.quality, circlet.ilvl, circlet.required, circlet.slot) == ("Fireleaf Circlet", 4, 30, 25, "INVTYPE_CHEST")
    assert circlet.seen == NOW and circlet.build == 60001 and circlet.stats.ITEM_MOD_STAMINA_SHORT == 10
    lines = [(line.left, line.color) for line in circlet.lines.values()]
    # (the item's own colors are kept; red, which depends on who's looking, isn't)
    assert lines == [("Fireleaf Circlet", None), ("Equip: Restores 5 mana per 5 sec.", "green"), ("Requires Level 60", None),
                     ('"Shiny."', None)]
    assert sorted(db["items"].keys()) == [234571, 240052, 240056]
    fireball = db.spells[133]
    assert (fireball.name, fireball.rank, fireball.description, fireball["class"], fireball.gcd) == (
        "Fireball", "Rank 1", "Hurls a fiery ball.", "MAGE", 1500)
    assert db.spells[116].description is None
    tree = db.talents.MAGE
    assert tree.tree == 500 and len(tree.groups) == 3 and len(tree.nodes) == 4
    subtlety = [n for n in tree.nodes.values() if n.id == 1001][0]
    talent = subtlety.talents[1]
    assert (talent.name, talent.spell, talent.max, list(talent.ranks.values())) == (
        "Arcane Subtlety", 11210, 2, ["Rank 1 of talent 1001", "Rank 2 of talent 1001"])
    assert db.spells[11210].name == "Arcane Subtlety"  # (and the talents' spells)
    assert GargoyleCollectorSummary(game) == "3 items, 6 spells, a talent tree waiting to be sent with the Gargoyle app's Send collected data button."


def GargoyleCollectorSummary(game):
    return game.lua.eval("GargoyleCollector.Summary()")


def test_the_collector_only_asks_about_what_you_come_across():
    game = collector()
    settle(game)
    assert sorted(set(game.fake.asked.values())) == [234571, 240052, 240056]
    asked = len(game.fake.asked)
    # Bags, a vendor, a loot window and a hovered item: each read once.
    game.lua.execute("fake.bags[0] = { 6948 }; fake.merchant = { 5187 }; fake.loot = { 872 }")
    for event in ("BAG_UPDATE_DELAYED", "MERCHANT_SHOW", "LOOT_OPENED"):
        game.fake.fire(event)
    game.fake.itemTooltip(240056)  # (noted already: not read again)
    settle(game)
    db = collected(game)
    assert sorted(db["items"].keys()) == [872, 5187, 6948, 234571, 240052, 240056]
    assert len(game.fake.asked) == asked + 3
    for event in ("BAG_UPDATE_DELAYED", "MERCHANT_SHOW", "LOOT_OPENED", "PLAYER_EQUIPMENT_CHANGED"):
        game.fake.fire(event)
    settle(game)
    assert len(game.fake.asked) == asked + 3


def test_the_collector_waits_for_the_game_to_load_an_item():
    game = collector(before=COLLECTOR_ITEMS + "; fake.uncached[5187] = true")
    settle(game)
    game.lua.execute("fake.merchant = { 5187 }")
    game.fake.fire("MERCHANT_SHOW")
    settle(game)
    assert collected(game)["items"][5187] is None
    game.fake.loadItems()
    settle(game)
    assert collected(game)["items"][5187].name == "Whirlwind Axe"


def test_the_collector_reads_a_few_at_a_time_and_never_in_combat():
    game = collector(before=COLLECTOR_ITEMS + "; fake.combat = true")
    for _ in range(5):
        game.fake.runTimers()
    assert len(game.fake.asked) == 0
    game.lua.execute("fake.combat = false")
    game.fake.fire("PLAYER_REGEN_ENABLED")
    game.fake.runTimers()
    assert 0 < len(game.fake.asked) <= 6
    settle(game)
    assert collected(game)["items"][240056] is not None


def test_a_trainer_list_gives_levels_and_costs():
    game = collector()
    settle(game)
    game.lua.execute('fake.trainer = { { 10, "Blizzard", "Rank 1", 20, 1500 } }')
    game.fake.fire("TRAINER_SHOW")
    settle(game)
    db = collected(game)
    trained = db.trainers[10]
    assert (trained.name, trained.rank, trained.level, trained.cost, trained["class"]) == ("Blizzard", "Rank 1", 20, 1500, "MAGE")
    assert db.spells[10].name == "Blizzard"


def test_sent_data_is_cleared_and_not_noted_again_until_it_changes():
    game = collector()
    settle(game)
    db = collected(game)
    saved = "GargoyleCollectorDB = " + lua_table(game, db)
    # The app sent it all: at the next login it's gone, but isn't noted again.
    sync = 'GargoyleSync = { version = 1, collected = { ["%s"] = %d } }' % (db.id, NOW)
    game = collector(saved=saved + "\n" + sync, now=NOW + 100)
    settle(game)
    db = collected(game)
    assert list(db["items"].keys()) == [] and list(db.spells.keys()) == [] and db.talents.MAGE is None
    assert GargoyleCollectorSummary(game) == "Nothing new to send yet."
    # A new version of the game: looked at again, and only what changed is kept.
    saved = "GargoyleCollectorDB = " + lua_table(game, db)
    game = collector(saved=saved, now=NOW + 200, before=COLLECTOR_ITEMS + """
        fake.build = 60002
        fake.items[240056] = { "Fireleaf Circlet", 4, 1, flavor = "New in this patch." }""")
    settle(game)
    db = collected(game)
    assert list(db["items"].keys()) == [240056] and db["items"][240056].build == 60002 and list(db.spells.keys()) == []


def lua_table(game, value):
    """A Lua table written out as the game's saved files have it."""
    return game.lua.eval("""function(t)
      local function write(v)
        if type(v) == "table" then
          local parts = {}
          for k, x in pairs(v) do parts[#parts + 1] = "[" .. write(k) .. "] = " .. write(x) end
          return "{" .. table.concat(parts, ", ") .. "}"
        elseif type(v) == "string" then return string.format("%q", v)
        else return tostring(v) end
      end
      return write(t)
    end""")(value)


def test_the_collector_stops_when_full_until_its_sent():
    game = collector(before=COLLECTOR_ITEMS + "; fake.book = {}")
    game.lua.execute("for id = 1, 3998 do GargoyleCollectorDB.items[900000 + id] = { name = 'x', seen = 1 } end")
    saved = "GargoyleCollectorDB = " + lua_table(game, collected(game))
    game = collector(saved=saved, before=COLLECTOR_ITEMS + "; fake.book = {}")
    settle(game)
    db = collected(game)
    assert len(list(db["items"].keys())) == 4000
    assert GargoyleCollectorSummary(game).startswith("Full: 4000 items")
    gear = (234571, 240052, 240056)
    left_out = [i for i in gear if db["items"][i] is None]
    assert len(left_out) == 1 and db.checked["items"][left_out[0]] is None  # (read again once there's room)


def test_the_collector_is_switched_in_gargoyles_options():
    game = collector()
    box = game.ns.collectorBox
    assert box.GetChecked(box) and "waiting to be sent" not in game.ns.collectorText.text
    box.SetChecked(box, False)
    box.scripts.OnClick(box)
    settle(game)
    assert collected(game).on is False and len(game.fake.asked) == 0
    game.fake.itemTooltip(5187)
    settle(game)
    assert len(game.fake.asked) == 0
    box.SetChecked(box, True)
    box.scripts.OnClick(box)
    settle(game)
    assert collected(game)["items"][240056] is not None
    game.ns.optionsPanel.scripts.OnShow(game.ns.optionsPanel)
    assert "waiting to be sent" in game.ns.collectorText.text


def test_gargoyle_without_the_collector_doesnt_mention_it():
    game = Game()
    assert game.ns.collectorBox is None and "Collect item" not in game.texts()


def test_odd_saved_collector_data_starts_afresh():
    game = collector(saved='GargoyleCollectorDB = { v = 7, on = false, items = "x" }')
    db = collected(game)
    assert db.v == 1 and db.on is False and list(db["items"].keys()) == []
    game = collector(saved='GargoyleCollectorDB = { v = 1, id = "not hex!", items = { [5] = "x" }, sums = 3 }')
    settle(game)
    db = collected(game)
    assert db.id != "not hex!" and db["items"][5] is None and db["items"][240056] is not None


def test_the_talent_tree_is_read_once_the_game_has_loaded_it():
    game = collector(before=COLLECTOR_ITEMS + "; fake.char.configID = nil")
    settle(game)
    assert collected(game).talents.MAGE is None and collected(game).checked.talents.MAGE is None
    game.lua.execute("fake.char.configID = 77")
    game.fake.fire("TRAIT_CONFIG_LIST_UPDATED")
    settle(game)
    assert len(collected(game).talents.MAGE.nodes) == 4
