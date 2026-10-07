-- The Gargoyle button on the edge of the minimap: click to open the window, right-click for
-- the options, drag to move it around the minimap. It can be hidden in the options (or
-- with /gargoyle minimap). Its place is kept in GargoyleDB.minimap.
local _, ns = ...

local DEFAULT_ANGLE = 220 -- degrees around the minimap, counterclockwise from the right
local button, glow, bubble

local function settings()
  return GargoyleDB.minimap
end

local function angle()
  local a = settings().angle
  return type(a) == "number" and a > -math.huge and a < math.huge and a or DEFAULT_ANGLE -- (also not NaN)
end

-- Sits just outside the minimap's edge. (Some interface addons make the minimap square: the
-- button then follows the square's edge.)
local function place()
  local radians = math.rad(angle())
  local x, y = math.cos(radians), math.sin(radians)
  local w, h = Minimap:GetWidth() / 2 + 5, Minimap:GetHeight() / 2 + 5
  if GetMinimapShape and GetMinimapShape() == "SQUARE" then
    local reach = math.sqrt(2) * w
    x = math.max(-w, math.min(x * reach, w))
    y = math.max(-h, math.min(y * reach, h))
  else
    x, y = x * w, y * h
  end
  button:ClearAllPoints()
  button:SetPoint("CENTER", Minimap, "CENTER", x, y)
end

local function follow()
  local mx, my = Minimap:GetCenter()
  local px, py = GetCursorPosition()
  local scale = Minimap:GetEffectiveScale()
  settings().angle = math.deg(math.atan2(py / scale - my, px / scale - mx)) % 360
  place()
end

local function showTooltip(self)
  GameTooltip:SetOwner(self, "ANCHOR_LEFT")
  GameTooltip:SetText("Gargoyle", 1, 1, 1)
  local upcoming = ns.Raids and ns.IsEnabled("raids") and ns.Raids.List()[1]
  if upcoming then
    GameTooltip:AddLine(string.format("Next raid: %s, %s", ns.Plain(upcoming.title), date("%a %d %b, %H:%M", upcoming.start)), 1, 1, 1)
  end
  local unseen = glow:IsShown() and #ns.RaidAlerts.Unseen() or 0
  if unseen > 0 then
    GameTooltip:AddLine(string.format("%d new %s you haven't seen", unseen, unseen == 1 and "raid" or "raids"), 0.1, 1, 0.1)
  end
  local waiting = ns.WaitingText()
  if waiting then GameTooltip:AddLine(waiting, 1, 1, 1) end
  GameTooltip:AddLine("Click to open. Right-click for options. Drag to move this button.", 1, 0.82, 0, true)
  GameTooltip:Show()
end

function ns.CreateMinimapButton()
  if button or not Minimap then return end
  button = CreateFrame("Button", "GargoyleMinimapButton", Minimap)
  button:SetSize(31, 31)
  button:SetFrameStrata("MEDIUM")
  button:SetFrameLevel(8)
  if button.SetFixedFrameStrata then -- (so it stays above the minimap when the minimap is moved or redrawn)
    button:SetFixedFrameStrata(true)
    button:SetFixedFrameLevel(true)
  end
  button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  button:RegisterForDrag("LeftButton")
  button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

  -- The round minimap-button look: a dark disc, the icon, and the gold ring over them.
  local background = button:CreateTexture(nil, "BACKGROUND")
  background:SetSize(20, 20)
  background:SetPoint("TOPLEFT", 7, -5)
  background:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  local icon = button:CreateTexture(nil, "ARTWORK")
  icon:SetSize(17, 17)
  icon:SetPoint("TOPLEFT", 7, -6)
  icon:SetTexture(ns.ROUND_ICON)
  icon:SetTexCoord(0.05, 0.95, 0.05, 0.95)
  if button.CreateMaskTexture and icon.AddMaskTexture then
    local mask = button:CreateMaskTexture()
    mask:SetAllPoints(icon)
    mask:SetTexture("Interface\\CharacterFrame\\TempPortraitAlphaMask", "CLAMPTOBLACKADDITIVE", "CLAMPTOBLACKADDITIVE")
    icon:AddMaskTexture(mask)
  end
  local ring = button:CreateTexture(nil, "OVERLAY")
  ring:SetSize(53, 53)
  ring:SetPoint("TOPLEFT")
  ring:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  -- New raids you haven't seen: the game's calendar-invite glow, pulsing (RaidAlerts.lua).
  glow = button:CreateTexture(nil, "OVERLAY", nil, 1)
  glow:SetSize(50, 50)
  glow:SetPoint("CENTER", background, "CENTER")
  glow:SetTexture("Interface\\Calendar\\EventNotificationGlow")
  glow:SetBlendMode("ADD")
  glow:Hide()
  glow.pulse = glow:CreateAnimationGroup()
  glow.pulse:SetLooping("BOUNCE")
  local fade = glow.pulse:CreateAnimation("Alpha")
  fade:SetFromAlpha(1)
  fade:SetToAlpha(0.2)
  fade:SetDuration(0.9)
  fade:SetSmoothing("IN_OUT")

  button:SetScript("OnClick", function(_, mouseButton)
    if mouseButton == "RightButton" then
      ns.OpenOptions()
    elseif glow:IsShown() then
      ns.OpenWindow("raids") -- (straight to the new raids)
    else
      ns.ToggleWindow()
    end
  end)
  -- Pressed: the icon sinks a little.
  button:SetScript("OnMouseDown", function() icon:SetTexCoord(0, 1, 0, 1) end)
  button:SetScript("OnMouseUp", function() icon:SetTexCoord(0.05, 0.95, 0.05, 0.95) end)
  button:SetScript("OnEnter", showTooltip)
  button:SetScript("OnLeave", function() GameTooltip:Hide() end)
  button:SetScript("OnDragStart", function(self)
    GameTooltip:Hide()
    self:LockHighlight()
    self:SetScript("OnUpdate", follow)
  end)
  button:SetScript("OnDragStop", function(self)
    self:SetScript("OnUpdate", nil)
    self:UnlockHighlight()
    icon:SetTexCoord(0.05, 0.95, 0.05, 0.95)
  end)

  ns.Sharpen(button)
  place()
  button:SetShown(not settings().hide)
