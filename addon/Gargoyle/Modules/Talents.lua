-- Talent plans: follow a talent build from your Gargoyle account in the game's talent window.
--
-- Every character saved on your Gargoyle account can be a plan: the Gargoyle app brings in
-- their talents with the rest (GargoyleSync). Pick one for the character you're playing, on
-- the talent window or in this tab (one for each set of talents, with dual spec). In the
-- game's own talent window, each talent the plan still wants then has a small Gargoyle mark
-- with the points the plan puts in it, and glows while a point can go in it. A talent with
-- more points than the plan gets a red mark. You still pick and click every talent yourself:
-- nothing is ever learned or applied for you.
--
-- The marks are only drawn on top of the talent window (the game's own addon,
-- Blizzard_PlayerSpells, loaded when it's first opened). Gargoyle follows its redraws through
-- the game's notice for them (EventRegistry's "TalentFrameBase.ButtonsUpdated") and only
-- reads from it: which talent each button shows, and which talents it shows.
local _, ns = ...

local Talents = {
  title = "Talent plans",
  description = "Follow a talent build from your Gargoyle account: the game's talent window marks the talents it still wants.",
}
ns.RegisterModule("talents", Talents)
ns.Talents = Talents

local EVENTS = { "TRAIT_CONFIG_UPDATED", "PLAYER_TALENT_UPDATE", "CHARACTER_POINTS_CHANGED", "ACTIVE_TALENT_GROUP_CHANGED",
  "PLAYER_LEVEL_UP", "PLAYER_REGEN_ENABLED" }
local LINES = 18 -- talents listed in each column of the tab

local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

-- ---- The plan ----

-- With dual spec, each set of talents has a plan of its own.
local function talentSet()
  local get = (C_SpecializationInfo and C_SpecializationInfo.GetActiveSpecGroup) or GetActiveTalentGroup
  local set = get and get()
  return type(set) == "number" and set or 1
end

function Talents.PlanKey()
  local key = ns.PlayerKey()
  return key and (key .. "#" .. talentSet())
end

