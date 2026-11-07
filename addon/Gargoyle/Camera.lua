-- Gargoyle camera: where the camera sits (sideways and up), as the game's own camera settings
-- ("CVars", the same ones Blizzard's options window changes). WoW Forever's options have no camera
-- offset, but the engine has retail's hidden ones, which only an addon can set (typed /console
-- commands don't reach them here).
--
--   /gargoyle camera              shows each related setting
--   /gargoyle camera side 1.5     test_cameraOverShoulder: sideways, positive right, negative left (about -2 to 2)
--   /gargoyle camera up 0.5       the view's height, as a strength from 0 to 1 (0 turns it off): dynamic pitch
--                                 (test_cameraDynamicPitch) on, with test_cameraDynamicPitchBaseFovPad and
--                                 ...BaseFovPadFlying set to 0.85 - 0.80 x strength. The game's padding works
--                                 backwards (a small padding lifts the view most), so the strength is the other
--                                 way round: 1 is the most lift (padding 0.05), a small strength a slight lift
--   /gargoyle camera pitch        the game has no setting for the camera's tilt: it says so
--   /gargoyle camera reset        the game's own values, from before Gargoyle first changed them
--
-- What you pick is kept in GargoyleDB.camera and set again at login (some clients forget "test_"
-- settings), and the first value each setting had is kept too, for reset. The game's settings are
-- never touched in combat: a change then waits for combat to end.
--
-- Blizzard's add-on rules: it only sets the game's own settings, when you ask, and automates nothing.
local _, ns = ...

local Camera = {}
ns.Camera = Camera

local OVER = "test_cameraOverShoulder"
local PITCH = "test_cameraDynamicPitch"
local FOV = "test_cameraDynamicPitchBaseFovPad"
local FOV_FLYING = "test_cameraDynamicPitchBaseFovPadFlying"
local PIVOT = "test_cameraDynamicPitchSmartPivotCutoffDist" -- (only shown: it is where the view's pivot changes, not a tilt)
-- The Accessibility > Motion Sickness option sets these two (Keep centered off, Reduce movement on). While
-- "keep character centred" is on the engine holds the camera in the middle and ignores the offsets.
local CENTERED = "CameraKeepCharacterCentered"
local REDUCE = "CameraReduceUnexpectedMovement"
local RELATED = { OVER, PITCH, FOV, FOV_FLYING, PIVOT, CENTERED, REDUCE }

Camera.SIDE_MIN, Camera.SIDE_MAX = -5, 5 -- (what a command accepts; the options page's slider shows -2 to 2)
Camera.SLIDER_MIN, Camera.SLIDER_MAX = -2, 2
Camera.UP_MIN, Camera.UP_MAX = 0, 1
Camera.PAD_WEAK, Camera.PAD_STRONG = 0.85, 0.05 -- (the padding at strength 0+ and at strength 1)

-- The game's padding for a strength: 0.85 - 0.80 x strength (strength 1: 0.05, the most lift).
function Camera.PadFor(strength)
  return Camera.PAD_WEAK - (Camera.PAD_WEAK - Camera.PAD_STRONG) * strength
end

-- The strength a padding stands for (the other way round), 0 to 1.
function Camera.StrengthFor(pad)
  return math.max(0, math.min(1, (Camera.PAD_WEAK - pad) / (Camera.PAD_WEAK - Camera.PAD_STRONG)))
end

local say = ns.say

-- GargoyleDB.camera: side and up (what was picked: a number, or nil), before (the game's own value
-- of each setting Gargoyle changed, as text, from before the first change).
local function db()
  if type(GargoyleDB.camera) ~= "table" then GargoyleDB.camera = {} end
  local saved = GargoyleDB.camera
  if type(saved.before) ~= "table" then saved.before = {} end
  if type(saved.side) ~= "number" then saved.side = nil end
  if type(saved.up) ~= "number" then saved.up = nil end
  -- Before upMode 2, "up" was the padding itself (higher: less lift). It is a strength now: convert once
  -- (a padding of 0.85 or more did nothing, so that becomes 0, off).
  if saved.up ~= nil and saved.upMode ~= 2 then
    if saved.up > 0 then saved.up = math.floor(Camera.StrengthFor(saved.up) * 100 + 0.5) / 100 end
  end
  saved.upMode = 2
  return saved
end

local function locked()
  return InCombatLockdown() == true
end

-- A game setting's value as text, or nil if this game doesn't have it.
local function cvar(name)
  local ok, value = pcall(GetCVar, name)
  if ok and value ~= nil then return tostring(value) end
  return nil
end

-- (the game keeps some numbers a hair off: 0.35 comes back 0.3499999)
local function same(a, b)
  local x, y = tonumber(a), tonumber(b)
  if x and y then return math.abs(x - y) < 0.0001 end
  return a == b
end

local function tidy(value) -- (a number as text, two decimals at most)
  return tostring(math.floor(value * 100 + 0.5) / 100)
end

local function clamp(value, low, high)
  return math.max(low, math.min(high, value))
end

function Camera.Has(name)
  return cvar(name) ~= nil
end

local pending = false -- (something waits for combat to end)

-- Set a game setting to a value (not if it already is), keeping the first value it had. Gives back
-- what the game kept, or nil if this game doesn't have the setting.
local function put(name, value)
  local now = cvar(name)
  if now == nil then return nil end
  local saved = db()
  if saved.before[name] == nil then saved.before[name] = now end
  if not same(now, value) then pcall(SetCVar, name, tostring(value)) end
  return cvar(name)
end

local function told(name, value, kept, quiet)
  if quiet then return end
  if kept == nil then
    say(name .. ": this game doesn't have that setting")
  else
    say(string.format("set %s to %s: the game kept %s", name, tostring(value), kept))
  end
end

local restore

local function applySide(value, quiet)
  told(OVER, tidy(value), put(OVER, tidy(value)), quiet)
end

-- Up: the strength. 0 turns dynamic pitch off (and puts both paddings back as they were); above 0 turns it
-- on with both view paddings at 0.85 - 0.80 x strength.
local function applyUp(value, quiet)
  if value <= 0 then
    told(PITCH, 0, put(PITCH, 0), quiet)
    restore(quiet, { FOV, FOV_FLYING })
  else
    local pad = tidy(Camera.PadFor(value))
    told(PITCH, 1, put(PITCH, 1), quiet)
    told(FOV, pad, put(FOV, pad), quiet)
    told(FOV_FLYING, pad, put(FOV_FLYING, pad), quiet)
    if not quiet then say(string.format("higher view: strength %s (padding %s)", tidy(value), pad)) end
  end
end

-- Put the settings Gargoyle changed back to the value they had at first (only: a list of names, else all).
function restore(quiet, only)
  local saved = db()
  local names = {}
  if only then
    for _, name in ipairs(only) do
      if saved.before[name] ~= nil then names[#names + 1] = name end
    end
  else
    for name in pairs(saved.before) do names[#names + 1] = name end
  end
  table.sort(names)
  for _, name in ipairs(names) do
    local was = saved.before[name]
    if type(was) == "string" and cvar(name) ~= nil then
      if not same(cvar(name), was) then pcall(SetCVar, name, was) end
      if not quiet then say(string.format("%s is %s again", name, cvar(name) or "nothing")) end
    end
    saved.before[name] = nil
  end
end

-- "Keep character centred" would hold the camera in the middle, so it is off while an offset is set
-- (and "reduce unexpected movement", which also blocks the sideways offset and damps dynamic pitch). With both
-- offsets at 0 nothing is forced: the game's own values are put back.
local function applyCentering(quiet)
  local saved = db()
  local sideOn = saved.side ~= nil and saved.side ~= 0
  local upOn = saved.up ~= nil and saved.up > 0
  if sideOn or upOn then
    told(CENTERED, 0, put(CENTERED, 0), true)
  else
    restore(quiet, { CENTERED })
  end
  if sideOn or upOn then -- (since game patch 11.0.2 "reduce unexpected movement" also blocks the sideways offset)
    if cvar(REDUCE) == "1" then told(REDUCE, 0, put(REDUCE, 0), true) end
  else
    restore(quiet, { REDUCE })
  end
end

-- Make the game's settings what was picked (or, when nothing is picked but something is still
-- changed, put them back). Not in combat: then after it. quiet: no chat.
function Camera.Apply(quiet)
  local saved = db()
  if saved.side == nil and saved.up == nil and next(saved.before) == nil then
    pending = false
    return
  end
  if locked() then
    pending = true
    return
  end
  pending = false
  if saved.side == nil and saved.up == nil then
    restore(quiet)
    return
  end
  if saved.side ~= nil then applySide(saved.side, quiet) end
  if saved.up ~= nil then applyUp(saved.up, quiet) end
  applyCentering(quiet)
end

function Camera.SetSide(value, quiet)
  value = clamp(math.floor(value * 100 + 0.5) / 100, Camera.SIDE_MIN, Camera.SIDE_MAX)
  if not Camera.Has(OVER) then
    told(OVER, value, nil, quiet)
    return false
  end
  db().side = value
  if locked() then
    pending = true
    if not quiet then say("in combat: the camera is moved sideways to " .. tidy(value) .. " when the fight ends.") end
    return true
  end
  applySide(value, quiet)
  applyCentering(quiet)
  return true
end

function Camera.SetUp(value, quiet)
  value = clamp(math.floor(value * 100 + 0.5) / 100, Camera.UP_MIN, Camera.UP_MAX)
  if not Camera.Has(PITCH) then
    told(PITCH, value, nil, quiet)
    return false
  end
  db().up = value
  if locked() then
    pending = true
    if not quiet then say("in combat: the camera's height is set to " .. tidy(value) .. " when the fight ends.") end
    return true
  end
  applyUp(value, quiet)
  applyCentering(quiet)
  return true
end

function Camera.Reset(quiet)
  local saved = db()
  if saved.side == nil and saved.up == nil and next(saved.before) == nil then
    if not quiet then say("nothing to reset: Gargoyle hasn't changed your camera.") end
    return
  end
  saved.side, saved.up = nil, nil -- (not applied again from now on)
  if locked() then
    pending = true
    if not quiet then say("in combat: the camera goes back as it was when the fight ends.") end
    return
  end
  restore(quiet)
  if not quiet then say("camera back as it was. Gargoyle no longer sets it.") end
end

-- What the options page's sliders start at: what was picked, else what the game has now.
function Camera.SideValue()
  local saved = db()
  return saved.side or tonumber(cvar(OVER)) or 0
end

function Camera.UpValue()
  local saved = db()
  if saved.up ~= nil then return saved.up end
  if tonumber(cvar(PITCH)) == 1 and tonumber(cvar(FOV)) then return Camera.StrengthFor(tonumber(cvar(FOV))) end
  return 0
end

function Camera.Show()
  for _, name in ipairs(RELATED) do say(name .. " is " .. (cvar(name) or "not in this game")) end
  local saved = db()
  if saved.side == nil and saved.up == nil then
    say("Gargoyle isn't setting your camera. /gargoyle camera side <number> or up <number> does.")
  else
    say(string.format("Gargoyle sets side to %s and up (strength) to %s at login. /gargoyle camera reset stops that.",
      saved.side and tidy(saved.side) or "(not picked)", saved.up and tidy(saved.up) or "(not picked)"))
  end
end

Camera.PITCH_TEXT = "the game has no setting for the camera's tilt (pitch): tilt it with the mouse. "
  .. "/gargoyle camera up (a strength) is the closest: it lowers your character on the screen."

Camera.HELP = "/gargoyle camera shows the camera settings; /gargoyle camera side <-2 to 2> moves it sideways (negative: left), "
  .. "up <strength 0 to 1> frames your character lower (0: off), pitch says why there's no tilt setting, reset puts it all back."

-- "/gargoyle camera <args>" (the core's /gargoyle passes the rest, in lower case).
function Camera.Command(args)
  local sub, rest = (args or ""):match("^(%S+)%s*(.-)$")
  if not sub then
    Camera.Show()
  elseif sub == "reset" then
    Camera.Reset()
  elseif sub == "pitch" then
    say(Camera.PITCH_TEXT)
  elseif sub == "side" or sub == "up" then
    local number = tonumber(rest)
    if not number or number ~= number or math.abs(number) == math.huge then
      say(Camera.HELP)
    elseif sub == "side" then
      Camera.SetSide(number)
    else
      Camera.SetUp(number)
    end
  else
    say(Camera.HELP)
  end
end

local events = CreateFrame("Frame")
events:SetScript("OnEvent", function(_, event)
  if event == "PLAYER_REGEN_ENABLED" then
    if pending then
      Camera.Apply(true)
      say("camera settings applied.")
    end
  else -- (PLAYER_LOGIN, PLAYER_ENTERING_WORLD: some clients forget "test_" settings at login)
    Camera.Apply(true)
  end
end)
for _, event in ipairs({ "PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "PLAYER_REGEN_ENABLED" }) do
  pcall(events.RegisterEvent, events, event)
end
