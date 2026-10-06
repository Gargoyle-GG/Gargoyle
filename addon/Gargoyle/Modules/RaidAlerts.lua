-- Raid alerts, part of Raid signups:
--  * New raids: when the Gargoyle app brings in raids you haven't looked at yet, the minimap
--    button glows (until you open the Raids tab), and once per raid a bubble by the button
--    says so, with a soft chime.
--  * Reminders: once per raid, a day before a raid you haven't signed up for (nor said you
--    can't come to), a small window says so, with a button that opens Gargoyle on that raid.
-- Both can be turned off in the options. They only show what's already in Gargoyle's data,
-- nothing is signed up for you, and nothing pops up in combat.
local _, ns = ...
local Raids = ns.Raids

local Alerts = {}
ns.RaidAlerts = Alerts

local DAY = 86400
local FIRST_CHECK = 6 -- seconds after logging in or reloading (past the loading screen)
local CHECK_EVERY = 60
local KEEP_DAYS = 30 -- what's been seen or told is forgotten this long after the raid

local fresh = {} -- raid id -> true: new when you opened the Raids tab (marked "New" until you reload)
local started, waiting = false, false
local reminder

-- GargoyleDB.alerts: newRaids and reminders (false when turned off); seen, told and reminded,
-- each raid id -> the raid's start time.
local function saved()
  return GargoyleDB.alerts
end

function Alerts.On(kind)
  return saved()[kind] ~= false
end

function Alerts.SetOn(kind, on)
  if on then saved()[kind] = nil else saved()[kind] = false end
  if kind == "reminders" and not on and reminder then reminder:Hide() end
  Alerts.Update()
end

