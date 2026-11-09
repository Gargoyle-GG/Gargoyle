-- Gargoyle Dungeons: WoW Forever's dungeons and raids in the Gargoyle window, as on the website's
-- Dungeons pages. An addon of its own that needs Gargoyle (the core), which it uses through the
-- Gargoyle table. The game has no journal of its own for them. Pick a place on the left
-- (inside a dungeon the tab opens on it), then:
--   Bosses: each boss in order; its loot and its abilities (in the game's own words).
--   Quests: the place's quests for your side and class, a chain of quests as one entry (as on
--           the website). Pick one to see its steps in order, with the ones you've done ticked
--           off, and the step to do next (or the one you click): who gives it and where, what
--           it asks and its rewards. "Show on map" puts the game's own map pin on where that
--           step starts (only when you click it). Horde-only and Alliance-only quests say so.
--   Map:    the game's own maps of Kalimdor and the Eastern Kingdoms (the world map's art) with
--           a pin on each entrance. Point at a pin to see the place, click it to open it; point
--           at a place in the list to light up its pin.
-- Places Blizzard has announced but that aren't in the game yet say when they come; the
-- original raids Forever hasn't announced say "Not yet released" and have no pin.
--
-- The drops and quest rewards that are upgrades for one of your Gargoyle characters are
-- marked, with how much better each one is (the core's Upgrades.lua), and each drop has a
-- wishlist star. Ctrl-click a drop to try it on, Shift-click to link it, as in your bags.
--
-- Its data (Data/Journal.lua) is ids, names, levels, places and drop chances; item names,
-- icons and tooltips and the abilities' text come from the game. Apart from that one map pin, it only shows things.
local _, ns = ...
local G = Gargoyle
if not G or (G.API or 1) < 2 then -- (an older Gargoyle addon: it hasn't what this needs)
  print("|cffd4a017Gargoyle|r: Gargoyle Dungeons needs a newer Gargoyle addon. Update it with the Gargoyle app (or turn Gargoyle Dungeons off).")
  return
end
local Upgrades = G.Upgrades

local Journal = {
  title = "Dungeons",
  description = "WoW Forever's dungeons and raids: each boss's loot and abilities, and the quests with their "
    .. "chains, with the drops that are upgrades for your character marked (on item tooltips too).",
}
G.RegisterModule("journal", Journal)
ns.Journal, G.Journal = Journal, Journal -- (G.Journal: for Gargoyle Loot's "Open in Dungeons")

local PLACES = ns.JOURNAL or {}
local ROWS, ROW_HEIGHT = 18, 22 -- places in the list
local BOSS_ROWS, BOSS_HEIGHT = 15, 20
local LOOT_ROWS, LOOT_HEIGHT = 9, 30
local ABILITY_ROWS, ABILITY_HEIGHT = 5, 56
local QUEST_ROWS, QUEST_HEIGHT = 15, 20
local CHAIN_LINES, STEP_HEIGHT = 6, 15 -- a chain's steps shown at once
local GREEN, GREY, GOLD = "|cff3fd35c", "|cffb0b0b0", "|cffffd100"
local SIDE_COLORS = { Horde = "|cffff5b4d", Alliance = "|cff4da6ff" }
local VIEWS = { "bosses", "quests", "map" }
local VIEW_TITLES = { bosses = "Bosses", quests = "Quests", map = "Map" }
local MAPS = ns.JOURNAL_MAPS or {}

local selected -- the place shown (its place in PLACES)
local boss, quest = 1, 1 -- the boss (one past the last: other drops) and quest shown
local step -- the chain's step picked (nil: the next one to do)
local followStep = true -- (scroll the chain's steps to the one shown, once)
local offset, bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0, 0
local here -- the dungeon you're in, if it's one of them
local ui = {}

local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

local function clamp(value, most)
  return math.max(0, math.min(value, most))
end

-- A place by its game id (or by name: the announced ones have no id yet).
local function placeIndex(id)
  if id == nil then return end
  for i, p in ipairs(PLACES) do
    if p.id == id or p.name == id then return i end
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

-- ---- Whose upgrades (the core's) ----

Journal.Chosen, Journal.Choose, Journal.Gain = Upgrades.Chosen, Upgrades.Choose, Upgrades.Gain
local gainText = Upgrades.GainText

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

local function forYou(q, side, class)
  local forClass = not q.classes or #q.classes == 0
  for _, c in ipairs(q.classes or {}) do forClass = forClass or c == class end
  return forClass and (q.side == "Both" or q.side == nil or q.side == side)
end

-- The quests shown for the character you're playing: its side's and its class's. Each is an
-- entry, { title, side, steps }: a quest on its own (one step) or a chain of them, with only
-- the steps for you (a chain's lead-in quests too). One whose own quests aren't for you isn't.
function Journal.Quests(p)
  local side = UnitFactionGroup and UnitFactionGroup("player")
  local _, classFile = UnitClass("player")
  local class = type(classFile) == "string" and classFile:lower() or ""
  local list = {}
  for _, e in ipairs(p.quests or {}) do
    local steps, mine = {}, false
    for _, q in ipairs(e.steps or { e }) do
      if forYou(q, side, class) then
        steps[#steps + 1] = q
        mine = mine or q.here or e.steps == nil
      end
    end
    if mine then list[#list + 1] = { title = e.title, side = e.side or "Both", steps = steps } end
  end
  return list
end

-- The place's drops and quest rewards that are upgrades: how many (each item once), and the best.
function Journal.Upgrades(p, character)
  local lists = {}
  for _, b in ipairs(p.bosses or {}) do lists[#lists + 1] = b.loot end
  lists[#lists + 1] = p.other or {}
  for _, e in ipairs(Journal.Quests(p)) do
    for _, q in ipairs(e.steps) do lists[#lists + 1] = q.rewards or {} end
  end
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
  if not loading[id] then
    loading[id] = G.Items.Load(id, function()
      loading[id] = nil
      refreshSoon()
    end) or "unknown" -- (an item the game doesn't know: not asked again)
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

-- A quest (or chain step) done: it, or any copy of it shown as it ("also": the same quest at
-- another of Gnomeregan's Sparklematic machines).
local function stepDone(q)
  if done(q.id) then return true end
  for _, id in ipairs(q.also or {}) do
    if done(id) then return true end
  end
  return false
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

-- The next step to take in a chain (or the quest itself): the first you haven't done, else
-- the last. A step you take first but hand in at the end ("last": Gnomeregan's Rig Wars) isn't
-- next while a step after it is still to do. Its place in the steps, and whether you've done them all.
local function nextStep(e)
  local steps = e.steps
  for i, q in ipairs(steps) do
    if not stepDone(q) then
      local waits = false
      if q.last then
        for j = i + 1, #steps do waits = waits or not stepDone(steps[j]) end
      end
      if not waits then return i, false end
    end
  end
  return #steps, true
end

-- A small "Horde" or "Alliance" in the side's colour: a quest or chain only that side has.
local function sideTag(side)
  return SIDE_COLORS[side] and (SIDE_COLORS[side] .. side .. "|r") or nil
end

-- A chain's levels: "Level 26-30".
local function levelsText(steps)
  local low, high
  for _, q in ipairs(steps) do
    if q.level then
      low, high = math.min(low or q.level, q.level), math.max(high or q.level, q.level)
    end
  end
  if not low then return end
  return "Level " .. low .. (high ~= low and ("-" .. high) or "")
end

-- Puts the game's own map pin on where a quest starts (only ever when you click the button).
function Journal.ShowOnMap(s)
  if not (s and s.map and s.x and s.y and C_Map and C_Map.SetUserWaypoint and UiMapPoint) then return false end
  if C_Map.CanSetUserWaypointOnMap and not C_Map.CanSetUserWaypointOnMap(s.map) then
    G.say("the game can't put a pin on that map.")
    return false
  end
  C_Map.SetUserWaypoint(UiMapPoint.CreateFromCoordinates(s.map, s.x / 100, s.y / 100))
  if C_SuperTrack and C_SuperTrack.SetSuperTrackedUserWaypoint then C_SuperTrack.SetSuperTrackedUserWaypoint(true) end
  G.say("map pin set: " .. startText(s) .. ".")
  return true
end

-- ---- The tab ----

local function levelText(p)
  if not p.min then return end
  return "Level " .. p.min .. ((p.max and p.max ~= p.min) and ("-" .. p.max) or "") .. (p.expected and " (expected)" or "")
end

-- When it comes, if it isn't in the game yet.
local function whenText(p)
  if not p.when then return end
  return (p.later and GREY or GOLD) .. plain(p.when) .. "|r"
end

local function facts(p)
  local parts = {}
  parts[#parts + 1] = levelText(p)
  if p.size then parts[#parts + 1] = p.size .. " players" end
  parts[#parts + 1] = p.kind == "raid" and "Raid" or "Dungeon"
  if p.zone and p.zone ~= "" then parts[#parts + 1] = plain(p.zone) end
  if p.new then parts[#parts + 1] = GREEN .. "New in Forever|r" end
  parts[#parts + 1] = whenText(p)
  return table.concat(parts, "  ·  ")
end

local function status(p, character)
  local missing = Upgrades.Missing(character)
  if missing then return missing end
  local name = plain(character.name)
  local u = character.upgrades
  local who = Upgrades.Who(character)
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
  if row.star then
    row.star.itemID = id
    row.star:Update()
  end
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

-- A quest's (or a chain step's) facts: "Level 22 (from 14)  ·  Alliance  ·  Dungeon  ·  Done".
local function questFacts(q, withSide)
  local bits = {}
  if q.level then bits[#bits + 1] = "Level " .. q.level .. (q.min and (" (from " .. q.min .. ")") or "") end
  if withSide then bits[#bits + 1] = sideTag(q.side) end
  if q.type and q.type ~= "" then bits[#bits + 1] = plain(q.type) end
  if q.after then bits[#bits + 1] = "after " .. plain(q.after) end
  if q.apart then bits[#bits + 1] = "a separate start" end
  if not q.here then bits[#bits + 1] = "lead-in quest" end
  if q.repeatable then bits[#bits + 1] = "repeatable" end
  if q.last then bits[#bits + 1] = "take it first, hand it in last" end
  if stepDone(q) then bits[#bits + 1] = GREEN .. "Done|r" end
  return table.concat(bits, "  ·  ")
end

local function showQuests(p, character)
  local entries = Journal.Quests(p)
  questOffset = clamp(questOffset, #entries - QUEST_ROWS)
  quest = math.max(1, math.min(quest, #entries))
  for i, row in ipairs(ui.questRows) do
    local n = i + questOffset
    local e = entries[n]
    row:SetShown(e ~= nil)
    if e then
      row.index = n
      local _, all = nextStep(e)
      row.name:SetText((all and (G.Icon("UI-LFG-ReadyMark", 12) .. " ") or "") .. plain(e.title))
      local levels = (levelsText(e.steps) or ""):gsub("^Level ", "")
      local tag = sideTag(e.side)
      row.level:SetText((tag and (tag .. " ") or "") .. levels)
      row.selectedBg:SetShown(n == quest)
    end
  end
  local e = entries[quest]
  ui.questDetail:SetShown(e ~= nil)
  ui.noQuests:SetShown(e == nil)
  if not e then return end
  local steps, chain = e.steps, #e.steps > 1
  local nextIndex, all = nextStep(e)
  local shown = math.max(1, math.min(step or nextIndex, #steps))
  local q = steps[shown]
  ui.qTitle:SetText(plain(e.title))
  if chain then
    local bits = { string.format("Chain: %d quests", #steps), levelsText(steps), sideTag(e.side) }
    if all then bits[#bits + 1] = GREEN .. "All done|r" end
    ui.qFacts:SetText(table.concat(bits, "  ·  "))
  else
    ui.qFacts:SetText(questFacts(q, true))
  end

  -- A chain's steps: click one to see it (the next one to do is shown till then).
  ui.stepArea:SetShown(chain)
  ui.chainHeading:SetShown(chain)
  ui.chainMore:SetShown(chain)
  ui.sTitle:SetShown(chain)
  ui.qHow:ClearAllPoints()
  ui.qHow:SetPoint("TOPLEFT", chain and ui.sTitle or ui.qFacts, "BOTTOMLEFT", 0, chain and -4 or -8)
  ui.qHow:SetPoint("RIGHT")
  if chain then
    if followStep then
      chainOffset = shown - CHAIN_LINES
      followStep = false
    end
    chainOffset = clamp(chainOffset, #steps - CHAIN_LINES)
    for i, row in ipairs(ui.stepRows) do
      local n = i + chainOffset
      local st = steps[n]
      row:SetShown(st ~= nil)
      if st then
        row.index = n
        local isDone = stepDone(st)
        local mark = isDone and G.Icon("UI-LFG-ReadyMark", 12) or (n == nextIndex and (GOLD .. ">|r") or " ")
        local color = (n == nextIndex and not isDone) and GOLD or (isDone and GREY or "|cffffffff")
        local tag = e.side == "Both" and sideTag(st.side)
        row.name:SetText(string.format("%s %s%d. %s|r%s", mark, color, n, plain(st.title), tag and ("  " .. tag) or ""))
        row.level:SetText(st.level and tostring(st.level) or "")
        row.selectedBg:SetShown(n == shown)
      end
    end
    ui.chainMore:SetText(#steps > CHAIN_LINES and (GREY .. "Scroll for more|r") or "")
    ui.sTitle:SetText(string.format("%sStep %d: %s|r  %s%s|r", GOLD, shown, plain(q.title), GREY,
      questFacts(q, e.side == "Both")))
  end

  -- The quest (or the step shown): who gives it and where, what it asks, its rewards.
  local how = q.start and q.start.kind == "item" and "Starts from " or (q.start and q.start.kind == "object" and "Starts at " or "Get it from ")
  ui.qHow:SetText(GOLD .. how .. "|r" .. startText(q.start))
  ui.qObj:SetText(plain(q.obj or ""))
  ui.showButton.target = q.start
  ui.showButton:SetEnabled(q.start ~= nil and q.start.map ~= nil and q.start.x ~= nil)
  for i, row in ipairs(ui.rewards) do
    local id = (q.rewards or {})[i]
    row:SetShown(id ~= nil)
    if id then itemButton(row, id, character) end
  end
  ui.rewardHeading:SetShown(#(q.rewards or {}) > 0)
end

local showMap -- (the Map view's, below)

function Journal:Refresh(fromMenu)
  if not ui.panel then return end
  if #PLACES == 0 then
    ui.title:SetText("No dungeons in this copy of Gargoyle.")
    return
  end
  selected = selected or here or placeIndex(GargoyleDB.journal.place) or 1
  GargoyleDB.journal.place = PLACES[selected].id or PLACES[selected].name
  local character = Journal.Chosen()

  -- The list of places.
  offset = clamp(offset, #PLACES - ROWS)
  for i, row in ipairs(ui.rows) do
    local p = PLACES[i + offset]
    row:SetShown(p ~= nil)
    if p then
      row.index = i + offset
      row.name:SetText((p.later and GREY or "") .. plain(p.name) .. (p.later and "|r" or "")
        .. (i + offset == here and (" " .. GREEN .. "(here)|r") or ""))
      row.level:SetText(p.later and "Not yet" or p.kind == "raid" and "Raid" or (p.min and (p.min .. "-" .. (p.max or p.min)) or ""))
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
  if v == "bosses" then showBosses(p, character) elseif v == "quests" then showQuests(p, character) else showMap(character) end
  ui.status:SetText(status(p, character))
end

function Journal.ShowView(key)
  GargoyleDB.journal.view = key
  Journal:Refresh(true)
end

function Journal.PickPlace(i)
  selected, boss, quest, step, followStep = i, 1, 1, nil, true
  bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0
  Journal:Refresh()
end

-- A quest (or chain) in the list: shows its next step to do.
function Journal.PickQuest(i)
  quest, step, followStep, chainOffset = i, nil, true, 0
  Journal:Refresh(true)
end

-- A step of the chain shown: who gives it and where, what it asks and its rewards.
function Journal.PickStep(i)
  step = i
  Journal:Refresh(true)
end

-- Opens a place (its game id, or the name of one that has none yet) on the Bosses view: for
-- Gargoyle Loot's "Open in Dungeons".
function Journal.Open(id)
  local i = placeIndex(id)
  if not i then return end
  selected, boss, quest, step, followStep = i, 1, 1, nil, true
  bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0
  GargoyleDB.journal.view = "bosses"
  G.OpenWindow("journal")
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

-- The game's tooltip for the item, and its own Ctrl-click (try it on) and Shift-click (link it).
local function itemTooltip(row)
  row:SetScript("OnEnter", function(self) G.Items.Tooltip(self, self.itemID) end)
  row:SetScript("OnLeave", function() GameTooltip:Hide() end)
  row:SetScript("OnClick", function(self) G.Items.Click(self.itemID) end)
end

-- ---- The Map view ----
-- The game's own world map art for the two continents, trimmed to the land as on the website
-- (C_Map.GetMapArtLayers / GetMapArtLayerTextures: what the world map itself draws with, so
-- the addon ships no pictures), with a pin on each entrance.

local MAP_HEIGHT = 322
local PIN, NEAR, SPREAD = 11, 9, 7 -- a pin's size; pins closer than NEAR are spread SPREAD round their spot
local COLORS = { dungeon = { 1, 0.78, 0.3 }, raid = { 0.92, 0.36, 0.24 } }
local MASK = "Interface\\CharacterFrame\\TempPortraitAlphaMask" -- (round)
local lit -- the place lit from the list (its place in PLACES)

local function mapWidth(m)
  return math.floor(MAP_HEIGHT * (m.crop[3] - m.crop[1]) / (m.crop[4] - m.crop[2]) + 0.5)
end

-- One continent's art, its tiles placed so the trimmed part fills `holder` (which clips the
-- rest). False when the game doesn't give it.
local function drawArt(holder, m, width)
  if not (C_Map and C_Map.GetMapArtLayers and C_Map.GetMapArtLayerTextures) then return false end
  local ok, layers = pcall(C_Map.GetMapArtLayers, m.id)
  local info = ok and type(layers) == "table" and layers[1]
  local ok2, textures = pcall(C_Map.GetMapArtLayerTextures, m.id, 1)
  if not (info and ok2 and type(textures) == "table" and #textures > 0) then return false end
  local scale = width / (m.crop[3] - m.crop[1])
  local canvas = CreateFrame("Frame", nil, holder)
  canvas:SetSize(info.layerWidth * scale, info.layerHeight * scale)
  canvas:SetPoint("TOPLEFT", -m.crop[1] * scale, m.crop[2] * scale)
  local cols = math.ceil(info.layerWidth / info.tileWidth)
  local rows = math.ceil(info.layerHeight / info.tileHeight)
  for row = 1, rows do
    for col = 1, cols do
      local tile = canvas:CreateTexture(nil, "BACKGROUND")
      tile:SetTexture(textures[(row - 1) * cols + col])
      tile:SetSize(info.tileWidth * scale, info.tileHeight * scale)
      tile:SetPoint("TOPLEFT", (col - 1) * info.tileWidth * scale, -(row - 1) * info.tileHeight * scale)
    end
  end
  return true
end

local function disc(pin, size, layer, sublevel)
  local t = pin:CreateTexture(nil, layer, nil, sublevel)
  t:SetSize(size, size)
  t:SetPoint("CENTER")
  local mask = pin:CreateMaskTexture()
  mask:SetTexture(MASK, "CLAMPTOBLACKADDITIVE", "CLAMPTOBLACKADDITIVE")
  mask:SetAllPoints(t)
  t:AddMaskTexture(mask)
  return t
end

local function rowFor(index)
  for _, row in ipairs(ui.rows or {}) do
    if row:IsShown() and row.index == index then return row end
  end
end

local function pinTooltip(pin)
  local p = PLACES[pin.index]
  local color = COLORS[p.kind] or COLORS.dungeon
  GameTooltip:SetOwner(pin, "ANCHOR_RIGHT")
  GameTooltip:SetText(plain(p.name), color[1], color[2], color[3])
  local where = p.pin.zone and ("somewhere in " .. plain(p.zone) .. " (its entrance isn't known yet)") or plain(p.zone or "")
  GameTooltip:AddLine((levelText(p) or "Levels not known") .. (p.kind == "raid" and " raid" or "") .. "  ·  " .. where, 1, 1, 1, true)
  local bosses = #p.bosses > 0 and #p.bosses or p.bossCount
  GameTooltip:AddLine((p.size or "?") .. " players" .. (bosses and ("  ·  " .. bosses .. " boss" .. (bosses == 1 and "" or "es")) or ""), 0.7, 0.7, 0.7)
  if p.when then GameTooltip:AddLine(plain(p.when), 1, 0.82, 0) end
  local character = Journal.Chosen()
  local n = character and character.upgrades and Journal.Upgrades(p, character) or 0
  if n > 0 then
    GameTooltip:AddLine(string.format("%d upgrade%s for %s", n, n == 1 and "" or "s", plain(character.name)), 0.25, 0.83, 0.36)
  end
  GameTooltip:AddLine("Click to open it.", 0.6, 0.6, 0.6)
  GameTooltip:Show()
end

-- The glow (the place lit from the list, and the one picked) and the panel beside the maps.
local function showLit()
  for _, pin in ipairs(ui.pins) do
    pin.glow:SetShown(pin.index == selected or pin.index == lit)
  end
  local p = PLACES[lit or selected]
  ui.mapName:SetText(plain(p.name))
  local lines = { facts(p) }
  if not p.pin then
    lines[#lines + 1] = GREY .. (p.later and "Not on the map: not released yet." or "Not on the map: where it is isn't known yet.") .. "|r"
  elseif p.pin.zone then
    lines[#lines + 1] = GREY .. "Somewhere in " .. plain(p.zone) .. ": its entrance isn't known yet.|r"
  end
  ui.mapFacts:SetText(table.concat(lines, "\n\n"))
end

-- The pins (with their upgrade rings) and the panel beside the maps.
function showMap(character)
  if not ui.artTried then -- (drawn the first time the Map view shows)
    ui.artTried = true
    local missing = false
    for _, holder in ipairs(ui.mapHolders) do
      if not drawArt(holder, holder.map, holder.width) then missing = true end
    end
    ui.noArt:SetShown(missing)
  end
  for _, pin in ipairs(ui.pins) do
    pin.up:SetShown(character ~= nil and character.upgrades ~= nil and Journal.Upgrades(PLACES[pin.index], character) > 0)
  end
  showLit()
end

function Journal.LightPin(index)
  lit = index
  if ui.panel and ui.views and ui.views.map:IsVisible() then showLit() end
end

local function createMap(body)
  ui.mapHolders, ui.pins = {}, {}
  local x = 0
  for _, m in ipairs(MAPS) do
    local width = mapWidth(m)
    local holder = CreateFrame("Frame", nil, body)
    holder:SetSize(width, MAP_HEIGHT)
    holder:SetPoint("TOPLEFT", x, 0)
    if holder.SetClipsChildren then holder:SetClipsChildren(true) end
    local back = holder:CreateTexture(nil, "BACKGROUND", nil, -8) -- (under the art; all there is without it)
    back:SetAllPoints()
    back:SetColorTexture(0.12, 0.1, 0.07, 1)
    holder.map, holder.width = m, width
    ui.mapHolders[#ui.mapHolders + 1] = holder
    -- The pins: on their own frame over the map, so the ones near an edge aren't cut off.
    local over = CreateFrame("Frame", nil, body)
    over:SetAllPoints(holder)
    over:SetFrameLevel(holder:GetFrameLevel() + 5)
    local here = {}
    for i, p in ipairs(PLACES) do
      if p.pin and p.pin.map == m.id then
        here[#here + 1] = { index = i, x = p.pin.x / 100 * width, y = p.pin.y / 100 * MAP_HEIGHT }
      end
    end
    local groups = {}
    for _, spot in ipairs(here) do
      local into
      for _, g in ipairs(groups) do
        for _, o in ipairs(g) do
          if math.abs(o.x - spot.x) < NEAR and math.abs(o.y - spot.y) < NEAR then into = g end
        end
        if into then break end
      end
      if into then into[#into + 1] = spot else groups[#groups + 1] = { spot } end
    end
    for _, g in ipairs(groups) do
      local cx, cy = 0, 0
      for _, spot in ipairs(g) do cx, cy = cx + spot.x / #g, cy + spot.y / #g end
      for k, spot in ipairs(g) do
        local turn = (#g == 2 and math.pi or -math.pi / 2) + 2 * math.pi * (k - 1) / #g
        local r = #g > 1 and SPREAD or 0
        local p = PLACES[spot.index]
        local color = COLORS[p.kind] or COLORS.dungeon
        local pin = CreateFrame("Button", nil, over)
        pin:SetSize(PIN + 6, PIN + 6)
        pin:SetPoint("CENTER", over, "TOPLEFT", cx + r * math.cos(turn), -(cy + r * math.sin(turn)))
        pin.index = spot.index
        pin.glow = disc(pin, PIN + 7, "BACKGROUND", 1) -- (lit or picked)
        pin.glow:SetColorTexture(1, 0.9, 0.55, 0.9)
        pin.up = disc(pin, PIN + 4, "BORDER", 1) -- (has upgrades)
        pin.up:SetColorTexture(0.25, 0.83, 0.36, 1)
        local edge = disc(pin, PIN, "ARTWORK", 1)
        local fill = disc(pin, PIN - 4, "ARTWORK", 2)
        if p.pin.zone then -- (only its zone is known: hollow)
          edge:SetColorTexture(color[1], color[2], color[3], 1)
          fill:SetColorTexture(0.1, 0.07, 0.04, 0.8)
        else
          edge:SetColorTexture(0.08, 0.05, 0.02, 1)
          fill:SetColorTexture(color[1], color[2], color[3], 1)
        end
        pin:SetScript("OnEnter", function(self)
          pinTooltip(self)
          local row = rowFor(self.index)
          if row then row:LockHighlight() end
        end)
        pin:SetScript("OnLeave", function(self)
          GameTooltip:Hide()
          local row = rowFor(self.index)
          if row then row:UnlockHighlight() end
        end)
        pin:SetScript("OnClick", function(self)
          Journal.PickPlace(self.index)
          Journal.ShowView("bosses")
        end)
        ui.pins[#ui.pins + 1] = pin
      end
    end
    x = x + width
  end
  ui.noArt = text(body, "GameFontDisableSmall", true)
  ui.noArt:SetPoint("BOTTOMLEFT", 6, 6)
  ui.noArt:SetWidth(math.max(x - 12, 100))
  ui.noArt:SetText("The game didn't give its map pictures: the pins are where the entrances are.")
  ui.noArt:Hide()

  -- Beside the maps: the place, a key, and what isn't on the map.
  local side = CreateFrame("Frame", nil, body)
  side:SetPoint("TOPLEFT", x + 12, 0)
  side:SetPoint("BOTTOMRIGHT")
  ui.mapName = text(side, "GameFontNormal")
  ui.mapName:SetPoint("TOPLEFT")
  ui.mapName:SetPoint("RIGHT")
  ui.mapFacts = text(side, "GameFontHighlightSmall", true)
  ui.mapFacts:SetPoint("TOPLEFT", ui.mapName, "BOTTOMLEFT", 0, -6)
  ui.mapFacts:SetPoint("RIGHT")
  ui.mapFacts:SetJustifyV("TOP")
  local off = {}
  for _, p in ipairs(PLACES) do
    if not p.pin and not p.later then off[#off + 1] = plain(p.name) end
  end
  local key = text(side, "GameFontDisableSmall", true)
  key:SetPoint("BOTTOMLEFT")
  key:SetPoint("RIGHT")
  key:SetJustifyV("BOTTOM")
  key:SetText("|cffffc74dGold|r: dungeon. |cffeb5c3dRed|r: raid. Hollow: only its zone is known. Green ring: upgrades "
    .. "for your character.\n\nPoint at a place in the list to find it; click a pin to open it.\n\nRaids not released yet "
    .. "aren't on the map." .. (#off > 0 and ("\nNot on the map yet: " .. table.concat(off, ", ") .. ".") or ""))
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
    row.star = G.Items.Star(row, 14)
    row.star:SetPoint("RIGHT", -4, 0)
    row.chance = text(row, "GameFontDisableSmall")
    row.chance:SetPoint("RIGHT", -24, 0)
    row.gain = text(row, "GameFontHighlightSmall")
    row.gain:SetPoint("RIGHT", -62, 0)
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
    row:SetScript("OnClick", function(self) Journal.PickQuest(self.index) end)
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
  -- A chain's steps, a row each (a long one is cut short rather than pushing the rest down).
  ui.chainHeading = text(d, "GameFontNormalSmall")
  ui.chainHeading:SetPoint("TOPLEFT", ui.qFacts, "BOTTOMLEFT", 0, -8)
  ui.chainHeading:SetText("Steps (click one to see it)")
  ui.chainMore = text(d, "GameFontDisableSmall")
  ui.chainMore:SetPoint("LEFT", ui.chainHeading, "RIGHT", 10, 0)
  ui.stepArea = CreateFrame("Frame", nil, d)
  ui.stepArea:SetPoint("TOPLEFT", ui.chainHeading, "BOTTOMLEFT", 0, -3)
  ui.stepArea:SetPoint("RIGHT")
  ui.stepArea:SetHeight(CHAIN_LINES * STEP_HEIGHT)
  wheel(ui.stepArea, function(delta) chainOffset = chainOffset - delta * 2 end)
  ui.stepRows = {}
  for i = 1, CHAIN_LINES do
    local row = rowButton(ui.stepArea, 300, STEP_HEIGHT + 1)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * STEP_HEIGHT)
    row:SetPoint("RIGHT")
    row.level = text(row, "GameFontDisableSmall")
    row.level:SetPoint("RIGHT", -4, 0)
    row.name = text(row, "GameFontHighlightSmall")
    row.name:SetPoint("LEFT", 2, 0)
    row.name:SetPoint("RIGHT", row.level, "LEFT", -4, 0)
    row:SetScript("OnClick", function(self) Journal.PickStep(self.index) end)
    ui.stepRows[i] = row
  end
  ui.sTitle = text(d, "GameFontHighlightSmall")
  ui.sTitle:SetPoint("TOPLEFT", ui.stepArea, "BOTTOMLEFT", 0, -8)
  ui.sTitle:SetPoint("RIGHT")
  -- The quest, or the step shown.
  ui.qHow = text(d, "GameFontHighlightSmall", true)
  ui.qHow:SetPoint("TOPLEFT", ui.qFacts, "BOTTOMLEFT", 0, -8)
  ui.qHow:SetPoint("RIGHT")
  ui.showButton = CreateFrame("Button", nil, d, "UIPanelButtonTemplate")
  ui.showButton:SetSize(170, 20)
  ui.showButton:SetPoint("TOPLEFT", ui.qHow, "BOTTOMLEFT", 0, -6)
  ui.showButton:SetText("Show on map")
  ui.showButton:SetScript("OnClick", function(self) Journal.ShowOnMap(self.target) end)
  G.Tooltip(ui.showButton, "Show on map", "Puts the game's own map pin on where this quest starts, as "
    .. "clicking the world map does. Quests started inside a dungeon or by an item have no pin.")
  ui.qObj = text(d, "GameFontHighlightSmall", true)
  ui.qObj:SetPoint("TOPLEFT", ui.showButton, "BOTTOMLEFT", 0, -8)
  ui.qObj:SetPoint("RIGHT")
  ui.qObj:SetMaxLines(3)
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
    row:SetScript("OnEnter", function(self) -- (on the Map view: lights its pin)
      if view() == "map" then Journal.LightPin(self.index) end
    end)
    row:SetScript("OnLeave", function()
      if lit then Journal.LightPin(nil) end
    end)
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
  ui.who = Upgrades.Menu(detail)
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
  createMap(ui.views.map)
  ui.status = text(detail, "GameFontHighlightSmall", true)
  ui.status:SetPoint("BOTTOMLEFT", 14, 8)
  ui.status:SetPoint("RIGHT", -14, 0)
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
      selected, boss, quest, step, followStep = now, 1, 1, nil, true
      bossOffset, lootOffset, abilityOffset, questOffset, chainOffset = 0, 0, 0, 0, 0
    end
    if ui.panel and ui.panel:IsVisible() then Journal:Refresh() end
  end
end)

function Journal:OnLogin()
  -- What's kept (GargoyleDB.journal): the place last looked at (its id, or the name of one
  -- that has no id yet), the view shown (Bosses, Quests or Map) and the boss's Loot or Abilities.
  local db = GargoyleDB.journal
  if type(db.place) ~= "number" and type(db.place) ~= "string" then db.place = nil end
  if type(db.view) ~= "string" then db.view = nil end
  if type(db.part) ~= "string" then db.part = nil end
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
