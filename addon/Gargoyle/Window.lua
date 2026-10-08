-- The Gargoyle window (/gargoyle or the minimap button): one tab per feature that's turned
-- on. It's built from the game's own window parts (the frame, tabs and buttons of the
-- character window), so it looks like the rest of the game.
local _, ns = ...

-- Gargoyle's gold G badge, as on gargoyle.gg (Media/, drawn by tools/build_addon_icons.py for
-- the size each is shown at): the badge itself for small marks, and round versions for round
-- frames (the minimap button, and the window's corner portrait).
local MEDIA = "Interface\\AddOns\\Gargoyle\\Media\\"
ns.ICON = MEDIA .. "Badge"
ns.ROUND_ICON = MEDIA .. "Round"
ns.PORTRAIT = MEDIA .. "Portrait"

local window, empty, account, waiting
local tabs, panels = {}, {}
local current

-- Lines up a frame and everything in it with the screen's pixels, so text and art stay
-- sharp at any interface scale (as the game does for its nameplates).
function ns.Sharpen(frame)
  if PixelUtil and PixelUtil.SetRoundLayoutToNearestPixelRecursively and frame.SetRoundLayoutToNearestPixel then
    PixelUtil.SetRoundLayoutToNearestPixelRecursively(frame, true)
  end
end

-- A tooltip for a button: its name, and a line about what it does.
function ns.Tooltip(owner, title, text)
  owner:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(title, 1, 1, 1)
    GameTooltip:AddLine(text, 1, 0.82, 0, true)
    GameTooltip:Show()
  end)
  owner:SetScript("OnLeave", function() GameTooltip:Hide() end)
end

local function create()
  window = CreateFrame("Frame", "GargoyleWindow", UIParent, "PortraitFrameTemplate")
  window:SetSize(800, 540)
  window:SetPoint("CENTER")
  window:SetFrameStrata("HIGH")
  window:SetToplevel(true)
  window:SetClampedToScreen(true)
  window:SetMovable(true)
  window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", window.StopMovingOrSizing)
  window:Hide()
  tinsert(UISpecialFrames, "GargoyleWindow") -- Escape closes it
  window:SetTitle("Gargoyle")
  window:SetPortraitToAsset(ns.PORTRAIT)

  -- Under the title: whose data this is and how fresh, and the options.
  account = window:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  account:SetPoint("TOPLEFT", 66, -38)
  account:SetPoint("RIGHT", -110, 0)
  account:SetJustifyH("LEFT")
  local options = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
  options:SetSize(90, 22)
  options:SetPoint("TOPRIGHT", -10, -32)
  options:SetText("Options")
  options:SetScript("OnClick", ns.OpenOptions)

  window.content = CreateFrame("Frame", nil, window)
  window.content:SetPoint("TOPLEFT", 10, -62)
  window.content:SetPoint("BOTTOMRIGHT", -10, 34)
  empty = window.content:CreateFontString(nil, "ARTWORK", "GameFontDisable")
  empty:SetPoint("CENTER")
  empty:SetText("Every feature is turned off. Turn some on in Options.")

  -- Along the bottom: what's waiting to sync, and the game's /reload as a button (the game
  -- saves Gargoyle's changes as it reloads, which is when the Gargoyle app can send them).
  local reload = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
  reload:SetSize(110, 22)
  reload:SetPoint("BOTTOMRIGHT", -10, 7)
  reload:SetText("Reload UI")
  reload:SetScript("OnClick", function() ReloadUI() end)
  ns.Tooltip(reload, "Reload UI", "Reloads the game's interface, like typing /reload. The game saves your changes "
    .. "as it does, and the Gargoyle app sends them a few seconds later. Anything new the app brought in since your "
    .. "last reload shows up.")
  waiting = window:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  waiting:SetPoint("BOTTOMLEFT", 14, 13)
  waiting:SetPoint("RIGHT", reload, "LEFT", -10, 0)
  waiting:SetJustifyH("LEFT")
end

-- What each feature has waiting to sync ("1 signup"), for the bottom of the window and the
-- minimap button's tooltip.
function ns.WaitingText()
  local parts = {}
  for _, key in ipairs(ns.moduleOrder) do
    local module = ns.modules[key]
    local part = ns.IsEnabled(key) and module.Waiting and module.Waiting()
    if part then parts[#parts + 1] = part end
  end
  if #parts > 0 then return "Waiting to sync: " .. table.concat(parts, ", ") end
end

function ns.UpdateStatus()
  if not window then return end
  local sync = ns.sync
  if sync.loaded then
    account:SetText(string.format("|cffffd100Gargoyle account:|r %s     |cffffd100Last sync:|r %s", ns.Plain(sync.user or "?"),
      sync.synced and ns.Ago(time() - sync.synced) or "before you logged in"))
  else
    account:SetText("No data from the Gargoyle app yet. With the app running, reload or log in again.")
  end
  local text = ns.WaitingText()
  waiting:SetText(text and (text .. ". Reload or log out to send.") or "Nothing waiting to sync.")
end

function ns.ShowModule(key)
  current = key
  for k, panel in pairs(panels) do panel:SetShown(k == key) end
  for k, tab in pairs(tabs) do
    if k == key then PanelTemplates_SelectTab(tab) else PanelTemplates_DeselectTab(tab) end
  end
  local module = ns.modules[key]
  if module and module.Refresh then module:Refresh() end
  ns.UpdateStatus()
end

-- Tabs hang below the window, as on the character window.
function ns.RefreshWindow()
  if not window then return end
  local previous, first, stillOn, added = nil, nil, false, false
  for _, key in ipairs(ns.moduleOrder) do
    local module = ns.modules[key]
    local on = ns.IsEnabled(key) and module.CreatePanel ~= nil
    if on and not tabs[key] then
      local tab = CreateFrame("Button", nil, window, "PanelTabButtonTemplate")
      tab:SetText(module.title)
      tab:SetScript("OnClick", function()
        local sound = SOUNDKIT and SOUNDKIT.IG_CHARACTER_INFO_TAB
        if sound then PlaySound(sound) end
        ns.ShowModule(key)
      end)
      PanelTemplates_TabResize(tab, 0)
      tabs[key] = tab
      panels[key] = CreateFrame("Frame", nil, window.content)
      panels[key]:SetAllPoints()
      module:CreatePanel(panels[key])
      added = true
    end
    if tabs[key] then
      tabs[key]:SetShown(on)
      panels[key]:SetShown(false)
      if on then
        tabs[key]:ClearAllPoints()
        if previous then
          tabs[key]:SetPoint("TOPLEFT", previous, "TOPRIGHT", 3, 0)
        else
          tabs[key]:SetPoint("TOPLEFT", window, "BOTTOMLEFT", 11, 2)
        end
        previous = tabs[key]
        first = first or key
        stillOn = stillOn or key == current
      end
    end
  end
  if added then ns.Sharpen(window) end
  empty:SetShown(first == nil)
  if first then ns.ShowModule(stillOn and current or first) else ns.UpdateStatus() end
end

-- Opens the window (on a feature's tab, if it's given and turned on).
function ns.OpenWindow(key)
  if not window then create() end
  if key then current = key end
  window:Show()
  window:Raise() -- (in front of the game's calendar, when opened from a mark on it)
  ns.RefreshWindow()
end

function ns.ToggleWindow()
  if window and window:IsShown() then window:Hide() else ns.OpenWindow() end
end