local function chime()
  local sound = SOUNDKIT and SOUNDKIT.UI_BNET_TOAST -- (the game's soft "bing" for a friend coming online)
  if sound then PlaySound(sound) end
end

local function inTime(seconds)
  local minutes = math.ceil(seconds / 60)
  if minutes < 60 then return minutes == 1 and "1 minute" or (minutes .. " minutes") end
  local hours = math.floor(seconds / 3600 + 0.5)
  return hours == 1 and "1 hour" or (hours .. " hours")
end

-- Upcoming raids you haven't looked at in the Raids tab and haven't signed up for.
function Alerts.Unseen()
  local unseen = {}
  if not (ns.sync and ns.IsEnabled("raids")) then return unseen end
  for _, raid in ipairs(Raids.List()) do
    if not saved().seen[raid.id] and not Raids.Mine(raid) then unseen[#unseen + 1] = raid end
  end
  return unseen
end

function Alerts.IsNew(raid)
  return fresh[raid.id] == true
end

-- The glow is on while there are unseen raids (and new-raid alerts are on).
function Alerts.Update()
  local on = ns.IsEnabled("raids") and Alerts.On("newRaids") and #Alerts.Unseen() > 0
  if ns.SetMinimapGlow then ns.SetMinimapGlow(on) end
  if not on and ns.HideMinimapBubble then ns.HideMinimapBubble() end
  if not ns.IsEnabled("raids") and reminder then reminder:Hide() end
end

-- The Raids tab is open on these raids: they've been seen.
function Alerts.Seen(raids)
  local seen, changed = saved().seen, false
  for _, raid in ipairs(raids) do
    if seen[raid.id] == nil then
      if not Raids.Mine(raid) then fresh[raid.id] = true end
      changed = true
    end
    seen[raid.id] = raid.start
  end
  if changed then Alerts.Update() end
end

-- ---- The reminder window ----

local function createReminder()
  reminder = CreateFrame("Frame", "GargoyleReminder", UIParent)
  reminder:SetSize(400, 214)
  reminder:SetPoint("TOP", 0, -200)
  reminder:SetFrameStrata("DIALOG")
  reminder:SetToplevel(true)
  reminder:SetClampedToScreen(true)
  reminder:EnableMouse(true)
  reminder:Hide()
  tinsert(UISpecialFrames, "GargoyleReminder") -- Escape closes it
  -- The game's dialog box, with its name plate on top.
  local border = CreateFrame("Frame", nil, reminder, "DialogBorderTemplate")
  border:SetAllPoints()
  local header = CreateFrame("Frame", nil, reminder, "DialogHeaderTemplate")
  if header.Setup then header:Setup("Gargoyle") end
  local close = CreateFrame("Button", nil, reminder, "UIPanelCloseButtonNoScripts")
  close:SetPoint("TOPRIGHT", -5, -5)
  close:SetScript("OnClick", function() reminder:Hide() end)

  local function line(font, y)
    local fs = reminder:CreateFontString(nil, "ARTWORK", font)
    fs:SetPoint("TOP", 0, y)
    fs:SetWidth(360)
    return fs
  end
  reminder.heading = line("GameFontNormalLarge", -28)
  reminder.raid = line("GameFontHighlight", -52)
  reminder.when = line("GameFontHighlightSmall", -70)
  reminder.text = line("GameFontHighlightSmall", -94)
  reminder.text:SetText("You haven't signed up yet. Let your raid know if you're coming, or that you can't make it.")
  reminder.more = line("GameFontDisableSmall", -124)

  local open = CreateFrame("Button", nil, reminder, "UIPanelButtonTemplate")
  open:SetSize(150, 24)
  open:SetPoint("BOTTOM", 0, 34)
  open:SetText("Open Gargoyle")
  open:SetScript("OnClick", function()
    reminder:Hide()
    Raids.Show(reminder.raidId)
  end)
  local hint = reminder:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  hint:SetPoint("BOTTOM", 0, 16)
  hint:SetText("You can turn these reminders off in Gargoyle's options.")
  ns.Sharpen(reminder)
end

local function showReminder(raid, others)
  if not reminder then createReminder() end
  reminder.raidId = raid.id
  reminder.heading:SetText("Your next raid is in " .. inTime(raid.start - time()))
  reminder.raid:SetText(ns.Plain(raid.title))
  reminder.when:SetText(Raids.When(raid.start) .. "  ·  " .. ns.Plain(raid.guild.name))
  reminder.more:SetText(others == 0 and ""
    or string.format("You also haven't signed up for %d more %s in the next 24 hours.", others, others == 1 and "raid" or "raids"))
  reminder:Show()
end

-- ---- Checking ----

-- A raid starting within a day that you haven't signed up for: a reminder, once. Returns true
-- if one showed.
local function remind()
  if not Alerts.On("reminders") or (reminder and reminder:IsShown()) then return end
  local reminded, due = saved().reminded, {}
  for _, raid in ipairs(Raids.List()) do
    if raid.start - time() <= DAY and reminded[raid.id] ~= raid.start and not Raids.Mine(raid) then
      due[#due + 1] = raid
    end
  end
  if #due == 0 then return end
  for _, raid in ipairs(due) do reminded[raid.id] = raid.start end
  showReminder(due[1], #due - 1)
  return true
end

-- Unseen raids it hasn't told you about yet (and that didn't just get a reminder): the
-- bubble, once. Returns true if it told you.
local function announce()
  Alerts.Update()
  if not Alerts.On("newRaids") then return end
  local told, reminded, untold = saved().told, saved().reminded, {}
  for _, raid in ipairs(Alerts.Unseen()) do
    if told[raid.id] == nil and reminded[raid.id] ~= raid.start then untold[#untold + 1] = raid end
    told[raid.id] = raid.start
  end
  if #untold == 0 then return end
  local first = untold[1]
  local detail = string.format("%s, %s", ns.Plain(first.title), Raids.When(first.start))
  if #untold > 1 then detail = detail .. string.format(" and %d more", #untold - 1) end
  if not (ns.ShowMinimapBubble and ns.ShowMinimapBubble("You have unseen raids scheduled!", detail)) then
    ns.say("you have unseen raids scheduled! " .. detail .. ". Type /gargoyle to see them.")
  end
  return true
end

function Alerts.Check()
  if not (ns.sync and ns.sync.loaded and ns.IsEnabled("raids")) then return end
  if InCombatLockdown() then
    waiting = true -- (again once combat ends)
    return
  end
  local reminded = remind()
  local told = announce()
  if reminded or told then chime() end
end

local function tick()
  Alerts.Check()
  C_Timer.After(CHECK_EVERY, tick)
end

-- Raids long gone are forgotten, and anything odd in the saved file is dropped.
local function tidy()
  local oldest = time() - KEEP_DAYS * DAY
  for _, name in ipairs({ "seen", "told", "reminded" }) do
    local list = saved()[name]
    for id, start in pairs(list) do
      if type(id) ~= "number" or type(start) ~= "number" or start < oldest then list[id] = nil end
    end
  end
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:SetScript("OnEvent", function(_, event)
  if event == "PLAYER_ENTERING_WORLD" then
    if started then return end
    started = true
    tidy()
    C_Timer.After(FIRST_CHECK, tick)
  elseif waiting then
    waiting = false
    Alerts.Check()
  end
end)
