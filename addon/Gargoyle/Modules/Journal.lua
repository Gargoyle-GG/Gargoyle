-- Dungeon journal: WoW Forever's dungeons and raids in the Gargoyle window, as on the website's
-- Dungeons pages. The game has no journal of its own for them. Pick a place on the left
-- (inside a dungeon the tab opens on it), then:
--   Bosses: each boss in order; its loot and its abilities (in the game's own words).
--   Quests: the place's quests for your side and class, who gives each one and where, and the
--           chain of quests that leads to it, with the ones you've done ticked off. "Show on
--           map" puts the game's own map pin on the next one to do (only when you click it).
--
-- The drops and quest rewards that are upgrades for one of your Gargoyle characters are
-- marked, with how much better each one is: the website's planner works those out (from the
-- character's gear, talents and level) and the Gargoyle app brings them in. Items you're
-- wearing aren't marked. The same mark shows on item tooltips anywhere in the game.
--
-- Its data (Data/Journal.lua) is ids, names, levels, places and drop chances; item names,
-- icons and tooltips and the abilities' text come from the game. Apart from that one map pin, it only shows things.
local _, ns = ...

local Journal = {
  title = "Dungeons",
  description = "WoW Forever's dungeons and raids: each boss's loot and abilities, and the quests with their "
    .. "chains, with the drops that are upgrades for your character marked (on item tooltips too).",
}
ns.RegisterModule("journal", Journal)
ns.Journal = Journal

local PLACES = ns.JOURNAL or {}
local ROWS, ROW_HEIGHT = 18, 22 -- places in the list
local BOSS_ROWS, BOSS_HEIGHT = 15, 20
local LOOT_ROWS, LOOT_HEIGHT = 9, 30
local ABILITY_ROWS, ABILITY_HEIGHT = 5, 56
local QUEST_ROWS, QUEST_HEIGHT = 15, 20
local CHAIN_LINES = 7
local GREEN, GREY, GOLD = "|cff3fd35c", "|cffb0b0b0", "|cffffd100"
local VIEWS = { "bosses", "quests" }
local VIEW_TITLES = { bosses = "Bosses", quests = "Quests" }

local selected -- the place shown (its place in PLACES)
local boss, quest = 1, 1 -- the boss (one past the last: other drops) and quest shown
local offset, bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0, 0
local here -- the dungeon you're in, if it's one of them
local ui = {}

local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

local function clamp(value, most)
  return math.max(0, math.min(value, most))
end

local function placeIndex(id)
  for i, p in ipairs(PLACES) do
    if p.id == id then return i end
  end
end

-- The dungeon or raid you're in (as the game numbers them), or nil.
local function currentPlace()
  if not GetInstanceInfo then return end
  local _, kind, _, _, _, _, _, instanceID = GetInstanceInfo()
  if (kind == "party" or kind == "raid") and type(instanceID) == "number" then return placeIndex(instanceID) end
end

local function view()
  local v = GargoyleDB.journal.view
  return VIEW_TITLES[v] and v or "bosses"
end

-- ---- Whose upgrades ----

-- The Gargoyle character whose upgrades are marked for the one you're playing: the one picked
-- here, else the one kept up to date from it.
function Journal.Chosen()
  local key = ns.PlayerKey()
  local picked = key and GargoyleDB.journal.chars[key]
  if picked == false then return end
  local fromGame
  for _, c in ipairs(ns.sync.characters) do
    if picked and c.id == picked then return c end
    if key and c.game == key then fromGame = c end
  end
  return fromGame
end

function Journal.Choose(id)
  local key = ns.PlayerKey()
  if key then GargoyleDB.journal.chars[key] = id or false end
  Journal:Refresh(true)
end

local function worn(itemID)
  local isEquipped = (C_Item and C_Item.IsEquippedItem) or IsEquippedItem
  if not isEquipped then return false end
  local ok, yes = pcall(isEquipped, itemID)
  return ok and yes == true
end

-- How much better an item is for the character (gain, gain in %), or nil.
function Journal.Gain(itemID, character)
  character = character or Journal.Chosen()
  local gain = character and character.upgrades and character.upgrades.items[itemID]
  if gain and not worn(itemID) then return gain end
end

local function gainText(gain)
  local points = gain[1] >= 10 and string.format("%d", math.floor(gain[1] + 0.5)) or string.format("%.1f", gain[1])
  return string.format("+%s (%s%%)", points, gain[2] >= 10 and string.format("%d", math.floor(gain[2] + 0.5)) or string.format("%.1f", gain[2]))
end

-- A drop chance: "1.5%", "20%" (one decimal under 10%, as on the website).
local function chanceText(pct)
  if pct >= 10 then return string.format("%d%%", math.floor(pct + 0.5)) end
  return (string.format("%.1f", pct):gsub("%.0$", "")) .. "%"
end

-- How many of some items are upgrades (each item once), and the best one.
local function count(lists, character, seen)
  seen = seen or {}
  local n, best = 0, nil
  for _, list in ipairs(lists) do
    for _, entry in ipairs(list) do
      local id = type(entry) == "table" and entry[1] or entry
      local gain = not seen[id] and Journal.Gain(id, character)
      seen[id] = true
      if gain then
        n = n + 1
        if not best or gain[1] > best.gain[1] then best = { id = id, gain = gain } end
      end
    end
  end
  return n, best
end

-- The quests shown for the character you're playing: its side's and its class's.
function Journal.Quests(p)
  local side = UnitFactionGroup and UnitFactionGroup("player")
  local _, classFile = UnitClass("player")
  local class = type(classFile) == "string" and classFile:lower() or ""
  local list = {}
  for _, q in ipairs(p.quests or {}) do
    local forClass = not q.classes or #q.classes == 0
    for _, c in ipairs(q.classes or {}) do forClass = forClass or c == class end
    if forClass and (q.side == "Both" or q.side == nil or q.side == side) then list[#list + 1] = q end
  end
  return list
end

-- The place's drops and quest rewards that are upgrades: how many (each item once), and the best.
function Journal.Upgrades(p, character)
  local lists = {}
  for _, b in ipairs(p.bosses or {}) do lists[#lists + 1] = b.loot end
  lists[#lists + 1] = p.other or {}
  for _, q in ipairs(Journal.Quests(p)) do lists[#lists + 1] = q.rewards or {} end
  return count(lists, character)
end

-- ---- Items, spells and quests, from the game ----

local loading, loadingSpells, soon = {}, {}, false

local function refreshSoon()
  if soon then return end
  soon = true
  local after = C_Timer and C_Timer.After
  local function go()
    soon = false
    if ui.panel and ui.panel:IsVisible() then Journal:Refresh(true) end
  end
  if after then after(0.2, go) else go() end
end

-- An item's name, quality and icon, or nil while the game loads it (it's asked for, and the tab
-- redrawn when it's in).
local function itemInfo(id)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  local name, _, quality, _, _, _, _, _, _, icon
  if getInfo then name, _, quality, _, _, _, _, _, _, icon = getInfo(id) end
  if name then return name, quality, icon end
  if not loading[id] and Item and Item.CreateFromItemID then
    loading[id] = true
    Item:CreateFromItemID(id):ContinueOnItemLoad(function()
      loading[id] = nil
      refreshSoon()
    end)
  end
end

local function qualityColor(quality)
  if C_Item and C_Item.GetItemQualityColor and quality then
    local _, _, _, hex = C_Item.GetItemQualityColor(quality)
    if type(hex) == "string" then return "|c" .. hex end
  end
  return "|cffffffff"
end

local function spellIcon(id)
  local info = C_Spell and C_Spell.GetSpellInfo and C_Spell.GetSpellInfo(id)
  return type(info) == "table" and info.iconID or nil
end

-- An ability's text in the game's own words ("" while the game loads it).
local function spellText(id)
  local text = C_Spell and C_Spell.GetSpellDescription and C_Spell.GetSpellDescription(id)
  if type(text) == "string" and text ~= "" then return text end
  if not loadingSpells[id] and Spell and Spell.CreateFromSpellID then
    loadingSpells[id] = true
    pcall(function() Spell:CreateFromSpellID(id):ContinueOnSpellLoad(refreshSoon) end)
  end
  return ""
end

local function done(questID)
  local isDone = C_QuestLog and C_QuestLog.IsQuestFlaggedCompleted
  return isDone ~= nil and isDone(questID) == true
end

-- Who or what gives a quest, and where: "Gryan Stoutmantle, Westfall (56.3, 47.5)".
local function startText(s)
  s = s or {}
  local where = ""
  if s.inside then
    where = "inside " .. s.inside
  elseif s.zone then
    where = s.zone .. (s.x and string.format(" (%.1f, %.1f)", s.x, s.y or 0) or "")
  end
  if s.kind == "item" then
    return "an item, " .. (s.name or "?") .. (s.drop and (", which drops from " .. s.drop) or "")
  end
  local text = s.name or ""
  if where ~= "" then text = text ~= "" and (text .. ", " .. where) or where end
  return plain(text ~= "" and text or "not known")
end

-- The next step to take towards a quest: the first in its chain you haven't done, else itself.
local function nextStep(q)
  for i, step in ipairs(q.chain or {}) do
    if not done(step.id) then return step, i end
  end
  return q, #(q.chain or {}) + 1
end

-- Puts the game's own map pin on where a quest starts (only ever when you click the button).
function Journal.ShowOnMap(s)
  if not (s and s.map and s.x and s.y and C_Map and C_Map.SetUserWaypoint and UiMapPoint) then return false end
  if C_Map.CanSetUserWaypointOnMap and not C_Map.CanSetUserWaypointOnMap(s.map) then
    ns.say("the game can't put a pin on that map.")
    return false
  end
  C_Map.SetUserWaypoint(UiMapPoint.CreateFromCoordinates(s.map, s.x / 100, s.y / 100))
  if C_SuperTrack and C_SuperTrack.SetSuperTrackedUserWaypoint then C_SuperTrack.SetSuperTrackedUserWaypoint(true) end
  ns.say("map pin set: " .. startText(s) .. ".")
  return true
end

-- ---- The tab ----

local function facts(p)
  local parts = {}
  if p.min then parts[#parts + 1] = "Level " .. p.min .. ((p.max and p.max ~= p.min) and ("-" .. p.max) or "") end
  if p.size then parts[#parts + 1] = p.size .. " players" end
  parts[#parts + 1] = p.kind == "raid" and "Raid" or "Dungeon"
  if p.zone then parts[#parts + 1] = plain(p.zone) end
  if p.new then parts[#parts + 1] = GREEN .. "New in Forever|r" end
  return table.concat(parts, "  ·  ")
end

local function status(p, character)
  local sync = ns.sync
  if not sync.loaded then
    return "Upgrade marks come from your Gargoyle account: with the Gargoyle app running, reload or log in again."
  end
  if not sync.sendsUpgrades then
    return "Upgrade marks need the newest Gargoyle app. Its window offers it when it's out: update, then reload."
  end
  if not character then
    if #sync.characters == 0 then return "Save a character on the website to see where its upgrades drop." end
    return "Pick one of your Gargoyle characters above to see which drops are upgrades for it."
  end
  local name = plain(character.name)
  local u = character.upgrades
  if not u then
    return name .. "'s upgrades haven't been worked out yet: open it in the planner on the website, then sync."
  end
  local who = name .. ((u.spec and u.level) and string.format(" (%s, level %d)", plain(u.spec), u.level) or "")
  local n, best = Journal.Upgrades(p, character)
  local text
  if n == 0 then
    text = "Nothing here is an upgrade for " .. who .. "."
  else
    text = string.format("%s%d upgrade%s|r here for %s. Best: %s %s.", GREEN, n, n == 1 and "" or "s", who,
      plain(itemInfo(best.id) or "?"), gainText(best.gain))
  end
  if u.stale then text = text .. " " .. name .. " has changed since: open it in the planner on the website to update." end
  return text
end

local function itemButton(row, id, character)
  local name, quality, icon = itemInfo(id)
  row.itemID = id
  row.icon:SetTexture(icon or 134400) -- (the game's "?" until it's loaded)
  local gain = Journal.Gain(id, character)
  if row.upgrade then row.upgrade:SetShown(gain ~= nil) end
  return name, quality, gain
end

local function showBosses(p, character)
  -- The boss list.
  local entries = #p.bosses + ((#(p.other or {}) > 0) and 1 or 0)
  bossOffset = clamp(bossOffset, entries - BOSS_ROWS)
  for i, row in ipairs(ui.bossRows) do
    local n = i + bossOffset
    local b = p.bosses[n]
    row:SetShown(n <= entries)
    if n <= entries then
      row.index = n
      row.name:SetText(b and (n .. ". " .. plain(b.name)) or "Other drops")
      local ups = character and character.upgrades and count({ b and b.loot or p.other }, character) or 0
      row.ups:SetText(ups > 0 and (GREEN .. "+" .. ups .. "|r") or "")
      row.selectedBg:SetShown(n == boss)
    end
  end
  ui.noBosses:SetShown(entries == 0)

  -- Its loot or its abilities.
  local b = p.bosses[boss]
  local loot, abilities = b and b.loot or p.other or {}, b and b.abilities or {}
  local showLoot = GargoyleDB.journal.part ~= "abilities" or not b
  ui.lootButton:SetEnabled(not showLoot)
  ui.abilityButton:SetEnabled(showLoot and b ~= nil)
  lootOffset = clamp(lootOffset, #loot - LOOT_ROWS)
  for i, row in ipairs(ui.loot) do
    local drop = showLoot and loot[i + lootOffset]
    row:SetShown(drop ~= nil and drop ~= false)
    if drop then
      local name, quality, gain = itemButton(row, drop[1], character)
      row.name:SetText(name and (qualityColor(quality) .. plain(name) .. "|r") or (GREY .. "Loading...|r"))
      row.chance:SetText(drop[2] and chanceText(drop[2]) or "")
      row.gain:SetText(gain and (GREEN .. gainText(gain) .. "|r") or "")
    end
  end
  abilityOffset = clamp(abilityOffset, #abilities - ABILITY_ROWS)
  for i, row in ipairs(ui.abilities) do
    local a = not showLoot and abilities[i + abilityOffset]
    row:SetShown(a ~= nil and a ~= false)
    if a then
      row.spellID = a[1]
      row.icon:SetTexture(spellIcon(a[1]) or 134400)
      row.name:SetText(plain(a[2]))
      row.text:SetText(plain(spellText(a[1])))
    end
  end
  local list = showLoot and loot or abilities
  local per = showLoot and LOOT_ROWS or ABILITY_ROWS
  ui.partNote:SetText(#list == 0 and (showLoot and "No gear listed yet." or "Not known yet.")
    or (#list > per and (GREY .. "Scroll for more|r") or ""))
end

local function chainLines(q)
  local lines = {}
  local _, nextIndex = nextStep(q)
  local steps = {}
  for _, step in ipairs(q.chain or {}) do steps[#steps + 1] = step end
  steps[#steps + 1] = q
  for i, step in ipairs(steps) do
    local mark = done(step.id) and ns.Icon("UI-LFG-ReadyMark", 12) or (i == nextIndex and (GOLD .. ">|r") or " ")
    local color = i == nextIndex and GOLD or (done(step.id) and GREY or "|cffffffff")
    local title = step == q and (plain(step.title) .. GREY .. " (this quest)|r") or plain(step.title)
    lines[#lines + 1] = string.format("%s %s%d. %s|r  %s%s|r", mark, color, i, title, GREY,
      startText(step.start))
  end
  return lines
end

local function showQuests(p, character)
  local quests = Journal.Quests(p)
  questOffset = clamp(questOffset, #quests - QUEST_ROWS)
  quest = math.max(1, math.min(quest, #quests))
  for i, row in ipairs(ui.questRows) do
    local n = i + questOffset
    local q = quests[n]
    row:SetShown(q ~= nil)
    if q then
      row.index = n
      row.name:SetText((done(q.id) and (ns.Icon("UI-LFG-ReadyMark", 12) .. " ") or "") .. plain(q.title))
      row.level:SetText(q.level and tostring(q.level) or "")
      row.selectedBg:SetShown(n == quest)
    end
  end
  local q = quests[quest]
  ui.questDetail:SetShown(q ~= nil)
  ui.noQuests:SetShown(q == nil)
  if not q then return end
  local bits = {}
  if q.level then bits[#bits + 1] = "Level " .. q.level .. (q.min and (" (from " .. q.min .. ")") or "") end
  if q.side and q.side ~= "Both" then bits[#bits + 1] = q.side end
  if q.type and q.type ~= "" then bits[#bits + 1] = q.type end
  if done(q.id) then bits[#bits + 1] = GREEN .. "Done|r" end
  ui.qTitle:SetText(plain(q.title))
  ui.qFacts:SetText(table.concat(bits, "  ·  "))
  local how = q.start and q.start.kind == "item" and "Starts from " or (q.start and q.start.kind == "object" and "Starts at " or "Get it from ")
  ui.qHow:SetText(GOLD .. how .. "|r" .. startText(q.start))
  ui.qObj:SetText(plain(q.obj or ""))
  local target = nextStep(q)
  ui.showButton.target = target.start
  ui.showButton:SetEnabled(target.start ~= nil and target.start.map ~= nil and target.start.x ~= nil)
  ui.showButton:SetText(#(q.chain or {}) > 0 and "Show next step on map" or "Show on map")
  local lines = chainLines(q)
  ui.chainHeading:SetText(#lines > 1 and string.format("Chain (%d quests)", #lines) or "No quests before it")
  chainOffset = clamp(chainOffset, #lines - CHAIN_LINES)
  for i, line in ipairs(ui.chain) do
    line:SetText(#lines > 1 and lines[i + chainOffset] or "")
  end
  ui.chainMore:SetText(#lines > CHAIN_LINES and (GREY .. "Scroll for more|r") or "")
  for i, row in ipairs(ui.rewards) do
    local id = (q.rewards or {})[i]
    row:SetShown(id ~= nil)
    if id then itemButton(row, id, character) end
  end
  ui.rewardHeading:SetShown(#(q.rewards or {}) > 0)
end

function Journal:Refresh(fromMenu)
  if not ui.panel then return end
  if #PLACES == 0 then
    ui.title:SetText("No dungeons in this copy of Gargoyle.")
    return
  end
  selected = selected or here or placeIndex(GargoyleDB.journal.place) or 1
  GargoyleDB.journal.place = PLACES[selected].id
  local character = Journal.Chosen()

  -- The list of places.
  offset = clamp(offset, #PLACES - ROWS)
  for i, row in ipairs(ui.rows) do
    local p = PLACES[i + offset]
    row:SetShown(p ~= nil)
    if p then
      row.index = i + offset
      row.name:SetText(plain(p.name) .. (i + offset == here and (" " .. GREEN .. "(here)|r") or ""))
      row.level:SetText(p.kind == "raid" and "Raid" or (p.min and (p.min .. "-" .. (p.max or p.min)) or ""))
      local n = character and character.upgrades and Journal.Upgrades(p, character) or 0
      row.ups:SetText(n > 0 and (GREEN .. "+" .. n .. "|r") or "")
      row.selectedBg:SetShown(i + offset == selected)
    end
  end

  -- The place: its header, then the view picked.
  local p = PLACES[selected]
  ui.title:SetText(plain(p.name))
  ui.facts:SetText(facts(p))
  if not fromMenu then ui.who:GenerateMenu() end
  local v = view()
  for _, key in ipairs(VIEWS) do
    ui.views[key]:SetShown(key == v)
    if key == v then ui.viewButtons[key]:LockHighlight() else ui.viewButtons[key]:UnlockHighlight() end
  end
  ui.viewButtons.quests:SetText(string.format("Quests (%d)", #Journal.Quests(p)))
  if v == "bosses" then showBosses(p, character) else showQuests(p, character) end
  ui.status:SetText(status(p, character))
end

local function whoMenu(parent)
  local menu = CreateFrame("DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
  menu:SetWidth(170)
  menu:SetDefaultText("No one")
  menu:SetupMenu(function(_, root)
    root:CreateRadio("No one", function() return Journal.Chosen() == nil end, function() Journal.Choose(nil) end)
    local list = {}
    for _, c in ipairs(ns.sync.characters) do list[#list + 1] = c end
    table.sort(list, function(a, b) return a.name:lower() < b.name:lower() end)
    for _, c in ipairs(list) do
      root:CreateRadio(plain(c.name), function(id)
        local chosen = Journal.Chosen()
        return chosen ~= nil and chosen.id == id
      end, Journal.Choose, c.id)
    end
  end)
  return menu
end

function Journal.ShowView(key)
  GargoyleDB.journal.view = key
  Journal:Refresh(true)
end

function Journal.PickPlace(i)
  selected, boss, quest = i, 1, 1
  bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0
  Journal:Refresh()
end

function Journal.PickBoss(i)
  boss, lootOffset, abilityOffset = i, 0, 0
  GargoyleDB.journal.view = "bosses"
  bossOffset = math.max(bossOffset, i - BOSS_ROWS) -- (scrolled so it's in the list)
  bossOffset = math.min(bossOffset, i - 1)
  Journal:Refresh(true)
end

local function wheel(frame, scroll)
  frame:EnableMouseWheel(true)
  frame:SetScript("OnMouseWheel", function(_, delta)
    scroll(delta)
    Journal:Refresh(true)
  end)
end

local function rowButton(parent, width, height)
  local row = CreateFrame("Button", nil, parent)
  row:SetSize(width, height - 2)
  row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  row.selectedBg = row:CreateTexture(nil, "BACKGROUND")
  row.selectedBg:SetAllPoints()
  row.selectedBg:SetColorTexture(1, 0.82, 0, 0.16)
  return row
end

local function text(parent, font, wrap)
  local fs = parent:CreateFontString(nil, "ARTWORK", font)
  fs:SetJustifyH("LEFT")
  if not wrap then fs:SetWordWrap(false) end
  return fs
end

local function itemTooltip(row)
  row:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetItemByID(self.itemID)
    GameTooltip:Show()
  end)
  row:SetScript("OnLeave", function() GameTooltip:Hide() end)
end

local function createBosses(body)
  local list = CreateFrame("Frame", nil, body)
  list:SetPoint("TOPLEFT")
  list:SetSize(188, BOSS_ROWS * BOSS_HEIGHT)
  wheel(list, function(delta) bossOffset = bossOffset - delta * 2 end)
  ui.bossRows = {}
  for i = 1, BOSS_ROWS do
    local row = rowButton(list, 186, BOSS_HEIGHT)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * BOSS_HEIGHT)
    row.ups = text(row, "GameFontHighlightSmall")
    row.ups:SetPoint("RIGHT", -4, 0)
    row.name = text(row, "GameFontHighlightSmall")
    row.name:SetPoint("LEFT", 6, 0)
    row.name:SetPoint("RIGHT", row.ups, "LEFT", -4, 0)
    row:SetScript("OnClick", function(self) Journal.PickBoss(self.index) end)
    ui.bossRows[i] = row
  end
  ui.noBosses = text(list, "GameFontDisableSmall")
  ui.noBosses:SetPoint("TOPLEFT", 6, -4)
  ui.noBosses:SetText("Its bosses aren't known yet.")

  local right = CreateFrame("Frame", nil, body)
  right:SetPoint("TOPLEFT", list, "TOPRIGHT", 10, 0)
  right:SetPoint("BOTTOMRIGHT")
  wheel(right, function(delta)
    if GargoyleDB.journal.part == "abilities" then abilityOffset = abilityOffset - delta else lootOffset = lootOffset - delta * 2 end
  end)
  local function part(label, key, x)
    local b = CreateFrame("Button", nil, right, "UIPanelButtonTemplate")
    b:SetSize(84, 20)
    b:SetPoint("TOPLEFT", x, 0)
    b:SetText(label)
    b:SetScript("OnClick", function()
      GargoyleDB.journal.part = key
      Journal:Refresh(true)
    end)
    return b
  end
  ui.lootButton = part("Loot", "loot", 0)
  ui.abilityButton = part("Abilities", "abilities", 88)
  ui.partNote = text(right, "GameFontDisableSmall")
  ui.partNote:SetPoint("LEFT", ui.abilityButton, "RIGHT", 10, 0)
  ui.loot = {}
  for i = 1, LOOT_ROWS do
    local row = rowButton(right, 352, LOOT_HEIGHT)
    row.selectedBg:Hide()
    row:SetPoint("TOPLEFT", 0, -26 - (i - 1) * LOOT_HEIGHT)
    row.upgrade = row:CreateTexture(nil, "BACKGROUND")
    row.upgrade:SetAllPoints()
    row.upgrade:SetColorTexture(0.25, 0.83, 0.36, 0.14)
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetSize(24, 24)
    row.icon:SetPoint("LEFT", 4, 0)
    row.chance = text(row, "GameFontDisableSmall")
    row.chance:SetPoint("RIGHT", -6, 0)
    row.gain = text(row, "GameFontHighlightSmall")
    row.gain:SetPoint("RIGHT", -44, 0)
    row.name = text(row, "GameFontHighlightSmall")
    row.name:SetPoint("LEFT", row.icon, "RIGHT", 6, 0)
    row.name:SetPoint("RIGHT", row.gain, "LEFT", -4, 0)
    itemTooltip(row)
    ui.loot[i] = row
  end
  ui.abilities = {}
  for i = 1, ABILITY_ROWS do
    local row = CreateFrame("Button", nil, right)
    row:SetHeight(ABILITY_HEIGHT - 4)
    row:SetPoint("TOPLEFT", 0, -26 - (i - 1) * ABILITY_HEIGHT)
    row:SetPoint("RIGHT")
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetSize(22, 22)
    row.icon:SetPoint("TOPLEFT", 4, -2)
    row.name = text(row, "GameFontNormalSmall")
    row.name:SetPoint("TOPLEFT", row.icon, "TOPRIGHT", 6, 0)
    row.name:SetPoint("RIGHT", -4, 0)
    row.text = text(row, "GameFontHighlightSmall", true)
    row.text:SetPoint("TOPLEFT", row.name, "BOTTOMLEFT", 0, -2)
    row.text:SetPoint("RIGHT", -4, 0)
    row.text:SetJustifyV("TOP")
    row.text:SetMaxLines(3)
    row:SetScript("OnEnter", function(self) -- (the game's own tooltip for it)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetSpellByID(self.spellID)
      GameTooltip:Show()
    end)
    row:SetScript("OnLeave", function() GameTooltip:Hide() end)
    ui.abilities[i] = row
  end
end

local function createQuests(body)
  local list = CreateFrame("Frame", nil, body)
  list:SetPoint("TOPLEFT")
  list:SetSize(218, QUEST_ROWS * QUEST_HEIGHT)
  wheel(list, function(delta) questOffset = questOffset - delta * 2 end)
  ui.questRows = {}
  for i = 1, QUEST_ROWS do
    local row = rowButton(list, 216, QUEST_HEIGHT)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * QUEST_HEIGHT)
    row.level = text(row, "GameFontDisableSmall")
    row.level:SetPoint("RIGHT", -4, 0)
    row.name = text(row, "GameFontHighlightSmall")
    row.name:SetPoint("LEFT", 6, 0)
    row.name:SetPoint("RIGHT", row.level, "LEFT", -4, 0)
    row:SetScript("OnClick", function(self)
      quest, chainOffset = self.index, 0
      Journal:Refresh(true)
    end)
    ui.questRows[i] = row
  end
  ui.noQuests = text(body, "GameFontDisable", true)
  ui.noQuests:SetPoint("TOPLEFT", 4, -4)
  ui.noQuests:SetPoint("RIGHT", -4, 0)
  ui.noQuests:SetText("No quests known here for your side and class.")

  local d = CreateFrame("Frame", nil, body)
  d:SetPoint("TOPLEFT", list, "TOPRIGHT", 12, 0)
  d:SetPoint("BOTTOMRIGHT")
  ui.questDetail = d
  ui.qTitle = text(d, "GameFontNormal")
  ui.qTitle:SetPoint("TOPLEFT")
  ui.qTitle:SetPoint("RIGHT")
  ui.qFacts = text(d, "GameFontDisableSmall")
  ui.qFacts:SetPoint("TOPLEFT", ui.qTitle, "BOTTOMLEFT", 0, -4)
  ui.qFacts:SetPoint("RIGHT")
  ui.qHow = text(d, "GameFontHighlightSmall", true)
  ui.qHow:SetPoint("TOPLEFT", ui.qFacts, "BOTTOMLEFT", 0, -8)
  ui.qHow:SetPoint("RIGHT")
  ui.showButton = CreateFrame("Button", nil, d, "UIPanelButtonTemplate")
  ui.showButton:SetSize(170, 20)
  ui.showButton:SetPoint("TOPLEFT", ui.qHow, "BOTTOMLEFT", 0, -6)
  ui.showButton:SetScript("OnClick", function(self) Journal.ShowOnMap(self.target) end)
  ns.Tooltip(ui.showButton, "Show on map", "Puts the game's own map pin on where the next quest to do starts, as "
    .. "clicking the world map does. Steps inside a dungeon or started by an item have no pin.")
  ui.qObj = text(d, "GameFontHighlightSmall", true)
  ui.qObj:SetPoint("TOPLEFT", ui.showButton, "BOTTOMLEFT", 0, -8)
  ui.qObj:SetPoint("RIGHT")
  ui.qObj:SetMaxLines(3)
  ui.chainHeading = text(d, "GameFontNormalSmall")
  ui.chainHeading:SetPoint("TOPLEFT", ui.qObj, "BOTTOMLEFT", 0, -10)
  local chainArea = CreateFrame("Frame", nil, d)
  chainArea:SetPoint("TOPLEFT", ui.chainHeading, "BOTTOMLEFT", 0, -4)
  chainArea:SetPoint("RIGHT")
  chainArea:SetHeight(CHAIN_LINES * 14)
  wheel(chainArea, function(delta) chainOffset = chainOffset - delta * 2 end)
  ui.chain = {} -- (a line each: a long one is cut short rather than pushing the rest down)
  for i = 1, CHAIN_LINES do
    local line = text(chainArea, "GameFontHighlightSmall")
    line:SetPoint("TOPLEFT", 0, -(i - 1) * 14)
    line:SetPoint("RIGHT")
    ui.chain[i] = line
  end
  ui.chainMore = text(d, "GameFontDisableSmall")
  ui.chainMore:SetPoint("LEFT", ui.chainHeading, "RIGHT", 10, 0)
  ui.rewardHeading = text(d, "GameFontNormalSmall")
  ui.rewardHeading:SetPoint("BOTTOMLEFT", 0, 30)
  ui.rewardHeading:SetText("Rewards")
  ui.rewards = {}
  for i = 1, 6 do
    local row = CreateFrame("Button", nil, d)
    row:SetSize(26, 26)
    row:SetPoint("BOTTOMLEFT", (i - 1) * 30, 0)
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetAllPoints()
    row.upgrade = row:CreateTexture(nil, "OVERLAY")
    row.upgrade:SetAllPoints()
    row.upgrade:SetColorTexture(0.25, 0.83, 0.36, 0.35)
    itemTooltip(row)
    ui.rewards[i] = row
  end
end

function Journal:CreatePanel(panel)
  ui.panel = panel
  -- Left: every place, dungeons by level, then raids.
  local list = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  list:SetPoint("TOPLEFT")
  list:SetPoint("BOTTOMLEFT")
  list:SetWidth(200)
  wheel(list, function(delta) offset = offset - delta * 3 end)
  local heading = text(list, "GameFontNormal")
  heading:SetPoint("TOPLEFT", 10, -8)
  heading:SetText("Dungeons and raids")
  ui.rows = {}
  for i = 1, ROWS do
    local row = rowButton(list, 192, ROW_HEIGHT)
    row:SetPoint("TOPLEFT", 4, -26 - (i - 1) * ROW_HEIGHT)
    row.level = text(row, "GameFontDisableSmall")
    row.level:SetPoint("RIGHT", -6, 0)
    row.ups = text(row, "GameFontHighlightSmall")
    row.ups:SetPoint("RIGHT", -46, 0)
    row.name = text(row, "GameFontHighlightSmall")
    row.name:SetPoint("LEFT", 6, 0)
    row.name:SetPoint("RIGHT", row.ups, "LEFT", -4, 0)
    row:SetScript("OnClick", function(self) Journal.PickPlace(self.index) end)
    ui.rows[i] = row
  end

  -- Right: the place.
  local detail = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  detail:SetPoint("TOPLEFT", list, "TOPRIGHT", 6, 0)
  detail:SetPoint("BOTTOMRIGHT")
  ui.title = text(detail, "GameFontNormalLarge")
  ui.title:SetPoint("TOPLEFT", 14, -12)
  ui.title:SetPoint("RIGHT", -270, 0)
  ui.facts = text(detail, "GameFontHighlightSmall")
  ui.facts:SetPoint("TOPLEFT", ui.title, "BOTTOMLEFT", 0, -6)
  ui.facts:SetPoint("RIGHT", -14, 0)
  ui.who = whoMenu(detail)
  ui.who:SetPoint("TOPRIGHT", -12, -8)
  local whoLabel = text(detail, "GameFontNormalSmall")
  whoLabel:SetPoint("RIGHT", ui.who, "LEFT", -6, 0)
  whoLabel:SetText("Upgrades for")
  ui.viewButtons, ui.views = {}, {}
  for i, key in ipairs(VIEWS) do
    local b = CreateFrame("Button", nil, detail, "UIPanelButtonTemplate")
    b:SetSize(110, 22)
    b:SetPoint("TOPLEFT", 12 + (i - 1) * 114, -54)
    b:SetText(VIEW_TITLES[key])
    b:SetScript("OnClick", function() Journal.ShowView(key) end)
    ui.viewButtons[key] = b
    local body = CreateFrame("Frame", nil, detail)
    body:SetPoint("TOPLEFT", 10, -84)
    body:SetPoint("BOTTOMRIGHT", -10, 36)
    ui.views[key] = body
  end
  createBosses(ui.views.bosses)
  createQuests(ui.views.quests)
  ui.status = text(detail, "GameFontHighlightSmall", true)
  ui.status:SetPoint("BOTTOMLEFT", 14, 8)
  ui.status:SetPoint("RIGHT", -14, 0)
end

-- ---- Item tooltips anywhere: "Upgrade for <character>" ----

local function onItemTooltip(tooltip, data)
  if not ns.IsEnabled("journal") or type(data) ~= "table" then return end
  local id = data.id
  if type(id) ~= "number" or (issecretvalue and issecretvalue(id)) then return end
  local character = Journal.Chosen()
  local gain = Journal.Gain(id, character)
  if gain and tooltip.AddLine then
    tooltip:AddLine(string.format("%sGargoyle: upgrade for %s, %s|r", GREEN, plain(character.name), gainText(gain)))
  end
end

-- ---- Keeping up ----

local watcher = CreateFrame("Frame")
watcher:SetScript("OnEvent", function(_, event)
  if event == "QUEST_TURNED_IN" then
    if ui.panel and ui.panel:IsVisible() then refreshSoon() end -- (a chain step done: ticked off)
    return
  end
  local now = currentPlace()
  if now ~= here then
    here = now
    if now then -- (opens on the dungeon you've just gone into)
      selected, boss, quest = now, 1, 1
      bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0
    end
    if ui.panel and ui.panel:IsVisible() then Journal:Refresh() end
  end
end)

function Journal:OnLogin()
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, onItemTooltip)
  end
  here = currentPlace()
end

function Journal:OnEnable()
  for _, event in ipairs({ "PLAYER_ENTERING_WORLD", "ZONE_CHANGED_NEW_AREA", "QUEST_TURNED_IN" }) do
    pcall(watcher.RegisterEvent, watcher, event)
  end
end

function Journal:OnDisable()
  watcher:UnregisterAllEvents()
end
