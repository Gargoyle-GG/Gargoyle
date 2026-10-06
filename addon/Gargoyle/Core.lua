-- Gargoyle: the in-game side of the Gargoyle website. Each feature is a module that can
-- be turned on and off (Options > AddOns > Gargoyle).
--
-- Addons can't go online, so website data comes through the Gargoyle app on the
-- player's PC. The app writes a small data addon, Gargoyle_Sync, which the game loads at
-- login or reload (the GargoyleSync table read below). It also reads what this addon
-- saves (GargoyleDB, which the game writes on reload or logout). The window's Reload UI
-- button is the game's /reload.
--
-- Blizzard's add-on rules this follows: free, plain readable code, no ads or links,
-- nothing automated (it shows things and records your clicks), no chat traffic.
local ADDON, ns = ...

ns.modules, ns.moduleOrder = {}, {}

local GOLD = "|cffd4a017"

function ns.say(text)
  print(GOLD .. "Gargoyle|r: " .. text)
end

-- Text typed by other players, shown as it is: "|" starts the game's color, icon and link
-- codes, so it's doubled to show a plain "|".
function ns.Plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

-- The first `limit` letters of a text. (Letters, not bytes: accented letters, other
-- alphabets and emoji take 2 to 4 bytes each, and a cut inside one would break it.)
function ns.Cut(text, limit)
  if #text <= limit then return text end
  local letters, i = 0, 1
  while i <= #text do
    letters = letters + 1
    if letters > limit then return text:sub(1, i - 1) end
    local byte = text:byte(i)
    i = i + (byte >= 240 and 4 or byte >= 224 and 3 or byte >= 192 and 2 or 1)
  end
  return text
end

function ns.Ago(seconds)
  if seconds < 90 then return "just now" end
  if seconds < 5400 then return string.format("%d min ago", math.floor(seconds / 60)) end
  if seconds < 129600 then return string.format("%d hours ago", math.floor(seconds / 3600)) end
  return string.format("%d days ago", math.floor(seconds / 86400))
end

-- An icon from the game's art inside a line of text.
function ns.Icon(atlas, size)
  return atlas and string.format("|A:%s:%d:%d|a", atlas, size, size) or ""
end

-- ---- Modules ----

