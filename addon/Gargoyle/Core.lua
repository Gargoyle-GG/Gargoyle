-- Gargoyle: the in-game side of the Gargoyle website. Each feature is a module that can
-- be turned on and off (Options > AddOns > Gargoyle).
--
-- This is the core. Some features are addons of their own, which the Gargoyle app installs
-- when they're ticked in its Settings: Gargoyle_Dungeons (the dungeon journal),
-- Gargoyle_Loot (every item and where it comes from) and Gargoyle_Fishing (a key that casts
-- Fishing). They use the core's helpers through the
-- Gargoyle table below, and register their tabs in the window like the core's own modules.
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
Gargoyle = ns -- (for the module addons)
-- What the module addons may use: raised when the core gains something they need (they check it
-- and say "update the Gargoyle addon" instead of breaking). 2: Items.Load, with 1.0.2.
ns.API = 2

-- The module addons, for Options to say how to get them when they aren't there.
ns.MODULE_ADDONS = {
  { key = "journal", title = "Dungeons", addon = "Gargoyle_Dungeons" },
  { key = "loot", title = "Loot", addon = "Gargoyle_Loot" },
  { key = "fishing", title = "Fishing", addon = "Gargoyle_Fishing" },
}

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
--            CreatePanel(parent) for its tab in the window, Refresh() when shown,
--            options: more checkboxes for the options page, each { label, get, set } }
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
  -- Talent plans (Modules/Talents.lua): "<character key>#<talent set>" -> the website character followed.
  db.talentPlans = tableOr(db.talentPlans)
  -- Upgrades.lua: for each character you play, the website character whose upgrades and
  -- wishlist go with it (false: no one; the dungeon journal kept these before 1.0.0), and the
  -- wishlist changes made in game, waiting to sync.
  db.journal = tableOr(db.journal)
  db.upgradesFor = tableOr(db.upgradesFor or db.journal.chars)
  db.journal.chars = nil
  db.wishes = tableOr(db.wishes)
  -- (db.tooltipMarks: false when item tooltips don't get Gargoyle's upgrade and wishlist lines)
  -- The module addons' own: db.journal (Gargoyle_Dungeons), db.loot (Gargoyle_Loot) and
  -- db.fishing (Gargoyle_Fishing).
  db.loot = tableOr(db.loot)
  db.fishing = tableOr(db.fishing)
  -- Camera.lua: side and up (what was picked), before (the game's own values, for reset).
  db.camera = tableOr(db.camera)
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

function ns.SpellName(spellID)
  if not spellID or spellID == 0 then return end
  if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(spellID) end
  if GetSpellInfo then return (GetSpellInfo(spellID)) end
end

-- ---- Talents ----

-- The talents in the game's talent tree, as Blizzard's talent window reads them. WoW Forever
-- has one talent tree per class (C_Traits), with the classic three trees as groups in it.
-- Each talent: its node id, tree number (the group's place), name, spell, points spent
-- (counting ones not applied yet), most points, and whether a point can go in now. Also the
-- points left to spend. Nil if the game doesn't show the tree.
function ns.TalentNodes(configID)
  local traits = C_Traits
  local config = configID and traits and traits.GetConfigInfo(configID)
  local treeID = config and config.treeIDs and config.treeIDs[1]
  if not treeID then return end
  local groups = traits.GetGroupDisplayInfoByTreeID and traits.GetGroupDisplayInfoByTreeID(treeID) or {}
  table.sort(groups, function(a, b) return (a.orderIndex or 0) < (b.orderIndex or 0) end)
  local tabs = {} -- group id -> tree number
  for i, group in ipairs(groups) do tabs[group.groupID] = i end
  local points
  if traits.GetTreeCurrencyInfo then
    points = 0
    for _, currency in ipairs(traits.GetTreeCurrencyInfo(configID, treeID, false) or {}) do
      points = points + (currency.quantity or 0)
    end
  end
  local nodes = {}
  for _, nodeID in ipairs(traits.GetTreeNodes(treeID) or {}) do
    local node = traits.GetNodeInfo(configID, nodeID)
    if node then
      local entryID = (node.activeEntry and node.activeEntry.entryID) or (node.entryIDs and node.entryIDs[1])
      local entry = entryID and traits.GetEntryInfo(configID, entryID)
      local definition = entry and entry.definitionID and traits.GetDefinitionInfo(entry.definitionID)
      local spell = definition and definition.spellID
      local tab
      for _, groupID in ipairs(node.groupIDs or {}) do tab = tab or tabs[groupID] end
      nodes[#nodes + 1] = {
        id = nodeID, tab = tab, spell = spell, rank = node.ranksPurchased or node.activeRank or 0, max = node.maxRanks,
        name = definition and ((definition.overrideName ~= "" and definition.overrideName) or ns.SpellName(spell)),
        canTake = node.canPurchaseRank == true and (points == nil or points > 0),
      }
    end
  end
  return nodes, points
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

-- A character's talents, as a talent plan: tree number, name, spells and points.
local function readPlan(raw)
  local plan = {}
  for _, t in ipairs(list(raw)) do
    if type(t) == "table" and number(t.tree) and text(t.name, 60) and number(t.rank) and t.rank >= 1 and t.rank <= 10 then
      local spells = {}
      for _, spell in ipairs(list(t.spells)) do
        if number(spell) and #spells < 10 then spells[#spells + 1] = spell end
      end
      plan[#plan + 1] = { tree = t.tree, name = text(t.name, 60), rank = t.rank, spells = spells }
    end
    if #plan == 60 then break end
  end
  return plan
end

-- The dungeon and raid drops the website's planner found are upgrades for a character:
-- item id -> { gain, gain in % }.
local function readUpgrades(raw)
  if type(raw) ~= "table" then return end
  local items, count = {}, 0
  for _, row in ipairs(list(raw.items)) do
    if count == 1000 then break end
    if type(row) == "table" and number(row[1]) and number(row[2]) then
      items[row[1]] = { row[2], number(row[3]) or 0 }
      count = count + 1
    end
  end
  return { items = items, count = count, spec = text(raw.spec, 40), level = number(raw.level), stale = raw.stale == true,
           at = number(raw.at) }
end

-- A character's wishlist on the website: {item id = true} (Upgrades.lua adds the changes made in game).
local function readWishlist(raw)
  local items, count = {}, 0
  for _, id in ipairs(list(raw)) do
    if count == 200 then break end
    if number(id) then
      items[id] = true
      count = count + 1
    end
  end
  return items
end

function ns.ReadSync()
  local sync = { characters = {}, guilds = {}, done = {}, removed = {}, imports = {} }
  local raw = GargoyleSync
  if type(raw) ~= "table" or raw.version ~= 1 then return sync end
  sync.loaded = true
  sync.synced, sync.user = number(raw.synced), text(raw.user, 60)
  sync.makesRaids = raw.can_make_raids == true -- (the app sends raids made in game; older ones don't)
  sync.sendsTalents = raw.sends_talents == true -- (and characters' talents, for talent plans)
  sync.sendsUpgrades = raw.sends_upgrades == true -- (and their upgrades, for the dungeon journal)
  for _, c in ipairs(list(raw.characters)) do
    if type(c) == "table" and number(c.id) and text(c.name, 60) then
      sync.characters[#sync.characters + 1] = {
        id = c.id, name = text(c.name, 60), class = text(c.class, 20) or "", guild = number(c.guild),
        role = text(c.role, 10), game = text(c.game, 80), read = number(c.read), talents = readPlan(c.talents),
        upgrades = readUpgrades(c.upgrades), wishlist = readWishlist(c.wishlist),
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

-- The page scrolls: the game's options window gives it a fixed space (the panel fills it, at
-- whatever UI scale), and Gargoyle has more checkboxes than fit. Everything is on `page`, the
-- scroll frame's child. ScrollFrameTemplate (Blizzard_SharedXML's SecureUIPanelTemplates.xml)
-- adds the scroll bar on the right and mouse-wheel scrolling (ScrollUtil.InitScrollFrameWithScrollBar);
-- UIPanelScrollFrameTemplate, the older one, does the same if a game hasn't the new one.
local SCROLL_BAR = 30 -- (room on the right for the scroll bar)
local LEFT, RIGHT = 16, 16 -- (the page's margins)

function ns.CreateOptions()
  local panel = CreateFrame("Frame")
  panel.name = "Gargoyle"
  local made, scroll = pcall(CreateFrame, "ScrollFrame", nil, panel, "ScrollFrameTemplate")
  if not made then scroll = CreateFrame("ScrollFrame", nil, panel, "UIPanelScrollFrameTemplate") end
  scroll:SetPoint("TOPLEFT", 0, -4)
  scroll:SetPoint("BOTTOMRIGHT", -SCROLL_BAR, 4)
  scroll:EnableMouseWheel(true)
  local page = CreateFrame("Frame", nil, scroll)
  page:SetSize(600, 600) -- (laid out once the panel has its size: layout below)
  scroll:SetScrollChild(page)
  ns.optionsScroll, ns.optionsPage = scroll, page

  -- The page is laid out from the top, one row at a time: each row is a function that puts its
  -- parts at y (from the top) for the page's width, and gives back how tall they came out. Texts
  -- wrap to the width, so their height is only known then (it changes with the width).
  local rows = {}
  local function wrap(text, width)
    text:SetJustifyH("LEFT")
    text:SetWordWrap(true)
    text:SetWidth(math.max(width, 40))
    return text:GetStringHeight()
  end
  local function textRow(text, left, after)
    rows[#rows + 1] = function(y, width)
      text:ClearAllPoints()
      text:SetPoint("TOPLEFT", page, "TOPLEFT", left, y)
      return wrap(text, width - left - RIGHT) + after
    end
  end
  -- A checkbox, its label to the right (wrapping), and a smaller line under the label if `about`;
  -- `after`: more room below it.
  local function boxRow(box, label, about, after)
    label:SetPoint("TOPLEFT", box, "TOPRIGHT", 2, -9)
    if about then about:SetPoint("TOPLEFT", label, "BOTTOMLEFT", 0, -3) end
    rows[#rows + 1] = function(y, width)
      box:ClearAllPoints()
      box:SetPoint("TOPLEFT", page, "TOPLEFT", LEFT, y)
      local textWidth = width - LEFT - box:GetWidth() - 2 - RIGHT
      local height = 9 + wrap(label, textWidth)
      if about then height = height + 3 + wrap(about, textWidth) end
      return math.max(box:GetHeight(), height + 4) + (after or 0)
    end
  end
  local function layout()
    local width = scroll:GetWidth()
    if not width or width < 100 then return end -- (not sized yet: it will be when it's shown)
    page:SetWidth(width)
    local y = -12
    for _, row in ipairs(rows) do y = y - row(y, width) end
    page:SetHeight(12 - y)
  end

  local title = page:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetText("Gargoyle")
  textRow(title, LEFT, 8)
  local intro = page:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetText("Turn features on or off. Changes take effect straight away. Open the window with the "
    .. "Gargoyle button on the minimap, or by typing /gargoyle.")
  textRow(intro, LEFT, 14)
  ns.optionBoxes = {}
  for _, key in ipairs(ns.moduleOrder) do
    local module = ns.modules[key]
    local box = CreateFrame("CheckButton", nil, page, "UICheckButtonTemplate")
    local label = page:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    label:SetText(module.title)
    local about = page:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
    about:SetText(module.description or "")
    boxRow(box, label, about, 8)
    box:SetChecked(ns.IsEnabled(key))
    box:SetScript("OnClick", function(self)
      ns.SetEnabled(key, self:GetChecked() and true or false)
    end)
    ns.optionBoxes[key] = box
  end
  -- The module addons that aren't here: how to get them.
  for _, m in ipairs(ns.MODULE_ADDONS) do
    if not ns.modules[m.key] then
      local missing = page:CreateFontString(nil, "ARTWORK", "GameFontDisable")
      missing:SetText(m.title .. " isn't installed: tick it in the Gargoyle app's Settings (it's its own addon, "
        .. m.addon .. "), or turn it on in the AddOns list.")
      textRow(missing, LEFT + 4, 10)
    end
  end
  rows[#rows + 1] = function() return 10 end
  -- More options, each a checkbox: get() says if it's on, set(on) changes it; `about`, a line under it.
  local more = {}
  local function option(label, get, set, about)
    local box = CreateFrame("CheckButton", nil, page, "UICheckButtonTemplate")
    local text = page:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    text:SetText(label)
    boxRow(box, text, about)
    box:SetChecked(get())
    box:SetScript("OnClick", function(self) set(self:GetChecked() and true or false) end)
    more[box] = get
    return box
  end
  ns.minimapBox = option("Show the minimap button", function() return not GargoyleDB.minimap.hide end, ns.ShowMinimapButton)
  local alerts = ns.RaidAlerts
  ns.newRaidsBox = option("Tell me about new raids (the minimap button glows, with a soft chime)",
    function() return alerts.On("newRaids") end, function(on) alerts.SetOn("newRaids", on) end)
  ns.remindersBox = option("Remind me a day before a raid I haven't signed up for",
    function() return alerts.On("reminders") end, function(on) alerts.SetOn("reminders", on) end)
  ns.calendarBox = option("Mark my guilds' raids on the game's calendar", ns.Calendar.On, ns.Calendar.SetOn)
  ns.tooltipMarksBox = option("Mark upgrades and wishlist items on item tooltips", ns.Upgrades.TooltipsOn,
    ns.Upgrades.SetTooltipsOn)
  -- The modules' own options (module.options: { label, get, set }).
  for _, key in ipairs(ns.moduleOrder) do
    for _, o in ipairs(ns.modules[key].options or {}) do option(o[1], o[2], o[3]) end
  end
  -- Damage tooltips are their own addon (Gargoyle_Tooltips), installed by the Gargoyle app
  -- when it's ticked there; its switch lives here.
  local tips = GargoyleTooltips
  ns.tooltipsBox = option(tips and "Show a damage and healing breakdown on my spells' tooltips"
      or "Damage tooltips aren't loaded (install them from the Gargoyle app's Settings, or turn them on in the AddOns list)",
    function() return tips ~= nil and tips.On() end, function(on) if tips then tips.SetOn(on) end end)
  if not tips then ns.tooltipsBox:Disable() end
  -- The data collector (Gargoyle_Collector), for Gargoyle's helpers: installed by the app with a
  -- helper code, so it's only shown when it's there. Its line says what's waiting to be sent.
  local collector = GargoyleCollector
  if collector then
    ns.collectorText = page:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
    ns.collectorText:SetText(collector.Summary())
    ns.collectorBox = option(type(collector.Label) == "string" and collector.Label
      or "Collect item, spell and talent data for Gargoyle (I'm a helper)", collector.On, collector.SetOn, ns.collectorText)
  end

  -- Camera (Camera.lua): sliders for the sideways and up settings, and a Reset button. The sliders
  -- are Blizzard's own (MinimalSliderWithSteppersTemplate, as in the game's settings: Init(value,
  -- min, max, steps, formatters), and the OnValueChanged callback); a game without it gets the
  -- commands in a line of text instead.
  local camera = ns.Camera
  local cameraTitle = page:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  cameraTitle:SetText("Camera")
  rows[#rows + 1] = function() return 8 end
  textRow(cameraTitle, LEFT, 6)
  local cameraAbout = page:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  cameraAbout:SetText("Move the camera sideways, or frame your character lower on the screen. These are the game's own "
    .. "camera settings, set again at every login and never in combat. The game has no setting for the camera's tilt: "
    .. "tilt it with the mouse. Gargoyle turns off the game's 'keep character centred' (Accessibility > Motion Sickness) "
    .. "while an offset is set, because it would hold the camera in the middle. Commands: /gargoyle camera side <number>, up <strength 0 to 1>, reset.")
  textRow(cameraAbout, LEFT, 8)
  local sliders, refreshing = {}, false
  local function cameraSlider(label, min, max, steps, name, get, set)
    local made, slider = pcall(CreateFrame, "Frame", nil, page, "MinimalSliderWithSteppersTemplate")
    if not (made and slider and slider.Init and slider.RegisterCallback) then return end
    local title = page:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    title:SetText(label)
    textRow(title, LEFT, 2)
    local mixin = MinimalSliderWithSteppersMixin
    local right = mixin and mixin.Label and mixin.Label.Right or 2
    slider:Init(get(), min, max, steps, { [right] = function(value) return tostring(math.floor(value * 100 + 0.5) / 100) end })
    slider:RegisterCallback(mixin and mixin.Event and mixin.Event.OnValueChanged or "OnValueChanged", function(_, value)
      if not refreshing then set(value, true) end
    end, slider)
    rows[#rows + 1] = function(y)
      slider:ClearAllPoints()
      slider:SetPoint("TOPLEFT", page, "TOPLEFT", LEFT + 4, y)
      return slider:GetHeight() + 4
    end
    sliders[#sliders + 1] = { slider = slider, get = get, name = name }
    if not camera.Has(name) then slider:SetEnabled(false) end
    return slider
  end
  local sideSlider = cameraSlider("Sideways (left to right)", camera.SLIDER_MIN, camera.SLIDER_MAX, 80,
    "test_cameraOverShoulder", camera.SideValue, camera.SetSide)
  local upSlider = cameraSlider("Higher view, strength: your character lower on the screen (0 is off)", camera.UP_MIN, camera.UP_MAX, 20,
    "test_cameraDynamicPitch", camera.UpValue, camera.SetUp)
  local cameraReset = CreateFrame("Button", nil, page, "UIPanelButtonTemplate")
  cameraReset:SetSize(140, 24)
  cameraReset:SetText("Reset camera")
  local function showCamera()
    refreshing = true
    for _, s in ipairs(sliders) do
      s.slider:SetValue(s.get())
      s.slider:SetEnabled(camera.Has(s.name))
    end
    refreshing = false
  end
  cameraReset:SetScript("OnClick", function()
    camera.Reset()
    showCamera()
  end)
  rows[#rows + 1] = function(y)
    cameraReset:ClearAllPoints()
    cameraReset:SetPoint("TOPLEFT", page, "TOPLEFT", LEFT + 4, y)
    return cameraReset:GetHeight() + 14
  end
  ns.cameraSliders, ns.cameraReset = { side = sideSlider, up = upSlider }, cameraReset

  scroll:HookScript("OnSizeChanged", layout)
  panel:SetScript("OnShow", function()
    for key, box in pairs(ns.optionBoxes) do box:SetChecked(ns.IsEnabled(key)) end
    for box, get in pairs(more) do box:SetChecked(get()) end
    showCamera()
    if collector then ns.collectorText:SetText(collector.Summary()) end
    layout()
  end)
  layout()
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
    ns.Upgrades.OnLogin()
    -- Once: the dungeon journal was part of Gargoyle until 1.0.0.
    if not ns.modules.journal and GargoyleDB.journal.place ~= nil and not GargoyleDB.toldDungeons then
      GargoyleDB.toldDungeons = true
      ns.say("the Dungeons tab is its own addon now (Gargoyle_Dungeons). Tick Dungeons in the Gargoyle app's Settings "
        .. "to get it back (update the app first if it isn't there).")
    end
    for _, key in ipairs(ns.moduleOrder) do
      local module = ns.modules[key]
      local ok, err = pcall(function()
        if module.OnLogin then module:OnLogin() end
        if ns.IsEnabled(key) and module.OnEnable then module:OnEnable() end
      end)
      if not ok then ns.say(string.format("%s didn't start: %s", module.title or key, tostring(err))) end
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
  elseif command == "camera" or command:sub(1, 7) == "camera " then
    ns.Camera.Command(command:match("^camera%s*(.*)$"))
  elseif command == "help" then
    ns.say("/gargoyle opens the window. /gargoyle options turns features on or off. /gargoyle minimap shows or hides the minimap button. "
      .. "/gargoyle camera moves the camera sideways or up (side, up, reset).")
  else
    ns.ToggleWindow()
  end
end

-- The addon menu by the minimap (## AddonCompartmentFunc in the .toc).
function Gargoyle_OnAddonCompartmentClick()
  ns.ToggleWindow()
end
