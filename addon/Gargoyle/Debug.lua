-- /gargoyle debug: asks the game how it shows a few things this addon reads (names,
-- talents, skills) and saves the answers in GargoyleDB.debug, for working out a game
-- version's differences. Read-only: it only calls the game's ordinary "get" functions.
-- The answers are written to the saved file on /reload or logout.
local _, ns = ...

local MAX_FOUND = 150

-- A value as saved data: numbers, text and true/false as they are, anything else described.
local function keep(value)
  local kind = type(value)
  if kind == "number" or kind == "string" or kind == "boolean" then return value end
  if kind == "table" then
    local copy = {}
    for k, v in pairs(value) do
      if type(k) == "string" or type(k) == "number" then
        local vk = type(v)
        if vk == "number" or vk == "string" or vk == "boolean" then copy[k] = v else copy[k] = "<" .. vk .. ">" end
      end
    end
    return copy
  end
  return "<" .. kind .. ">"
end

-- Every value a call returns (nil included), or the error it raised.
local function collect(ok, ...)
  if not ok then return { error = tostring((...)) } end
  local out = { count = select("#", ...) }
  for i = 1, out.count do
    local value = select(i, ...)
    out[i] = value == nil and "<nil>" or keep(value)
  end
  return out
end

local function try(fn, ...)
  if type(fn) ~= "function" then return { missing = true } end
  return collect(pcall(fn, ...))
end

-- Names of functions in a table (one of the game's C_ namespaces).
local function functions(table_)
  local names = {}
  for k, v in pairs(type(table_) == "table" and table_ or {}) do
    if type(k) == "string" and type(v) == "function" then names[#names + 1] = k end
  end
  table.sort(names)
  return names
end

-- Global functions and C_ namespace functions whose name contains one of the words.
local function find(words)
  local found = {}
  local function matches(name)
    local lower = name:lower()
    for _, word in ipairs(words) do
      if lower:find(word, 1, true) then return true end
    end
  end
  for k, v in pairs(_G) do
    if #found >= MAX_FOUND then break end
    if type(k) == "string" then
      if type(v) == "function" and matches(k) then
        found[#found + 1] = k
      elseif type(v) == "table" and k:sub(1, 2) == "C_" then
        for name, fn in pairs(v) do
          if type(name) == "string" and type(fn) == "function" and matches(name) and #found < MAX_FOUND then
            found[#found + 1] = k .. "." .. name
          end
        end
      end
    end
  end
  table.sort(found)
  return found
end

function ns.Debug()
  local spec = C_SpecializationInfo or {}
  local classID = select(3, UnitClass("player"))
  local guid = UnitGUID("player")
  local report = { at = time() }

  report.names = {
    UnitName = try(UnitName, "player"),
    UnitFullName = try(UnitFullName, "player"),
    GetUnitName = try(GetUnitName, "player", true),
    UnitPVPName = try(UnitPVPName, "player"),
    UnitNameUnmodified = try(UnitNameUnmodified, "player"),
    GetPlayerInfoByGUID = try(GetPlayerInfoByGUID, guid),
    ShouldDisplaySurname = try(C_PlayerInfo and C_PlayerInfo.ShouldDisplaySurname),
    C_PlayerInfo = functions(C_PlayerInfo),
    C_NameUtil = functions(C_NameUtil),
    found = find({ "surname", "lastname", "fullname", "secondaryname" }),
  }

  -- Talents, step by step as Modules/Characters.lua reads them (C_Traits).
  local traits = C_Traits or {}
  local configID = C_ClassTalents and C_ClassTalents.GetActiveConfigID and C_ClassTalents.GetActiveConfigID()
  local config = configID and traits.GetConfigInfo and traits.GetConfigInfo(configID)
  local treeID = type(config) == "table" and config.treeIDs and config.treeIDs[1]
  local nodes = treeID and traits.GetTreeNodes and traits.GetTreeNodes(treeID) or {}
  local spent = {}
  for _, nodeID in ipairs(nodes) do
    local node = traits.GetNodeInfo(configID, nodeID)
    if node and (node.ranksPurchased or 0) > 0 and #spent < 12 then
      local entryID = (node.activeEntry and node.activeEntry.entryID) or (node.entryIDs and node.entryIDs[1])
      local entry = entryID and traits.GetEntryInfo(configID, entryID)
      spent[#spent + 1] = { node = keep(node), entry = keep(entry),
                            definition = keep(entry and entry.definitionID and traits.GetDefinitionInfo(entry.definitionID)) }
    end
  end
  local groups = {}
  for _, group in ipairs(treeID and traits.GetGroupDisplayInfoByTreeID and traits.GetGroupDisplayInfoByTreeID(treeID) or {}) do
    groups[#groups + 1] = keep(group)
  end
  report.talents = {
    initialized = try(spec.IsInitialized),
    configID = configID or "<nil>",
    config = keep(config),
    groups = groups,
    nodes = #nodes,
    spent = spent,
    classID = classID or "<nil>",
    globals = { GetTalentInfo = type(GetTalentInfo), GetNumTalentTabs = type(GetNumTalentTabs) },
  }
  -- What the addon itself reads now.
  if ns.Characters and ns.Characters.Read then
    local ok, character = pcall(ns.Characters.Read)
    report.read = ok and { talents = character.talents and #character.talents or "<nil>",
                           gear = character.gear and #character.gear or "<nil>",
                           skills = character.skills and #character.skills or "<nil>" } or tostring(character)
  end

  -- Talent plans (Modules/Talents.lua): the points to spend, the first node as the talent
  -- window shows it, and what the plan finds.
  local window = PlayerSpellsFrame and PlayerSpellsFrame.TalentsFrame
  local currency = try(traits.GetTreeCurrencyInfo, configID, treeID, false)
  if currency.count then
    local ok, list = pcall(traits.GetTreeCurrencyInfo, configID, treeID, false)
    currency = {}
    for _, c in ipairs(ok and type(list) == "table" and list or {}) do currency[#currency + 1] = keep(c) end
  end
  report.plans = {
    currency = currency,
    firstNode = nodes[1] and keep(traits.GetNodeInfo(configID, nodes[1])) or "<none>",
    window = window and { shown = window:IsShown(), config = try(window.GetConfigID, window),
                          enumerate = type(window.EnumerateAllTalentButtons), buttonsParent = window.ButtonsParent ~= nil,
                          background = window.Background ~= nil } or "<not loaded>",
    eventRegistry = type(EventRegistry),
    specGroup = try(spec.GetActiveSpecGroup),
  }
  if ns.Talents then
    local ok, result = pcall(ns.Talents.Progress)
    report.plans.progress = ok and (result and { planned = result.planned, spent = result.spent, now = result.now,
      todo = #result.todo, over = #result.over, missing = #result.missing } or "<no plan>") or tostring(result)
  end

  report.skills = {
    C_SkillInfo = functions(C_SkillInfo),
    lines = try(C_SkillInfo and C_SkillInfo.GetNumSkillLines),
    first = try(C_SkillInfo and C_SkillInfo.GetSkillLineInfo, 1),
    globalLines = type(GetNumSkillLines),
  }

  GargoyleDB.debug = report
  ns.say("checked. /reload (or log out) to save the answers.")
end
