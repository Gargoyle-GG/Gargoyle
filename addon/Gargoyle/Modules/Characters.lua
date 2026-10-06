-- Characters: keep the characters you pick up to date on your Gargoyle account.
--
-- Pick a character in this tab. While it's picked, the addon reads it as you play: level,
-- race, talents, equipped gear with enchants, and professions. That goes into
-- GargoyleDB.characters, which the game writes on reload or logout; the Gargoyle app
-- sends it to the website, which makes a Gargoyle character from it the first time and
-- updates that one after (game_import.py). Characters that aren't picked are never read.
--
-- Only the game's ordinary addon functions are used, the ones the character sheet, the
-- talent window and the skills page show. Reading waits a few seconds after a change, and
-- for the end of combat. (Not at logout: by then the game reports no gear.)
local _, ns = ...

local Characters = {
  title = "Characters",
  description = "Keep the characters you pick up to date on your Gargoyle account (level, talents, gear, professions).",
}
ns.RegisterModule("characters", Characters)
ns.Characters = Characters

local DELAY = 3 -- seconds after a change before reading (gear swaps come in bursts)
local RETRIES = 3 -- tries when the game hasn't loaded every equipped item's details yet
local MAX_SKILLS = 80
local EVENTS = { "PLAYER_ENTERING_WORLD", "PLAYER_EQUIPMENT_CHANGED", "CHARACTER_POINTS_CHANGED", "PLAYER_TALENT_UPDATE",
  "TRAIT_CONFIG_UPDATED", "ACTIVE_TALENT_GROUP_CHANGED", "PLAYER_LEVEL_UP", "SKILL_LINES_CHANGED", "PLAYER_REGEN_ENABLED" }
-- Why the website didn't take a character (results from the app; see game_import.py).
local PROBLEMS = {
  limit = "not added: your account has as many characters from the game as it can hold",
  invalid = "not added: the website couldn't read it",
}

local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

-- ---- Reading the character ----

local function spellName(spellID)
  if not spellID or spellID == 0 then return end
  if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(spellID) end
  if GetSpellInfo then return (GetSpellInfo(spellID)) end
end

