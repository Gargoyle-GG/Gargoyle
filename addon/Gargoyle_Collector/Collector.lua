-- Gargoyle Data Collector, for Gargoyle's helpers: notes what the game shows you about items,
-- spells and talents, so gargoyle.gg's database can be kept up to date with the game as it is.
--
-- What it notes, all from the game's own addon functions, as the game shows them to you:
--   Items: the ones you come across (worn, in your bags or bank, sold by a vendor, in a loot
--     window, offered by a quest, or under your mouse): name, quality, level, slot, stats and
--     the tooltip's lines.
--   Spells: your spellbook, the spells a trainer offers (with the level and cost), and spells
--     whose tooltip you look at: name, rank, text, cast time, cost, range and cooldown.
--   Talents: your class's whole talent tree: every talent with each rank's text, where it
--     sits, and what it needs.
-- Nothing about you or other players is noted but your class (for its talents and spells).
--
-- Kept light and polite: it only reads what the game has already shown you or is loading to
-- show you (it never runs through item or spell numbers, which would make the game ask the
-- server for each one); it reads a few things at a time, never in combat; and anything it
-- has noted in this version of the game isn't read again. When the game is patched it
-- checks things again as you see them, and keeps only what changed.
--
-- It saves to GargoyleCollectorDB, which the game writes on reload or logout. Nothing leaves
-- your PC unless you press "Send collected data" in the Gargoyle app, which sends it to
-- gargoyle.gg for review. Once it's been sent, the app says so in Gargoyle_Sync and what was
-- sent is cleared at the next login. It's turned on or off in Gargoyle's options (Options >
-- AddOns > Gargoyle), which use On() and SetOn() below.
local ADDON = ...

GargoyleCollector = {}
local C = GargoyleCollector

local KINDS = { "items", "spells", "talents", "trainers" }
-- How much it keeps before it's sent (each kind): beyond this it waits for the app to send it.
local LIMITS = { items = 4000, spells = 3000, talents = 20, trainers = 2000 }
local MAX_QUEUE = 400 -- things waiting to be read (more are picked up when seen again)
local MAX_LOADING = 20 -- items being loaded by the game at once
local PER_STEP = 6 -- things read per step...
local STEP = 0.1 -- ...a step every tenth of a second...
local BUDGET_MS = 4 -- ...and a step stops early after this long
local MAX_LINES, MAX_TEXT = 30, 300
local EQUIPPED = 19
local BANK = -1

local db, build
local counts = {}
local jobs, head, tail = {}, 1, 0
local queued, loading, loadingCount = {}, {}, 0
local stepping, pending = false, {}
local events = CreateFrame("Frame")

-- ---- Small helpers ----

-- The game's values can be "secret" (hidden from addons) in some situations: then they're left out.
local function secret(v)
  return issecretvalue and issecretvalue(v)
end

local function number(v)
  if type(v) == "number" and v == v and not secret(v) then return v end
end

-- Text cut to `limit` letters (not bytes: a cut inside an accented letter would break it).
local function text(v, limit)
  if type(v) ~= "string" or v == "" or secret(v) then return nil end
  limit = limit or MAX_TEXT
  if #v <= limit then return v end
  local letters, i = 0, 1
  while i <= #v do
    letters = letters + 1
    if letters > limit then return v:sub(1, i - 1) end
    local byte = v:byte(i)
    i = i + (byte >= 240 and 4 or byte >= 224 and 3 or byte >= 192 and 2 or 1)
  end
  return v
end

local function itemID(link)
  return type(link) == "string" and not secret(link) and tonumber(link:match("item:(%d+)")) or nil
end