end

function ns.ShowMinimapButton(show)
  settings().hide = not show or nil
  if button then button:SetShown(show) end
  if not show then ns.HideMinimapBubble() end
  if ns.minimapBox then ns.minimapBox:SetChecked(show) end
end

function ns.SetMinimapGlow(on)
  if not glow then return end
  glow:SetShown(on)
  if on then glow.pulse:Play() else glow.pulse:Stop() end
end

-- ---- The bubble by the button ----

-- The game's yellow-edged help bubble (GlowBoxTemplate), with its arrow pointing at the
-- button. A click on it opens the Raids tab.
local function createBubble()
  bubble = CreateFrame("Button", "GargoyleMinimapBubble", UIParent, "GlowBoxTemplate")
  bubble:SetWidth(250)
  bubble:SetFrameStrata("DIALOG")
  bubble:SetClampedToScreen(true)
  bubble:Hide()
  bubble.title = bubble:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  bubble.title:SetPoint("TOPLEFT", 14, -14)
  bubble.title:SetPoint("RIGHT", -28, 0)
  bubble.title:SetJustifyH("LEFT")
  bubble.detail = bubble:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  bubble.detail:SetPoint("TOPLEFT", bubble.title, "BOTTOMLEFT", 0, -6)
  bubble.detail:SetPoint("RIGHT", -14, 0)
  bubble.detail:SetJustifyH("LEFT")
  bubble.hint = bubble:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  bubble.hint:SetPoint("TOPLEFT", bubble.detail, "BOTTOMLEFT", 0, -6)
  bubble.hint:SetText("Click to see them.")
  bubble.arrowUp = bubble:CreateTexture(nil, "ARTWORK", "HelpPlateArrowUp")
  bubble.arrowDown = bubble:CreateTexture(nil, "ARTWORK", "HelpPlateArrowDown")
  local close = CreateFrame("Button", nil, bubble, "UIPanelCloseButtonNoScripts")
  close:SetPoint("TOPRIGHT", -2, -2)
  close:SetScript("OnClick", function() bubble:Hide() end)
  bubble:SetScript("OnClick", function()
    bubble:Hide()
    ns.OpenWindow("raids")
  end)
  ns.Sharpen(bubble)
end

-- Below the button if it's in the top half of the screen (above it if not), reaching left
-- if it's on the right half (right if not), so the bubble stays on screen.
local function placeBubble()
  local x, y = button:GetCenter()
  local scale = button:GetEffectiveScale() / UIParent:GetEffectiveScale()
  local below = y * scale > UIParent:GetHeight() / 2
  local side = x * scale > UIParent:GetWidth() / 2 and "RIGHT" or "LEFT"
  local inset = side == "RIGHT" and -32 or 32 -- (the arrow's middle, from the bubble's corner)
  local arrow = below and bubble.arrowUp or bubble.arrowDown
  bubble.arrowUp:SetShown(below)
  bubble.arrowDown:SetShown(not below)
  arrow:ClearAllPoints()
  bubble:ClearAllPoints()
  if below then
    arrow:SetPoint("BOTTOM", bubble, "TOP" .. side, inset, -3)
    bubble:SetPoint("TOP" .. side, button, "BOTTOM", -inset, -16)
  else
    arrow:SetPoint("TOP", bubble, "BOTTOM" .. side, inset, 3)
    bubble:SetPoint("BOTTOM" .. side, button, "TOP", -inset, 16)
  end
end

-- Shows the bubble. False if the button can't be seen (the caller then says it in chat).
function ns.ShowMinimapBubble(title, detail)
  if not (button and button:IsVisible()) then return false end
  if not bubble then createBubble() end
  bubble.title:SetText(title)
  bubble.detail:SetText(detail)
  bubble:SetHeight(bubble.title:GetStringHeight() + bubble.detail:GetStringHeight() + bubble.hint:GetStringHeight() + 40)
  placeBubble()
  bubble:Show()
  return true
end

function ns.HideMinimapBubble()
  if bubble then bubble:Hide() end
end
