-- Raids on the game's calendar, part of Raid signups: a day on the game's own calendar (from
-- the clock by the minimap, or /calendar) gets a small Gargoyle mark when one of your
-- guilds' raids is that day, in your own time like the rest of Gargoyle. Hovering it lists
-- them; clicking it opens Gargoyle on the first.
--
-- The marks are only drawn on top of the calendar. Nothing is added to the game's calendar
-- itself, so nothing is sent and nobody else sees them. The calendar is the game's own addon
-- (Blizzard_Calendar, loaded when it's first opened). Gargoyle follows its month changes
-- with hooksecurefunc, which runs after the game's code and changes none of it. It can be
-- turned off in the options.
local _, ns = ...
local Raids = ns.Raids

local Calendar = {}
ns.Calendar = Calendar

local DAY_BUTTONS = 42 -- the calendar shows six weeks
local marks = {} -- day button number -> its Gargoyle mark
local hooked = false

function Calendar.On()
  return GargoyleDB.calendar ~= false
end

function Calendar.SetOn(on)
  if on then GargoyleDB.calendar = nil else GargoyleDB.calendar = false end
  Calendar.Update()
end

local function dayKey(year, month, day)
  return year * 10000 + month * 100 + day
end

-- The date a day button shows: a day of the calendar's month, or of the month before or after.
local function dateOf(button)
  local year, month = CalendarFrame.viewedYear, CalendarFrame.viewedMonth + (button.monthOffset or 0)
  if month < 1 then
    month, year = 12, year - 1
  elseif month > 12 then
    month, year = 1, year + 1
  end
  return dayKey(year, month, button.day)
end

local function showTooltip(mark)
  GameTooltip:SetOwner(mark, "ANCHOR_RIGHT")
  GameTooltip:SetText("Gargoyle", 1, 1, 1)
  for _, raid in ipairs(mark.raids) do
    GameTooltip:AddLine(ns.Plain(raid.title), 1, 0.82, 0)
    GameTooltip:AddLine(string.format("%s  ·  %s  ·  %s", date("%H:%M", raid.start), ns.Plain(raid.guild.name),
      Raids.StatusText(raid)), 1, 1, 1)
  end
  GameTooltip:AddLine("Click to open it in Gargoyle.", 0.6, 0.6, 0.6)
  GameTooltip:Show()
end

local function markFor(index)
  if marks[index] then return marks[index] end
  local day = _G["CalendarDayButton" .. index]
  if not day then return end
  local mark = CreateFrame("Button", nil, day)
  mark:SetSize(22, 22)
  mark:SetPoint("TOPRIGHT", -4, -4) -- (the date is top left, the game's events along the bottom)
  mark:SetFrameLevel(day:GetFrameLevel() + 5)
  local icon = mark:CreateTexture(nil, "ARTWORK")
  icon:SetAllPoints()
  icon:SetTexture(ns.ICON)
  icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
  mark:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
  mark.count = mark:CreateFontString(nil, "OVERLAY", "NumberFontNormalSmall")
  mark.count:SetPoint("BOTTOMRIGHT", 2, -2)
  mark:SetScript("OnEnter", showTooltip)
  mark:SetScript("OnLeave", function() GameTooltip:Hide() end)
  mark:SetScript("OnClick", function(self) Raids.Show(self.raids[1].id) end)
  marks[index] = mark
  return mark
end

-- Marks the days with raids (after the calendar draws a month, and when Gargoyle's raids change).
function Calendar.Update()
  if not (hooked and CalendarFrame and CalendarFrame.viewedMonth and CalendarFrame.viewedYear) then return end
  local byDay = {}
  if Calendar.On() and ns.sync and ns.IsEnabled("raids") then
    for _, raid in ipairs(Raids.Shown()) do
      local d = date("*t", raid.start)
      local key = dayKey(d.year, d.month, d.day)
      byDay[key] = byDay[key] or {}
      table.insert(byDay[key], raid)
    end
  end
  for index = 1, DAY_BUTTONS do
    local button = _G["CalendarDayButton" .. index]
    local raids = (button and type(button.day) == "number") and byDay[dateOf(button)] or nil
    local mark = raids and markFor(index) or marks[index]
    if mark then
      mark.raids = raids or {}
      mark.count:SetText(raids and #raids > 1 and tostring(#raids) or "")
      mark:SetShown(raids ~= nil)
    end
  end
end

local function hook()
  if hooked or type(CalendarFrame_Update) ~= "function" then return end
  hooked = true
  hooksecurefunc("CalendarFrame_Update", Calendar.Update)
  Calendar.Update()
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", function(_, event, name)
  if event == "PLAYER_LOGIN" or name == "Blizzard_Calendar" then hook() end -- (at login: in case it's loaded already)
end)