-- WoW Forever: each class has one talent tree (C_Traits, as Blizzard's talent window reads
-- it), with the classic three trees as groups in it. Each talent: its tree number (the
-- group's place), name, spell and the points spent.
local function readTreeTalents()
  local traits = C_Traits
  local configID = C_ClassTalents and C_ClassTalents.GetActiveConfigID and C_ClassTalents.GetActiveConfigID()
  local config = configID and traits.GetConfigInfo(configID)
  local treeID = config and config.treeIDs and config.treeIDs[1]
  if not treeID then return end
  local groups = traits.GetGroupDisplayInfoByTreeID and traits.GetGroupDisplayInfoByTreeID(treeID) or {}
  table.sort(groups, function(a, b) return (a.orderIndex or 0) < (b.orderIndex or 0) end)
  local tabs = {} -- group id -> tree number
  for i, group in ipairs(groups) do tabs[group.groupID] = i end
  local talents = {}
  for _, nodeID in ipairs(traits.GetTreeNodes(treeID) or {}) do
    local node = traits.GetNodeInfo(configID, nodeID)
    local rank = node and (node.ranksPurchased or node.activeRank) or 0
    if rank > 0 then
      local entryID = (node.activeEntry and node.activeEntry.entryID) or (node.entryIDs and node.entryIDs[1])
      local entry = entryID and traits.GetEntryInfo(configID, entryID)
      local definition = entry and entry.definitionID and traits.GetDefinitionInfo(entry.definitionID)
      local spell = definition and definition.spellID
      local name = definition and ((definition.overrideName ~= "" and definition.overrideName) or spellName(spell))
      local tab
      for _, groupID in ipairs(node.groupIDs or {}) do tab = tab or tabs[groupID] end
      talents[#talents + 1] = { tab = tab, rank = rank, name = name, spell = spell }
    end
  end
  return talents
end

-- Older clients: three talent tabs, each with its talents in rows and columns.
local function readTabTalents()
  local talents = {}
  for tab = 1, GetNumTalentTabs() do
    for index = 1, GetNumTalents(tab) do
      local name, _, row, col, rank = GetTalentInfo(tab, index)
      if type(name) ~= "string" or type(rank) ~= "number" then return end
      if rank > 0 then talents[#talents + 1] = { tab = tab, row = row, col = col, rank = rank, name = name } end
    end
  end
  return talents
end

-- The points spent, talent by talent. Nil if the game doesn't show talents (or hasn't
-- loaded them yet), so the website keeps what it had.
local function readTalents(level)
  local talents
  if C_Traits and C_Traits.GetTreeNodes then
    if C_SpecializationInfo and C_SpecializationInfo.IsInitialized and not C_SpecializationInfo.IsInitialized() then return end
    talents = readTreeTalents()
  elseif GetNumTalentTabs and GetNumTalents and GetTalentInfo then
    talents = readTabTalents()
  end
  -- None spent from level 10 on: most likely not loaded yet.
  if not talents or (#talents == 0 and level >= 10) then return end
  return talents
end

-- Equipped items: slot number, item id and enchant id, from each item's link. Also says
-- whether an item's details weren't loaded yet (it's read again shortly). Nil when nothing
-- is equipped: far more likely the game not showing it than a character with no gear.
local function readGear()
  local gear, missing = {}, false
  for slot = 1, 19 do
    local link = GetInventoryItemLink("player", slot)
    local item, enchant
    if type(link) == "string" then
      item, enchant = link:match("item:(%d+):(%d*)")
    end
    item, enchant = tonumber(item), tonumber(enchant)
    if item then
      gear[#gear + 1] = { slot = slot, item = item, enchant = enchant ~= 0 and enchant or nil }
    elseif GetInventoryItemID and GetInventoryItemID("player", slot) then
      missing = true
    end
  end
  return #gear > 0 and gear or nil, missing
end

-- Skills with their level (the website keeps only the professions). Nil if a group of
-- skills is folded away on the skills page, so the website keeps what it had.
local function readSkills()
  local skills = {}
  if GetNumSkillLines and GetSkillLineInfo then
    for i = 1, GetNumSkillLines() do
      local name, isHeader, isExpanded, rank = GetSkillLineInfo(i)
      if isHeader and not isExpanded then return end
      if type(name) == "string" and not isHeader and type(rank) == "number" and rank > 0 and #skills < MAX_SKILLS then
        skills[#skills + 1] = { name = name, rank = rank }
      end
    end
    return #skills > 0 and skills or nil -- (every character has some skills: none means not loaded)
  elseif GetProfessions and GetProfessionInfo then
    local indexes = { GetProfessions() } -- (with gaps where there's no profession)
    for i = 1, 6 do
      if indexes[i] then
        local name, _, rank = GetProfessionInfo(indexes[i])
        if type(name) == "string" and type(rank) == "number" and rank > 0 then
          skills[#skills + 1] = { name = name, rank = rank }
        end
      end
    end
    return skills
  end
end

-- Everything the website uses, as the game shows it now. Each part is read on its own:
-- one that fails is left out (and kept as it was on the website) without stopping the rest.
function Characters.Read()
  local raceName, raceFile = UnitRace("player")
  local _, classFile = UnitClass("player")
  local level = UnitLevel("player") or 0
  local character = {
    name = ns.PlayerName(), class = classFile, race = raceFile, race_name = raceName,
    faction = UnitFactionGroup("player"), level = level, at = time(),
  }
  local ok, talents = pcall(readTalents, level)
  character.talents = ok and talents or nil
  local gearOk, gear, missing = pcall(readGear)
  character.gear = gearOk and gear or nil
  local skillsOk, skills = pcall(readSkills)
  character.skills = skillsOk and skills or nil
  return character, gearOk and missing
end

-- ---- Picking ----

function Characters.Entry(key)
  local entry = key and GargoyleDB.characters[key]
  if type(entry) == "table" and type(entry.picked) == "number" then return entry end
end

local retries = 0

local function same(a, b)
  if type(a) ~= "table" or type(b) ~= "table" then return a == b end
  for k, v in pairs(a) do
    if not same(v, b[k]) then return false end
  end
  for k in pairs(b) do
    if a[k] == nil then return false end
  end
  return true
end

-- Read the character you're playing into GargoyleDB, if it's picked. A part the game didn't
-- show this time stays as it was. If nothing changed, it keeps the time it was last read,
-- so there's nothing new for the app to send.
function Characters.Save()
  local key = ns.PlayerKey()
  local entry = Characters.Entry(key)
  if not entry then return end
  local character, missing = Characters.Read()
  character.picked = entry.picked
  for _, part in ipairs({ "talents", "gear", "skills" }) do
    if character[part] == nil then character[part] = entry[part] end
  end
  local at = character.at
  character.at = entry.at
  if not (entry.at and same(character, entry)) then character.at = at end
  GargoyleDB.characters[key] = character
  if missing and retries < RETRIES and C_Timer then
    retries = retries + 1
    C_Timer.After(5, Characters.Save)
  end
end

function Characters.Pick(on)
  local key = ns.PlayerKey()
  if not key then return end
  if on then
    GargoyleDB.characters[key] = { picked = time() }
    Characters.Save()
  else
    GargoyleDB.characters[key] = nil
  end
end

-- The website's copy of a picked character (from the app), if it has one.
function Characters.OnWebsite(key)
  for _, c in ipairs(ns.sync.characters) do
    if c.game == key then return c end
  end
end

-- What became of a picked character on its way to the website: "saved" (the website has
-- it as it is now), "problem" (it said no) or "waiting". Also the website's copy, if any.
function Characters.State(key, entry)
  local website = Characters.OnWebsite(key)
  if website and website.read and entry.at and website.read >= entry.at then return "saved", website end
  if not website and PROBLEMS[ns.sync.imports[key]] then return "problem", website end
  return "waiting", website
end

function Characters.Status(key, entry)
  local state, website = Characters.State(key, entry)
  if state == "saved" then return "|cff40c040On your Gargoyle account|r" end
  if state == "problem" then return "|cffe05050" .. PROBLEMS[ns.sync.imports[key]] .. "|r" end
  return website and "|cffe0c040Changes waiting to sync|r" or "|cffe0c040Waiting to sync|r"
end

function Characters.Waiting()
  local n = 0
  for key, entry in pairs(GargoyleDB.characters) do
    if Characters.Entry(key) and Characters.State(key, entry) == "waiting" then n = n + 1 end
  end
  if n == 1 then return "1 character" end
  if n > 1 then return n .. " characters" end
end

-- At login: let go of characters deleted on the website (unless picked again since), and
-- of anything odd in the saved file.
function Characters:OnLogin()
  for key, entry in pairs(GargoyleDB.characters) do
    if type(key) ~= "string" or type(entry) ~= "table" or type(entry.picked) ~= "number" then
      GargoyleDB.characters[key] = nil
    else
      local removed = ns.sync.removed[key]
      if removed and removed >= entry.picked then
        GargoyleDB.characters[key] = nil
        ns.say(string.format("%s was deleted from your Gargoyle account, so it's no longer kept up to date there. "
          .. "Pick it again in the Characters tab to bring it back.", plain(entry.name or "A character")))
      end
    end
  end
end

-- ---- Watching for changes ----

local watcher = CreateFrame("Frame")
local scheduled, afterCombat = false, false

local function readSoon()
  if scheduled or not C_Timer then return end
  scheduled = true
  C_Timer.After(DELAY, function()
    scheduled = false
    if InCombatLockdown and InCombatLockdown() then
      afterCombat = true
    else
      Characters.Save()
      if Characters.Refresh then Characters:Refresh() end
    end
  end)
end

watcher:SetScript("OnEvent", function(_, event)
  if event == "PLAYER_REGEN_ENABLED" then
    if afterCombat then
      afterCombat = false
      readSoon()
    end
  else
    readSoon()
  end
end)

function Characters:OnEnable()
  for _, event in ipairs(EVENTS) do
    pcall(watcher.RegisterEvent, watcher, event) -- (one this version of the game doesn't have is skipped)
  end
  readSoon()
end

function Characters:OnDisable()
  watcher:UnregisterAllEvents()
end

-- ---- The tab ----

local ROWS, ROW_HEIGHT = 8, 26
local ui = {}

local function className(classFile)
  local name = classFile and LOCALIZED_CLASS_NAMES_MALE and LOCALIZED_CLASS_NAMES_MALE[classFile]
  return name or (classFile or ""):lower()
end

local function describe(entry)
  return string.format("Level %s %s", tostring(entry.level or "?"), plain(className(entry.class)))
end

local function classColor(classFile)
  local color = RAID_CLASS_COLORS and RAID_CLASS_COLORS[classFile or ""]
  return color and color.colorStr and ("|c" .. color.colorStr) or "|cffffffff"
end

local function classIcon(classFile, size)
  local name = type(classFile) == "string" and classFile:match("^%a+$")
  return name and ns.Icon("classicon-" .. name:lower(), size) or ""
end

function Characters:Refresh()
  if not ui.name then return end
  if ns.UpdateStatus then ns.UpdateStatus() end
  local key = ns.PlayerKey()
  local entry = Characters.Entry(key)
  local _, classFile = UnitClass("player")
  if SetPortraitTexture then SetPortraitTexture(ui.portrait, "player") end
  ui.name:SetText(plain(ns.PlayerName()))
  ui.level:SetText(describe({ level = UnitLevel("player"), class = classFile }))
  if not key then
    ui.status:SetText("The game didn't say who you're playing. Try again after a reload.")
  elseif entry then
    ui.status:SetText(Characters.Status(key, entry))
  else
    ui.status:SetText("Not on your Gargoyle account.")
  end
  ui.pick:SetText(entry and "Stop keeping it up to date" or "Keep it up to date")
  ui.pick:SetEnabled(key ~= nil)

  local picked = {}
  for k, e in pairs(GargoyleDB.characters) do
    if Characters.Entry(k) then picked[#picked + 1] = { key = k, entry = e } end
  end
  table.sort(picked, function(a, b) return tostring(a.entry.name):lower() < tostring(b.entry.name):lower() end)
  for i, row in ipairs(ui.rows) do
    local p = picked[i]
    row:SetShown(p ~= nil)
    if p then
      local e = p.entry
      row.name:SetText(string.format("%s %s%s|r   |cffb0b0b0%s|r", classIcon(e.class, 16), classColor(e.class),
        plain(e.name or "?"), describe(e)))
      row.status:SetText(Characters.Status(p.key, e))
    end
  end
  ui.more:SetText(#picked > ROWS and string.format("and %d more", #picked - ROWS) or "")
  ui.none:SetShown(#picked == 0)
end

function Characters:CreatePanel(panel)
  -- Top: the character you're playing.
  local card = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  card:SetPoint("TOPLEFT")
  card:SetPoint("TOPRIGHT")
  card:SetHeight(150)
  ui.portrait = card:CreateTexture(nil, "ARTWORK")
  ui.portrait:SetSize(60, 60)
  ui.portrait:SetPoint("TOPLEFT", 16, -14)
  ui.pick = CreateFrame("Button", nil, card, "UIPanelButtonTemplate")
  ui.pick:SetSize(230, 24)
  ui.pick:SetPoint("TOPRIGHT", -16, -18)
  ui.pick:SetScript("OnClick", function()
    local picking = not Characters.Entry(ns.PlayerKey())
    Characters.Pick(picking)
    if picking and not Characters.toldAboutSync then
      Characters.toldAboutSync = true
      ns.say("this character is sent to your Gargoyle account the next time you reload (Reload UI) or log out, "
        .. "with the Gargoyle app running.")
    end
    Characters:Refresh()
  end)
  local function text(font, anchor, gap)
    local fs = card:CreateFontString(nil, "ARTWORK", font)
    fs:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, -gap)
    fs:SetPoint("RIGHT", ui.pick, "LEFT", -12, 0)
    fs:SetJustifyH("LEFT")
    return fs
  end
  ui.name = card:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  ui.name:SetPoint("TOPLEFT", ui.portrait, "TOPRIGHT", 14, -4)
  ui.name:SetPoint("RIGHT", ui.pick, "LEFT", -12, 0)
  ui.name:SetJustifyH("LEFT")
  ui.level = text("GameFontHighlight", ui.name, 4)
  ui.status = text("GameFontHighlight", ui.level, 6)
  local about = card:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  about:SetPoint("TOPLEFT", ui.portrait, "BOTTOMLEFT", 0, -14)
  about:SetPoint("RIGHT", -16, 0)
  about:SetJustifyH("LEFT")
  about:SetText("While it's kept up to date, this character's level, race, talents, gear, enchants and professions are "
    .. "read as you play. The Gargoyle app sends them to your account when you reload or log out, and it updates the "
    .. "same character there each time. Stopping leaves it on your account as it last was.")

  -- Below: every character picked on this game account.
  local list = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  list:SetPoint("TOPLEFT", card, "BOTTOMLEFT", 0, -6)
  list:SetPoint("BOTTOMRIGHT")
  local heading = list:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  heading:SetPoint("TOPLEFT", 12, -10)
  heading:SetText("Kept up to date (characters on this game account)")
  ui.more = list:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  ui.more:SetPoint("TOPRIGHT", -12, -12)
  ui.none = list:CreateFontString(nil, "ARTWORK", "GameFontDisable")
  ui.none:SetPoint("TOPLEFT", heading, "BOTTOMLEFT", 0, -10)
  ui.none:SetText("None yet.")
  ui.rows = {}
  for i = 1, ROWS do
    local row = CreateFrame("Frame", nil, list)
    row:SetHeight(ROW_HEIGHT)
    row:SetPoint("TOPLEFT", 6, -32 - (i - 1) * ROW_HEIGHT)
    row:SetPoint("RIGHT", -6, 0)
    if i % 2 == 0 then -- (faint stripes, as in the game's lists)
      local stripe = row:CreateTexture(nil, "BACKGROUND")
      stripe:SetAllPoints()
      stripe:SetColorTexture(1, 1, 1, 0.04)
    end
    row.status = row:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    row.status:SetPoint("RIGHT", -8, 0)
    row.status:SetJustifyH("RIGHT")
    row.name = row:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    row.name:SetPoint("LEFT", 8, 0)
    row.name:SetPoint("RIGHT", row.status, "LEFT", -10, 0)
    row.name:SetJustifyH("LEFT")
    row.name:SetWordWrap(false)
    ui.rows[i] = row
  end
end