-- module = { title, description, default (on unless false), OnLogin, OnEnable, OnDisable,
--            CreatePanel(parent) for its tab in the window, Refresh() when shown }
function ns.RegisterModule(key, module)
  module.key = key
  ns.modules[key] = module
  ns.moduleOrder[#ns.moduleOrder + 1] = key
end

function ns.IsEnabled(key)
  local on = GargoyleDB and GargoyleDB.modules[key]
  if on == nil then
    return ns.modules[key].default ~= false
  end
  return on
end

function ns.SetEnabled(key, on)
  local module = ns.modules[key]
  if not module or ns.IsEnabled(key) == on then return end
  GargoyleDB.modules[key] = on
  local hook = on and module.OnEnable or module.OnDisable
  if hook then hook(module) end
  if ns.RefreshWindow then ns.RefreshWindow() end
end

-- ---- Saved data ----

-- Anything odd in the saved file (edited by hand, an older version) starts afresh.
local function tableOr(value)
  return type(value) == "table" and value or {}
end

local function loadDB()
  local db = tableOr(GargoyleDB)
  db.modules = tableOr(db.modules)
  db.outbox = tableOr(db.outbox)
  db.newRaids = tableOr(db.newRaids) -- raids made in game by officers, waiting to sync
  db.characters = tableOr(db.characters)
  -- (db.calendar: false when Gargoyle's raids are kept off the game's calendar)
  db.minimap = tableOr(db.minimap) -- the minimap button: angle (degrees), hide
  -- Raid alerts (Modules/RaidAlerts.lua): newRaids, reminders (false = off), and the raids
  -- seen, told about and reminded of (raid id -> its start time).
  db.alerts = tableOr(db.alerts)
  for _, name in ipairs({ "seen", "told", "reminded" }) do db.alerts[name] = tableOr(db.alerts[name]) end
  GargoyleDB = db
end

local function usable(value)
  if issecretvalue and issecretvalue(value) then return nil end -- (hidden from addons)
  if type(value) == "string" and value ~= "" then return value end
end

-- The name of the character you're playing. WoW Forever gives the surname as UnitName's
-- second value ("Zyzx", "Alpha"): the full name is both.
function ns.PlayerName()
  local first, surname = UnitName("player")
  first, surname = usable(first), usable(surname)
  return first and surname and (first .. " " .. surname) or first
end

-- The character you're playing, as the game identifies it (its GUID; its name if the game
-- won't say). Nil if neither is available.
function ns.PlayerKey()
  local guid = usable(UnitGUID and UnitGUID("player"))
  if guid then return guid end
  local name = ns.PlayerName()
  return name and ("name:" .. name)
end

-- ---- Data from the Gargoyle app ----

-- GargoyleSync is written by the app from website data (helper/sync_file.py). It's read
-- defensively all the same: wrong types are skipped and text is cut to length, so a bad
-- file can only mean less to show, never an error.
local function text(value, limit)
  if type(value) == "string" then return ns.Cut(value, limit) end
end

local function number(value)
  if type(value) == "number" and value == value then return value end
end

local function list(value)
  return type(value) == "table" and value or {}
end

local function readSignup(raw)
  if type(raw) ~= "table" or not text(raw.name, 60) then return end
  return {
    name = text(raw.name, 60), class = text(raw.class, 20) or "", role = text(raw.role, 10) or "dps",
    status = text(raw.status, 10) or "", note = text(raw.note, 200) or "",
    mine = raw.mine == true, character = number(raw.character), changed = number(raw.changed),
  }
end

local function readRaid(raw, guild)
  if type(raw) ~= "table" or not number(raw.id) or not number(raw.start) then return end
  local raid = {
    id = raw.id, title = text(raw.title, 80) or "Raid", start = raw.start, size = number(raw.size),
    notes = text(raw.notes, 1000) or "", guild = guild, signups = {},
  }
  for _, s in ipairs(list(raw.signups)) do
    raid.signups[#raid.signups + 1] = readSignup(s)
  end
  return raid
end

function ns.ReadSync()
  local sync = { characters = {}, guilds = {}, done = {}, removed = {}, imports = {} }
  local raw = GargoyleSync
  if type(raw) ~= "table" or raw.version ~= 1 then return sync end
  sync.loaded = true
  sync.synced, sync.user = number(raw.synced), text(raw.user, 60)
  sync.makesRaids = raw.can_make_raids == true -- (the app sends raids made in game; older ones don't)
  for _, c in ipairs(list(raw.characters)) do
    if type(c) == "table" and number(c.id) and text(c.name, 60) then
      sync.characters[#sync.characters + 1] = {
        id = c.id, name = text(c.name, 60), class = text(c.class, 20) or "", guild = number(c.guild),
        role = text(c.role, 10), game = text(c.game, 80), read = number(c.read),
      }
    end
  end
  for _, g in ipairs(list(raw.guilds)) do
    if type(g) == "table" and number(g.id) and text(g.name, 60) then
      local guild = { id = g.id, name = text(g.name, 60), gameName = text(g.game, 60), officer = g.officer == true, raids = {} }
      for _, r in ipairs(list(g.raids)) do
        guild.raids[#guild.raids + 1] = readRaid(r, guild)
      end
      sync.guilds[#sync.guilds + 1] = guild
    end
  end
  for id, result in pairs(list(raw.done)) do
    if type(id) == "string" and type(result) == "string" then sync.done[id] = result end
  end
  for key, at in pairs(list(raw.removed)) do
    if type(key) == "string" and number(at) then sync.removed[key] = at end
  end
  for key, result in pairs(list(raw.imports)) do
    if type(key) == "string" and type(result) == "string" then sync.imports[key] = result end
  end
  return sync
end

-- ---- Options (Options > AddOns > Gargoyle) ----

function ns.CreateOptions()
  local panel = CreateFrame("Frame")
  panel.name = "Gargoyle"
  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Gargoyle")
  local intro = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  intro:SetText("Turn features on or off. Changes take effect straight away. Open the window with the "
    .. "Gargoyle button on the minimap, or by typing /gargoyle.")
  ns.optionBoxes = {}
  local y = -70
  for _, key in ipairs(ns.moduleOrder) do
    local module = ns.modules[key]
    local box = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    box:SetPoint("TOPLEFT", 16, y)
    local label = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    label:SetPoint("LEFT", box, "RIGHT", 4, 0)
    label:SetText(module.title)
    local about = panel:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
    about:SetPoint("TOPLEFT", label, "BOTTOMLEFT", 0, -4)
    about:SetText(module.description or "")
    box:SetChecked(ns.IsEnabled(key))
    box:SetScript("OnClick", function(self)
      ns.SetEnabled(key, self:GetChecked() and true or false)
    end)
    ns.optionBoxes[key] = box
    y = y - 56
  end
  -- More options, each a checkbox: get() says if it's on, set(on) changes it.
  local more = {}
  y = y - 10
  local function option(label, get, set)
    local box = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    box:SetPoint("TOPLEFT", 16, y)
    local text = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    text:SetPoint("LEFT", box, "RIGHT", 4, 0)
    text:SetText(label)
    box:SetChecked(get())
    box:SetScript("OnClick", function(self) set(self:GetChecked() and true or false) end)
    more[box] = get
    y = y - 32
    return box
  end
  ns.minimapBox = option("Show the minimap button", function() return not GargoyleDB.minimap.hide end, ns.ShowMinimapButton)
  local alerts = ns.RaidAlerts
  ns.newRaidsBox = option("Tell me about new raids (the minimap button glows, with a soft chime)",
    function() return alerts.On("newRaids") end, function(on) alerts.SetOn("newRaids", on) end)
  ns.remindersBox = option("Remind me a day before a raid I haven't signed up for",
    function() return alerts.On("reminders") end, function(on) alerts.SetOn("reminders", on) end)
  ns.calendarBox = option("Mark my guilds' raids on the game's calendar", ns.Calendar.On, ns.Calendar.SetOn)
  panel:SetScript("OnShow", function()
    for key, box in pairs(ns.optionBoxes) do box:SetChecked(ns.IsEnabled(key)) end
    for box, get in pairs(more) do box:SetChecked(get()) end
  end)
  ns.optionsPanel = panel
  -- The options window's API has changed over the years; if this one is missing, the
  -- features are still there, just without the checkboxes.
  local ok = pcall(function()
    if Settings and Settings.RegisterCanvasLayoutCategory then
      ns.optionsCategory = Settings.RegisterCanvasLayoutCategory(panel, "Gargoyle")
      Settings.RegisterAddOnCategory(ns.optionsCategory)
    elseif InterfaceOptions_AddCategory then
      InterfaceOptions_AddCategory(panel)
    end
  end)
  if not ok then ns.optionsCategory = nil end
end

function ns.OpenOptions()
  local ok = pcall(function()
    if ns.optionsCategory and Settings and Settings.OpenToCategory then
      Settings.OpenToCategory(ns.optionsCategory:GetID())
    elseif InterfaceOptionsFrame_OpenToCategory then
      InterfaceOptionsFrame_OpenToCategory(ns.optionsPanel)
    end
  end)
  if not ok then ns.say("couldn't open the options. Find them under Options > AddOns > Gargoyle.") end
end

-- ---- Starting up ----

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", function(_, event, name)
  if event == "ADDON_LOADED" and name == ADDON then
    loadDB()
  elseif event == "PLAYER_LOGIN" then
    ns.sync = ns.ReadSync()
    for _, key in ipairs(ns.moduleOrder) do
      local module = ns.modules[key]
      if module.OnLogin then module:OnLogin() end
      if ns.IsEnabled(key) and module.OnEnable then module:OnEnable() end
    end
    ns.CreateOptions()
    ns.CreateMinimapButton()
  end
end)

SLASH_GARGOYLE1 = "/gargoyle"
SlashCmdList.GARGOYLE = function(message)
  local command = strtrim(message or ""):lower()
  if command == "options" or command == "config" then
    ns.OpenOptions()
  elseif command == "debug" then
    ns.Debug()
  elseif command == "minimap" then
    ns.ShowMinimapButton(GargoyleDB.minimap.hide == true)
  elseif command == "help" then
    ns.say("/gargoyle opens the window. /gargoyle options turns features on or off. /gargoyle minimap shows or hides the minimap button.")
  else
    ns.ToggleWindow()
  end
end

-- The addon menu by the minimap (## AddonCompartmentFunc in the .toc).
function Gargoyle_OnAddonCompartmentClick()
  ns.ToggleWindow()
end