-- A number for what an entry says, to tell whether it changed (its time and game version aside).
local function checksum(value, acc)
  acc = acc or 0
  if type(value) == "table" then
    local keys = {}
    for k in pairs(value) do
      if k ~= "seen" and k ~= "build" then keys[#keys + 1] = k end
    end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for _, k in ipairs(keys) do acc = checksum(value[k], checksum(k, acc)) end
    return acc
  end
  local s = tostring(value)
  for i = 1, #s do acc = (acc * 31 + s:byte(i)) % 2147483629 end
  return (acc * 31 + 7) % 2147483629
end

-- A tooltip line's color, when it means something: green (Equip, Use and set bonuses that
-- apply), grey (set bonuses that don't yet), gold (flavor text, set names). Red and white
-- are left out: those depend on who's looking.
local function colorOf(color)
  local r, g, b = number(color and color.r), number(color and color.g), number(color and color.b)
  if not (r and g and b) then return nil end
  if g > 0.9 and r < 0.2 and b < 0.2 then return "green" end
  if math.abs(r - g) < 0.05 and math.abs(g - b) < 0.05 and r > 0.4 and r < 0.7 then return "grey" end
  if r > 0.9 and g > 0.7 and g < 0.9 and b < 0.2 then return "gold" end
end

-- A tooltip's lines, as the game's tooltip data has them ({ left, right, color }), without
-- showing a tooltip (so no other addon's additions get in).
local function lines(data)
  if type(data) ~= "table" or type(data.lines) ~= "table" then return nil end
  local out = {}
  for _, line in ipairs(data.lines) do
    if #out == MAX_LINES then break end
    if type(line) == "table" then
      if line.leftText == nil and type(line.args) == "table" then -- (older tooltip data: the values in args)
        for _, arg in ipairs(line.args) do
          if type(arg) == "table" and type(arg.field) == "string" and line[arg.field] == nil then
            line[arg.field] = arg.stringVal or arg.colorVal or arg.intVal
          end
        end
      end
      local left, right = text(line.leftText), text(line.rightText)
      if left or right then out[#out + 1] = { left = left, right = right, color = colorOf(line.leftColor) } end
    end
  end
  return #out > 0 and out or nil
end

local function tooltip(getter, ...)
  local get = C_TooltipInfo and C_TooltipInfo[getter]
  if not get then return nil end
  local ok, data = pcall(get, ...)
  return ok and lines(data) or nil
end

local function playerClass()
  local _, class = UnitClass("player")
  return text(class, 20)
end

-- ---- Saved data ----

local function tableOr(v)
  return type(v) == "table" and v or {}
end

local function newID()
  local parts = {}
  for i = 1, 4 do parts[i] = string.format("%04x", math.random(0, 65535)) end
  return table.concat(parts)
end

-- Anything odd in the saved file (edited by hand, an older version) starts afresh.
local function loadDB()
  local saved = tableOr(GargoyleCollectorDB)
  if saved.v ~= 1 then saved = { on = saved.on } end
  saved.v = 1
  if type(saved.id) ~= "string" or not saved.id:match("^%x+$") or #saved.id > 20 then saved.id = newID() end
  saved.sums = tableOr(saved.sums)
  saved.checked = tableOr(saved.checked)
  local _, gameBuild = GetBuildInfo()
  build = tonumber(gameBuild) or 0
  if saved.checked.build ~= build then saved.checked = { build = build } end -- (a new version of the game: look again)
  for _, kind in ipairs(KINDS) do
    saved[kind] = tableOr(saved[kind])
    saved.sums[kind] = tableOr(saved.sums[kind])
    saved.checked[kind] = tableOr(saved.checked[kind])
    queued[kind] = {}
  end
  -- What the app has sent already (Gargoyle_Sync: the newest entry it sent from this file):
  -- cleared, though its checksums stay, so it isn't noted again unless it changes. (Nothing
  -- is noted in the same second as the game saving: it saves at logout or a reload, and
  -- noting starts a few seconds after logging in.)
  local sync = type(GargoyleSync) == "table" and type(GargoyleSync.collected) == "table" and GargoyleSync.collected
  local sent = sync and number(sync[saved.id])
  for _, kind in ipairs(KINDS) do
    local count = 0
    for key, entry in pairs(saved[kind]) do
      if type(entry) ~= "table" or (sent and number(entry.seen) and entry.seen <= sent) then
        saved[kind][key] = nil
      else
        count = count + 1
      end
    end
    counts[kind] = count
  end
  GargoyleCollectorDB = saved
  db = saved
end

function C.On()
  return not (type(GargoyleCollectorDB) == "table" and GargoyleCollectorDB.on == false)
end

-- Notes an entry, unless it's what was noted last time. False if there's no room left.
local function record(kind, key, entry)
  local sum = checksum(entry)
  if db.sums[kind][key] ~= sum then
    if not db[kind][key] then
      if counts[kind] >= LIMITS[kind] then
        C.full = true
        return false
      end
      counts[kind] = counts[kind] + 1
    end
    entry.seen, entry.build = time(), build
    db[kind][key] = entry
    db.sums[kind][key] = sum
  end
  db.checked[kind][key] = true
  return true
end

-- ---- Reading things ----

local function getItemInfo(id)
  if C_Item and C_Item.GetItemInfo then return C_Item.GetItemInfo(id) end
  if GetItemInfo then return GetItemInfo(id) end
end

-- "loading" while the game is still loading it (it's read once that's done).
local function readItem(id)
  local name, link, quality, ilvl, required, _, _, stack, slot, icon, price, classID, subclassID, bind, _, setID = getItemInfo(id)
  if not text(name) then
    if loading[id] or loadingCount >= MAX_LOADING or not (Item and Item.CreateFromItemID) then return "loading" end
    loading[id], loadingCount = true, loadingCount + 1
    local function done()
      if loading[id] then loading[id], loadingCount = nil, loadingCount - 1 end
    end
    Item:CreateFromItemID(id):ContinueOnItemLoad(function()
      done()
      C.Want("items", id)
    end)
    C_Timer.After(60, done) -- (one the game never finishes loading doesn't hold up the rest)
    return "loading"
  end
  local entry = {
    name = text(name, 100), quality = number(quality), ilvl = number(ilvl), required = number(required),
    stack = number(stack), slot = text(slot, 40), icon = number(icon), price = number(price),
    class = number(classID), subclass = number(subclassID), bind = number(bind), set = number(setID),
    lines = tooltip("GetItemByID", id),
  }
  local getStats = (C_Item and C_Item.GetItemStats) or GetItemStats
  local ok, stats = false, nil
  if getStats and type(link) == "string" then ok, stats = pcall(getStats, link) end
  if ok and type(stats) == "table" then
    entry.stats = {}
    for stat, value in pairs(stats) do
      if text(stat, 60) and number(value) then entry.stats[stat] = value end
    end
  end
  return entry
end

local function spellCall(modern, older, ...)
  local fn = (C_Spell and C_Spell[modern]) or (older and _G[older])
  if not fn then return nil end
  local ok, a, b = pcall(fn, ...)
  if ok then return a, b end
end

local function readSpell(id)
  local info = C_Spell and C_Spell.GetSpellInfo and C_Spell.GetSpellInfo(id)
  local name, icon, cast, minRange, maxRange
  if type(info) == "table" then
    name, icon, cast, minRange, maxRange = info.name, info.iconID, info.castTime, info.minRange, info.maxRange
  elseif GetSpellInfo then
    local _
    name, _, icon, cast, minRange, maxRange = GetSpellInfo(id)
  end
  name = text(name, 100) or text(spellCall("GetSpellName", nil, id), 100)
  if not name then return nil end -- (not a spell)
  local description = text(spellCall("GetSpellDescription", "GetSpellDescription", id), 1000)
  if not description and C_Spell and C_Spell.IsSpellDataCached and not C_Spell.IsSpellDataCached(id)
      and Spell and Spell.CreateFromSpellID and not loading["spell" .. id] then
    loading["spell" .. id] = true -- (its text isn't loaded yet: read it again once it is)
    Spell:CreateFromSpellID(id):ContinueOnSpellLoad(function() C.Want("spells", id) end)
    return "loading"
  end
  local entry = {
    name = name, rank = text(spellCall("GetSpellSubtext", "GetSpellSubtext", id), 60), description = description,
    icon = number(icon), cast = number(cast), minRange = number(minRange), maxRange = number(maxRange),
    passive = spellCall("IsSpellPassive", "IsPassiveSpell", id) == true or nil,
    level = number(spellCall("GetSpellLevelLearned", "GetSpellLevelLearned", id)),
    lines = tooltip("GetSpellByID", id),
  }
  local cooldown, gcd = spellCall("GetSpellBaseCooldown", "GetSpellBaseCooldown", id)
  entry.cooldown, entry.gcd = number(cooldown), number(gcd)
  local costs = spellCall("GetSpellPowerCost", "GetSpellPowerCost", id)
  for _, cost in ipairs(type(costs) == "table" and costs or {}) do
    if type(cost) == "table" then
      entry.costs = entry.costs or {}
      entry.costs[#entry.costs + 1] = { type = number(cost.type), name = text(cost.name, 30), cost = number(cost.cost),
        min = number(cost.minCost), percent = number(cost.costPercent), perSecond = number(cost.costPerSec) }
    end
  end
  return entry
end

-- The class's talent tree, whole: its groups (the classic three trees), and every talent
-- with where it sits, its arrows, what it needs, and each rank's text.
local function readTalents()
  local traits = C_Traits
  local configID = C_ClassTalents and C_ClassTalents.GetActiveConfigID and C_ClassTalents.GetActiveConfigID()
  local config = configID and traits and traits.GetConfigInfo(configID)
  local treeID = config and type(config.treeIDs) == "table" and config.treeIDs[1]
  if not number(treeID) then return nil end
  local tree = { tree = treeID, groups = {}, gates = {}, nodes = {} }
  for _, group in ipairs(traits.GetGroupDisplayInfoByTreeID and traits.GetGroupDisplayInfoByTreeID(treeID) or {}) do
    tree.groups[#tree.groups + 1] = { id = number(group.groupID), order = number(group.orderIndex), name = text(group.name, 60) }
  end
  local treeInfo = traits.GetTreeInfo and traits.GetTreeInfo(configID, treeID)
  for _, gate in ipairs(type(treeInfo) == "table" and type(treeInfo.gates) == "table" and treeInfo.gates or {}) do
    local condition = traits.GetConditionInfo and number(gate.conditionID) and traits.GetConditionInfo(configID, gate.conditionID)
    tree.gates[#tree.gates + 1] = { node = number(gate.topLeftNodeID), spent = number(condition and condition.spentAmountRequired) }
  end
  for _, nodeID in ipairs(traits.GetTreeNodes(treeID) or {}) do
    local node = traits.GetNodeInfo(configID, nodeID)
    if type(node) == "table" then
      local entry = { id = nodeID, x = number(node.posX), y = number(node.posY), max = number(node.maxRanks),
                      groups = {}, arrows = {}, needs = {}, talents = {} }
      for _, groupID in ipairs(type(node.groupIDs) == "table" and node.groupIDs or {}) do
        entry.groups[#entry.groups + 1] = number(groupID)
      end
      for _, edge in ipairs(type(node.visibleEdges) == "table" and node.visibleEdges or {}) do
        entry.arrows[#entry.arrows + 1] = number(type(edge) == "table" and edge.targetNode)
      end
      for _, conditionID in ipairs(type(node.conditionIDs) == "table" and node.conditionIDs or {}) do
        local condition = traits.GetConditionInfo and number(conditionID) and traits.GetConditionInfo(configID, conditionID)
        if type(condition) == "table" then
          entry.needs[#entry.needs + 1] = { spent = number(condition.spentAmountRequired), group = number(condition.traceGroupID) }
        end
      end
      for _, entryID in ipairs(type(node.entryIDs) == "table" and node.entryIDs or {}) do
        local info = traits.GetEntryInfo(configID, entryID)
        local definition = type(info) == "table" and number(info.definitionID) and traits.GetDefinitionInfo(info.definitionID)
        local spell = type(definition) == "table" and number(definition.spellID)
        local talent = { id = entryID, spell = spell, max = number(info and info.maxRanks) or entry.max, ranks = {},
          name = text(definition and definition.overrideName, 100) or text(spell and spellCall("GetSpellName", nil, spell), 100),
          icon = number(definition and definition.overrideIcon) or number(spell and spellCall("GetSpellTexture", "GetSpellTexture", spell)) }
        for rank = 1, math.min(talent.max or 1, 10) do
          local description = traits.GetTraitDescription and text(traits.GetTraitDescription(entryID, rank), 1000)
          if not description then
            local tip = tooltip("GetTraitEntry", entryID, rank)
            description = tip and tip[#tip].left
          end
          talent.ranks[rank] = description or false
        end
        entry.talents[#entry.talents + 1] = talent
        if spell then C.Want("spells", spell) end
      end
      tree.nodes[#tree.nodes + 1] = entry
    end
  end
  return #tree.nodes > 0 and tree or nil
end

-- (No talent tree yet: the game loads it a little after logging in. It's read when it says
-- it has.)
local READ = { items = readItem, spells = readSpell, talents = function() return readTalents() or "loading" end }

-- Reads one thing and notes it. Left unchecked (so it's read when next seen) while it's
-- loading, or when there's no room left.
local function run(kind, key)
  local entry = READ[kind](key)
  if entry == "loading" then return end
  if entry == nil then
    db.checked[kind][key] = true -- (nothing there: not a real item or spell, or no talent tree)
    return
  end
  if kind == "spells" then entry.class = C.spellClass and C.spellClass[key] end
  record(kind, key, entry)
end

-- ---- Reading a few at a time ----

local step

local function schedule()
  if not stepping and head <= tail then
    stepping = true
    C_Timer.After(STEP, step)
  end
end

step = function()
  stepping = false
  if not db or not C.On() then return end
  if InCombatLockdown and InCombatLockdown() then return end -- (PLAYER_REGEN_ENABLED carries on)
  local started = debugprofilestop and debugprofilestop()
  local done = 0
  while head <= tail and done < PER_STEP do
    local job = jobs[head]
    jobs[head], head = nil, head + 1
    queued[job[1]][job[2]] = nil
    pcall(run, job[1], job[2]) -- (a problem with one thing only skips that thing)
    done = done + 1
    if started and debugprofilestop() - started > BUDGET_MS then break end
  end
  if head > tail then head, tail = 1, 0 end
  schedule()
end

-- Something to read (an item or spell id, or a class for its talents), unless it's been
-- read in this version of the game already or is waiting.
function C.Want(kind, key)
  if not db or not C.On() or not queued[kind] then return end
  if kind ~= "talents" then
    key = number(key)
    if not key or key <= 0 or key ~= math.floor(key) then return end
  elseif not key then
    return
  end
  if db.checked[kind][key] or queued[kind][key] or tail - head + 1 >= MAX_QUEUE then return end
  if counts[kind] >= LIMITS[kind] and not db[kind][key] then -- (full: nothing new until it's sent)
    C.full = true
    return
  end
  queued[kind][key] = true
  tail = tail + 1
  jobs[tail] = { kind, key }
  schedule()
end

-- Runs fn after `seconds`, once however often it's asked for meanwhile (the game sends some
-- events in bursts).
local function soon(name, seconds, fn)
  if pending[name] then return end
  pending[name] = true
  C_Timer.After(seconds, function()
    pending[name] = nil
    if db and C.On() then pcall(fn) end
  end)
end

-- ---- Where things are seen ----

local function container(name)
  return (C_Container and C_Container[name]) or _G[name]
end

local function scanBags(bags)
  local slots, idAt = container("GetContainerNumSlots"), container("GetContainerItemID")
  if not (slots and idAt) then return end
  for _, bag in ipairs(bags) do
    for slot = 1, number(slots(bag)) or 0 do C.Want("items", idAt(bag, slot)) end
  end
end

local function carried()
  local bags = {}
  for bag = 0, NUM_BAG_SLOTS or 4 do bags[#bags + 1] = bag end
  scanBags(bags)
end

local function bank()
  local bags = { BANK }
  local first = (NUM_BAG_SLOTS or 4) + 1
  for bag = first, first + (NUM_BANKBAGSLOTS or 6) - 1 do bags[#bags + 1] = bag end
  scanBags(bags)
end

local function equipped()
  for slot = 1, EQUIPPED do C.Want("items", GetInventoryItemID("player", slot)) end
end

local function merchant()
  for i = 1, number(GetMerchantNumItems and GetMerchantNumItems()) or 0 do
    C.Want("items", (GetMerchantItemID and GetMerchantItemID(i)) or itemID(GetMerchantItemLink and GetMerchantItemLink(i)))
  end
end

local function loot()
  for i = 1, number(GetNumLootItems and GetNumLootItems()) or 0 do
    C.Want("items", itemID(GetLootSlotLink and GetLootSlotLink(i)))
  end
end

local function questRewards()
  if not GetQuestItemLink then return end
  for _, kind in ipairs({ { "reward", GetNumQuestRewards }, { "choice", GetNumQuestChoices } }) do
    for i = 1, number(kind[2] and kind[2]()) or 0 do C.Want("items", itemID(GetQuestItemLink(kind[1], i))) end
  end
end

-- Your spellbook's spells (marked with your class: the website sorts out the general ones).
local function spellbook()
  local class = playerClass()
  C.spellClass = C.spellClass or {}
  local function add(id)
    id = number(id)
    if id then
      C.spellClass[id] = class
      C.Want("spells", id)
    end
  end
  if C_SpellBook and C_SpellBook.GetNumSpellBookSkillLines then
    local bank = Enum and Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player or 0
    for line = 1, C_SpellBook.GetNumSpellBookSkillLines() do
      local info = C_SpellBook.GetSpellBookSkillLineInfo(line)
      if type(info) == "table" and number(info.itemIndexOffset) and number(info.numSpellBookItems) then
        for i = info.itemIndexOffset + 1, info.itemIndexOffset + info.numSpellBookItems do
          local item = C_SpellBook.GetSpellBookItemInfo(i, bank)
          add(type(item) == "table" and item.spellID)
        end
      end
    end
  elseif GetNumSpellTabs and GetSpellTabInfo and GetSpellBookItemInfo then
    for tab = 1, GetNumSpellTabs() do
      local _, _, offset, count = GetSpellTabInfo(tab)
      for i = (number(offset) or 0) + 1, (number(offset) or 0) + (number(count) or 0) do
        local kind, id = GetSpellBookItemInfo(i, BOOKTYPE_SPELL or "spell")
        if kind == "SPELL" or kind == "FUTURESPELL" then add(id) end
      end
    end
  end
end

-- A trainer's list: each spell it teaches, with the level it needs and what it costs.
local function trainer()
  if not (GetNumTrainerServices and C_TooltipInfo and C_TooltipInfo.GetTrainerService) then return end
  local class = not (IsTradeskillTrainer and IsTradeskillTrainer()) and playerClass() or nil
  C.spellClass = C.spellClass or {}
  for i = 1, number(GetNumTrainerServices()) or 0 do
    local ok, data = pcall(C_TooltipInfo.GetTrainerService, i)
    local id = ok and type(data) == "table" and number(data.id)
    if id and not db.checked.trainers[id] then
      local name, rank
      if GetTrainerServiceInfo then name, rank = GetTrainerServiceInfo(i) end
      record("trainers", id, { name = text(name, 100), rank = text(rank, 60), class = class,
        level = number(GetTrainerServiceLevelReq and GetTrainerServiceLevelReq(i)),
        cost = number(GetTrainerServiceCost and GetTrainerServiceCost(i)),
        profession = not class or nil })
    end
    if id then
      if class then C.spellClass[id] = class end
      C.Want("spells", id)
    end
  end
end

local function talents()
  C.Want("talents", playerClass())
end

local function everything()
  equipped()
  carried()
  spellbook()
  talents()
end

local EVENTS = {
  PLAYER_EQUIPMENT_CHANGED = function() soon("equipped", 2, equipped) end,
  BAG_UPDATE_DELAYED = function() soon("carried", 2, carried) end,
  BANKFRAME_OPENED = function() soon("bank", 1, bank) end,
  MERCHANT_SHOW = function() soon("merchant", 0.5, merchant) end,
  MERCHANT_UPDATE = function() soon("merchant", 0.5, merchant) end,
  LOOT_OPENED = loot, -- (straight away: the window can be gone in a moment)
  QUEST_DETAIL = questRewards,
  QUEST_COMPLETE = questRewards,
  TRAINER_SHOW = function() soon("trainer", 0.5, trainer) end,
  TRAINER_UPDATE = function() soon("trainer", 0.5, trainer) end,
  SPELLS_CHANGED = function() soon("spellbook", 5, spellbook) end,
  TRAIT_CONFIG_LIST_UPDATED = function() soon("talents", 5, talents) end,
  TRAIT_CONFIG_UPDATED = function() soon("talents", 5, talents) end,
  PLAYER_REGEN_ENABLED = schedule,
}

local function start()
  for event in pairs(EVENTS) do pcall(events.RegisterEvent, events, event) end
  soon("everything", 5, everything)
  schedule()
end

local function stop()
  events:UnregisterAllEvents()
  events:RegisterEvent("PLAYER_LOGIN")
  jobs, head, tail = {}, 1, 0
  for _, kind in ipairs(KINDS) do queued[kind] = {} end
end

function C.SetOn(on)
  if type(GargoyleCollectorDB) ~= "table" then GargoyleCollectorDB = {} end
  GargoyleCollectorDB.on = on and true or false
  if db then
    if on then start() else stop() end
  end
end

-- What's waiting to be sent, for Gargoyle's options.
function C.Summary()
  if not db then return "" end
  local parts = {}
  if counts.items > 0 then parts[#parts + 1] = counts.items .. (counts.items == 1 and " item" or " items") end
  local spells = counts.spells + counts.trainers
  if spells > 0 then parts[#parts + 1] = spells .. (spells == 1 and " spell" or " spells") end
  if counts.talents > 0 then parts[#parts + 1] = "a talent tree" end
  if #parts == 0 then return "Nothing new to send yet." end
  local waiting = table.concat(parts, ", ") .. " waiting to be sent with the Gargoyle app's Send collected data button."
  if C.full then return "Full: " .. waiting .. " Then /reload, and it carries on." end
  return waiting
end

function C.Counts()
  return counts.items or 0, counts.spells or 0, counts.talents or 0, counts.trainers or 0
end

-- Items and spells under your mouse (from the game's tooltip data, so it's what the game has).
if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(_, data)
    if type(data) == "table" then C.Want("items", data.id) end
  end)
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Spell, function(_, data)
    if type(data) == "table" then C.Want("spells", data.id) end
  end)
end

events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", function(_, event, name)
  if event == "ADDON_LOADED" then
    if name == ADDON then loadDB() end
  elseif event == "PLAYER_LOGIN" then
    if db and C.On() then start() end
  elseif EVENTS[event] and db and C.On() then
    EVENTS[event]()
  end
end)