-- The builds this character can follow: your Gargoyle characters of its class that have
-- talents, except the one kept up to date from this character (its talents are the game's).
function Talents.Plans()
  local _, classFile = UnitClass("player")
  local class, me, plans = type(classFile) == "string" and classFile:lower() or "", ns.PlayerKey(), {}
  for _, c in ipairs(ns.sync.characters) do
    if c.class == class and #c.talents > 0 and not (me and c.game == me) then plans[#plans + 1] = c end
  end
  table.sort(plans, function(a, b) return a.name:lower() < b.name:lower() end)
  return plans
end

function Talents.Chosen()
  local key = Talents.PlanKey()
  local id = key and GargoyleDB.talentPlans[key]
  for _, c in ipairs(Talents.Plans()) do
    if c.id == id then return c end
  end
end

-- ---- Comparing ----

local function key(name)
  return (tostring(name or ""):lower():gsub("[^%w]", ""))
end

-- Which of the game's talents each of the plan's is: by its spell, else by its name in the
-- same tree, else by its name anywhere (as the website finds the game's talents,
-- game_import.py). Returns node id -> the points the plan wants, and the plan's talents the
-- game's tree doesn't have.
function Talents.Match(plan, nodes)
  local bySpell, byName = {}, {}
  for _, node in ipairs(nodes) do
    if node.spell then bySpell[node.spell] = bySpell[node.spell] or node end
    local k = key(node.name)
    if k ~= "" then
      byName[k] = byName[k] or {}
      table.insert(byName[k], node)
    end
  end
  local wanted, missing = {}, {}
  for _, t in ipairs(plan.talents) do
    local node
    for _, spell in ipairs(t.spells) do node = node or bySpell[spell] end
    local named = byName[key(t.name)] or {}
    for _, n in ipairs(named) do
      if not node and n.tab == t.tree then node = n end
    end
    node = node or named[1]
    if node then
      wanted[node.id] = math.min(math.max(wanted[node.id] or 0, t.rank), node.max or t.rank)
    else
      missing[#missing + 1] = t
    end
  end
  return wanted, missing
end

-- The game's talents against the plan. Each talent the plan disagrees with gets a state:
-- "now" (it wants more, and a point can go in now), "later" (it wants more) or "over" (more
-- points than the plan). Also the lists, and the points planned and spent as planned.
function Talents.Compare(plan, nodes)
  local wanted, missing = Talents.Match(plan, nodes)
  local result = { states = {}, todo = {}, over = {}, missing = missing, planned = 0, spent = 0, now = 0 }
  for _, node in ipairs(nodes) do
    local want = wanted[node.id] or 0
    result.planned = result.planned + want
    result.spent = result.spent + math.min(node.rank, want)
    local state
    if node.rank < want then
      state = node.canTake and "now" or "later"
      table.insert(result.todo, node)
      if state == "now" then result.now = result.now + 1 end
    elseif node.rank > want then
      state = "over"
      table.insert(result.over, node)
    end
    if state then result.states[node.id] = { state = state, want = want } end
  end
  return result
end

local function activeConfig()
  return C_ClassTalents and C_ClassTalents.GetActiveConfigID and C_ClassTalents.GetActiveConfigID()
end

-- The chosen plan against the talents you have now (in the talent set you're using, or the
-- one given). Nil when there's no plan, or the game doesn't show the talents.
function Talents.Progress(configID)
  local plan = Talents.Chosen()
  if not plan then return end
  local ok, nodes = pcall(ns.TalentNodes, configID or activeConfig())
  if ok and nodes then return Talents.Compare(plan, nodes), plan end
end

-- One line about where you are with the plan (or why there's none).
function Talents.Summary(result)
  if not ns.sync.loaded then return "No data from the Gargoyle app yet." end
  if not ns.sync.sendsTalents then return "Update the Gargoyle app to follow talent plans." end
  if not Talents.Chosen() then
    if #Talents.Plans() == 0 then return "None of your Gargoyle characters of this class have talents to follow." end
    return "Pick one of your Gargoyle characters to follow its talents."
  end
  if not result then return "" end
  local parts = {}
  if result.planned == 0 then
    parts[1] = "None of the plan's talents were found in the game's talents"
  elseif result.spent >= result.planned then
    parts[1] = "|cff40c040Plan done|r"
  else
    parts[1] = string.format("%d of %d planned points spent", result.spent, result.planned)
    if result.now > 0 then parts[#parts + 1] = "|cffffd100glowing: a point can go in now|r" end
  end
  if #result.over > 0 then
    parts[#parts + 1] = string.format("|cffe05050%d with more points than the plan|r", #result.over)
  end
  return table.concat(parts, "  ·  ")
end

-- ---- On the game's talent window ----

local talentFrame, layer, bar -- the game's talent window; our layer over its talents; our plan bar on it
local marks = {} -- our marks, reused as the window redraws
local hooked, afterCombat = false, false
local dropdowns = {} -- the plan pickers (on the talent window and in the tab)

local function markFor(i)
  if marks[i] then return marks[i] end
  local mark = CreateFrame("Frame", nil, layer)
  -- A soft light around a talent a point can go in now, gently pulsing.
  mark.glow = mark:CreateTexture(nil, "OVERLAY")
  mark.glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
  mark.glow:SetBlendMode("ADD")
  mark.glow:SetVertexColor(1, 0.82, 0)
  mark.glow:SetPoint("TOPLEFT", -15, 15)
  mark.glow:SetPoint("BOTTOMRIGHT", 15, -15)
  mark.pulse = mark.glow:CreateAnimationGroup()
  mark.pulse:SetLooping("BOUNCE")
  local fade = mark.pulse:CreateAnimation("Alpha")
  fade:SetFromAlpha(1)
  fade:SetToAlpha(0.35)
  fade:SetDuration(0.8)
  fade:SetSmoothing("IN_OUT")
  -- Gargoyle's mark in the corner, with the points the plan puts in this talent.
  mark.icon = mark:CreateTexture(nil, "OVERLAY")
  mark.icon:SetSize(16, 16)
  mark.icon:SetPoint("TOPLEFT", -5, 5)
  mark.icon:SetTexture(ns.ICON)
  mark.want = mark:CreateFontString(nil, "OVERLAY", "NumberFontNormalSmall")
  mark.want:SetPoint("LEFT", mark.icon, "RIGHT", 1, 0)
  marks[i] = mark
  return mark
end

local function draw(mark, button, state)
  mark:ClearAllPoints()
  mark:SetAllPoints(button)
  mark:SetFrameLevel(button:GetFrameLevel() + 5)
  local over = state.state == "over"
  mark.icon:SetVertexColor(1, over and 0.35 or 1, over and 0.35 or 1)
  mark.want:SetText((over and "|cffff5050" or "|cffffffff") .. state.want .. "|r")
  mark.glow:SetShown(state.state == "now")
  if state.state == "now" then mark.pulse:Play() else mark.pulse:Stop() end
  mark.state = state.state
  mark:Show()
end

-- The talent window's buttons that show talents the plan disagrees with, and how.
local function marked(result)
  local found = {}
  for button in talentFrame:EnumerateAllTalentButtons() do
    local nodeID = button.GetNodeID and button:GetNodeID()
    local state = nodeID and result.states[nodeID]
    if state and button:IsShown() then found[#found + 1] = { button = button, state = state } end
  end
  return found
end

-- Marks the talents (after the talent window redraws them, and when the plan or your talents
-- change). Only while the window shows the talents you're using: the other set is locked.
function Talents.UpdateMarks()
  if not hooked then return end
  if InCombatLockdown and InCombatLockdown() then
    afterCombat = true -- (talents can't change in combat: the marks are still right)
    return
  end
  local on = ns.IsEnabled("talents")
  bar:SetShown(on)
  bar.status:SetText("")
  local found = {}
  if on and talentFrame:IsVisible() then
    local okConfig, configID = pcall(talentFrame.GetConfigID, talentFrame)
    local result = okConfig and configID and configID == activeConfig() and Talents.Progress(configID)
    bar.status:SetText(Talents.Summary(result or nil))
    if result then
      local ok, buttons = pcall(marked, result)
      found = ok and buttons or {}
    end
  end
  for i, entry in ipairs(found) do draw(markFor(i), entry.button, entry.state) end
  for i = #found + 1, #marks do
    marks[i].pulse:Stop()
    marks[i]:Hide()
  end
end

local function planMenu(parent, width)
  local dropdown = CreateFrame("DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
  dropdown:SetWidth(width)
  dropdown:SetDefaultText("No plan")
  dropdown:SetupMenu(function(self, root)
    root:CreateRadio("No plan", function() return Talents.Chosen() == nil end, function() Talents.Choose(nil, self) end)
    for _, c in ipairs(Talents.Plans()) do
      root:CreateRadio(plain(c.name), function(id)
        local plan = Talents.Chosen()
        return plan ~= nil and plan.id == id
      end, function(id) Talents.Choose(id, self) end, c.id)
    end
  end)
  dropdowns[#dropdowns + 1] = dropdown
  return dropdown
end

-- Along the bottom of the talent window, either side of its Apply button: the plan picker at
-- the left (where other game versions have their loadouts), and where you are with it at the
-- right.
local function createBar()
  local bottom = talentFrame.Background or talentFrame
  bar = CreateFrame("Frame", nil, talentFrame)
  bar:SetSize(300, 28)
  bar:SetPoint("BOTTOMLEFT", bottom, "BOTTOMLEFT", 48, 6)
  bar:SetFrameLevel(1010) -- (with the window's search box: above its talents)
  local icon = bar:CreateTexture(nil, "ARTWORK")
  icon:SetSize(20, 20)
  icon:SetPoint("LEFT")
  icon:SetTexture(ns.ICON)
  local label = bar:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  label:SetPoint("LEFT", icon, "RIGHT", 6, 0)
  label:SetText("Talent plan")
  bar.dropdown = planMenu(bar, 170)
  bar.dropdown:SetPoint("LEFT", label, "RIGHT", 8, 0)
  bar.status = bar:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  bar.status:SetPoint("BOTTOMRIGHT", bottom, "BOTTOMRIGHT", -48, 14)
  bar.status:SetWidth(420)
  bar.status:SetJustifyH("RIGHT")
end

local function hook()
  if hooked then return end
  local frame = PlayerSpellsFrame and PlayerSpellsFrame.TalentsFrame
  if not (frame and frame.EnumerateAllTalentButtons and frame.GetConfigID and EventRegistry) then return end
  hooked, talentFrame = true, frame
  layer = CreateFrame("Frame", nil, frame.ButtonsParent or frame) -- (inside it: zooms with the talents)
  layer:SetAllPoints()
  -- The window shown again: our layer is inside it, so it's shown too.
  layer:SetScript("OnShow", Talents.UpdateMarks)
  createBar()
  EventRegistry:RegisterCallback("TalentFrameBase.ButtonsUpdated", Talents.UpdateMarks, Talents)
  Talents.UpdateMarks()
end

-- ---- Keeping up ----

-- from: the plan picker it was picked in (it shows the choice itself).
function Talents.Choose(id, from)
  local planKey = Talents.PlanKey()
  if not planKey then return end
  GargoyleDB.talentPlans[planKey] = id
  Talents.Update(from)
end

function Talents.Update(from)
  for _, dropdown in ipairs(dropdowns) do
    if dropdown ~= from then dropdown:GenerateMenu() end
  end
  Talents.UpdateMarks()
  if Talents.Refresh then Talents:Refresh(true) end
end

local watcher = CreateFrame("Frame")
watcher:SetScript("OnEvent", function(_, event, name)
  if event == "ADDON_LOADED" then
    if name == "Blizzard_PlayerSpells" then hook() end
  elseif event == "PLAYER_REGEN_ENABLED" then
    if afterCombat then
      afterCombat = false
      Talents.Update()
    end
  else
    Talents.Update()
  end
end)
watcher:RegisterEvent("ADDON_LOADED")

function Talents:OnLogin()
  hook() -- (in case the talent window was loaded already)
end

function Talents:OnEnable()
  for _, event in ipairs(EVENTS) do
    pcall(watcher.RegisterEvent, watcher, event) -- (one this version of the game doesn't have is skipped)
  end
  Talents.Update()
end

function Talents:OnDisable()
  watcher:UnregisterAllEvents()
  watcher:RegisterEvent("ADDON_LOADED")
  Talents.UpdateMarks()
end

-- ---- The tab ----

local ui = {}

local function lines(list)
  if #list <= LINES then return table.concat(list, "\n") end
  local shown = { unpack(list, 1, LINES - 1) }
  shown[LINES] = string.format("|cffb0b0b0and %d more|r", #list - LINES + 1)
  return table.concat(shown, "\n")
end

-- A talent with its points now and planned, in the color of its state.
local function talentLine(node, state)
  local color = (state.state == "now" and "ffd100") or (state.state == "over" and "e05050") or "ffffff"
  return string.format("|cff%s%s|r  |cffb0b0b0%d/%d|r", color, plain(node.name or "?"), node.rank, state.want)
end

-- fromMenu: the plan was picked in this tab's picker (it shows the choice itself).
function Talents:Refresh(fromMenu)
  if not ui.status then return end
  if ns.UpdateStatus then ns.UpdateStatus() end
  if not fromMenu then ui.dropdown:GenerateMenu() end
  ui.name:SetText(plain(ns.PlayerName() or "?") .. (talentSet() > 1 and "  |cffb0b0b0(second talents)|r" or ""))
  local result = Talents.Progress()
  ui.status:SetText(Talents.Summary(result))
  local todo, other = {}, {}
  if result then
    for _, node in ipairs(result.todo) do todo[#todo + 1] = talentLine(node, result.states[node.id]) end
    for _, node in ipairs(result.over) do other[#other + 1] = talentLine(node, result.states[node.id]) end
    for _, t in ipairs(result.missing) do
      other[#other + 1] = string.format("|cffb0b0b0%s (not in the game's talents)|r", plain(t.name))
    end
  end
  ui.todoHeading:SetShown(result ~= nil)
  ui.otherHeading:SetShown(#other > 0)
  ui.todo:SetText(result and (#todo > 0 and lines(todo) or "Nothing: every planned point is in.") or "")
  ui.other:SetText(lines(other))
end

function Talents:CreatePanel(panel)
  ui.panel = panel
  local card = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  card:SetPoint("TOPLEFT")
  card:SetPoint("TOPRIGHT")
  card:SetHeight(122)
  ui.name = card:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  ui.name:SetPoint("TOPLEFT", 16, -14)
  ui.name:SetPoint("RIGHT", -16, 0)
  ui.name:SetJustifyH("LEFT")
  local follow = card:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  follow:SetPoint("TOPLEFT", ui.name, "BOTTOMLEFT", 0, -14)
  follow:SetText("Follow the talents of")
  ui.dropdown = planMenu(card, 200)
  ui.dropdown:SetPoint("LEFT", follow, "RIGHT", 10, 0)
  ui.status = card:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  ui.status:SetPoint("TOPLEFT", follow, "BOTTOMLEFT", 0, -14)
  ui.status:SetPoint("RIGHT", -16, 0)
  ui.status:SetJustifyH("LEFT")
  local about = card:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  about:SetPoint("TOPLEFT", ui.status, "BOTTOMLEFT", 0, -8)
  about:SetPoint("RIGHT", -16, 0)
  about:SetJustifyH("LEFT")
  about:SetText("In the game's talent window, talents the plan still wants have a Gargoyle mark with the points it puts "
    .. "in them, and glow when a point can go in now. A red mark means more points than the plan. You pick the talents.")

  local list = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  list:SetPoint("TOPLEFT", card, "BOTTOMLEFT", 0, -6)
  list:SetPoint("BOTTOMRIGHT")
  local function column(x, heading)
    local h = list:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    h:SetPoint("TOPLEFT", x, -10)
    h:SetText(heading)
    local text = list:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    text:SetPoint("TOPLEFT", h, "BOTTOMLEFT", 0, -8)
    text:SetWidth(320)
    text:SetJustifyH("LEFT")
    text:SetJustifyV("TOP")
    return h, text
  end
  ui.todoHeading, ui.todo = column(12, "Still to take (points now / planned)")
  ui.otherHeading, ui.other = column(360, "Not as planned")
end
