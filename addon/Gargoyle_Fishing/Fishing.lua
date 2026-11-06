-- Gargoyle Fishing: easy fishing. An addon of its own that needs Gargoyle (the core), which it
-- uses through the Gargoyle table.
--
--   * A key casts Fishing: "Cast Fishing" in Key Bindings > Gargoyle (Bindings.xml).
--   * Right-clicking the bobber reels in, as the game always does: this addon leaves it alone.
--   * One key (an option, on to start with): while you fish, the Cast Fishing key is the game's
--     Interact With Target, so the same key reels in. The game's Interact key only reaches 10 yards
--     to start with, so while you fish its reach is 30 yards and a wider arc (game settings), put
--     back as they were when fishing ends, as combat starts and as you log out.
--   * Louder splash (an option, on to start with, for players who listen for the bite): while you
--     fish, sound effects go up to full and music and ambient sounds go down (game settings),
--     put back the same way.
--
-- Blizzard's add-on rules, and no risk to your account: every cast is your own key press, going
-- through a secure action button (SecureActionButtonTemplate, type "spell"), which is how the game
-- lets addons cast at all. The addon never watches for a bite, never casts by itself, has no
-- timers, and does nothing in combat (its override binding is cleared as combat starts).
local _, ns = ...
local G = Gargoyle
if not G then -- (Gargoyle, the core, isn't loaded: the .toc needs it)
  print("|cffd4a017Gargoyle|r: Gargoyle Fishing needs the Gargoyle addon. Install it with the Gargoyle app (or turn Gargoyle Fishing off).")
  return
end

local KEY_BUTTON = "GargoyleFishingButton" -- (the Cast Fishing key's button: Bindings.xml)
local KEY_BINDING = "CLICK " .. KEY_BUTTON .. ":LeftButton"
-- In WoW Forever each rank of Fishing is two spells, both called "Fishing": the cast (it throws the
-- bobber: Apprentice 7620, Journeyman 7731, Expert 7732, Artisan 18248) and, learned with it, the
-- profession's "open the window" spell (1240948, 1240959, 1240970, 1240983), which comes first in
-- the spellbook. So the button casts by spell ID, never by name: the best rank this character knows.
local FISHING_CASTS = { 18248, 7732, 7731, 7620 } -- (best first)
local IS_CAST = { [18248] = true, [7732] = true, [7731] = true, [7620] = true }
local OPENS_WINDOW = { [1240948] = true, [1240959] = true, [1240970] = true, [1240983] = true }
local FISHING_SKILLS = { [356] = true, [2943] = true } -- (Fishing's skill lines: the casts', the window's)

-- Key Bindings > Gargoyle > Cast Fishing.
BINDING_HEADER_GARGOYLE = "Gargoyle"
_G["BINDING_NAME_" .. KEY_BINDING] = "Cast Fishing"

local Fishing = {
  title = "Fishing",
  description = "Cast Fishing with one key (set it in Key Bindings > Gargoyle), and press it again to reel in (or right-click the bobber).",
}
G.RegisterModule("fishing", Fishing)
ns.Fishing, G.Fishing = Fishing, Fishing

-- GargoyleDB.fishing: oneKey and louder (the options: on unless false), reach and sound (the game's
-- own settings while fishing has changed them, for putting back), and before (the game settings
-- "/gargoyle fishing test" changed, as they were, for "/gargoyle fishing restore").
local function db()
  if type(GargoyleDB.fishing) ~= "table" then GargoyleDB.fishing = {} end
  return GargoyleDB.fishing
end

local function locked()
  return InCombatLockdown() == true
end

-- ---- The secure button (it does the casting: the game only lets a click or key press cast) ----

-- The key casts as it goes down; on its release nothing happens (so in one-key mode, the release
-- after reeling in can't cast again).
local keyButton = CreateFrame("Button", KEY_BUTTON, nil, "SecureActionButtonTemplate")
keyButton:RegisterForClicks("AnyDown")
keyButton:SetAttribute("type", "spell")
keyButton:SetAttribute("useOnKeyDown", true)
local keyOwner = CreateFrame("Frame") -- (one-key mode's override binding belongs to it)

-- Does this character know the spell? (nil: the game can't say)
local function knows(spellID)
  if C_SpellBook and C_SpellBook.IsSpellKnown then return C_SpellBook.IsSpellKnown(spellID) == true end
  if IsPlayerSpell then return IsPlayerSpell(spellID) == true end
  if IsSpellKnown then return IsSpellKnown(spellID) == true end
end

-- When none of the casts above is known (a rank this addon doesn't know of yet): the Fishing
-- profession's spellbook entry that isn't passive and doesn't open the profession window.
local function castInSpellBook()
  local book = C_SpellBook and C_SpellBook.GetSpellBookItemInfo
  local bank = Enum and Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player
  if not (book and bank and GetProfessions and GetProfessionInfo) then return end
  local canShow = C_TradeSkillUI and C_TradeSkillUI.CanTradeSkillShowCraftingUI
  local spellType = Enum.SpellBookItemType and Enum.SpellBookItemType.Spell
  local _, _, _, fish = GetProfessions() -- (Fishing is the 4th, in Forever's professions book)
  for _, index in pairs({ GetProfessions() }) do
    local _, _, _, _, numSpells, offset, skillLine = GetProfessionInfo(index)
    if (index == fish or FISHING_SKILLS[skillLine]) and offset then
      for slot = offset + 1, offset + (numSpells or 0) do
        local info = book(slot, bank)
        local id = info and info.spellID
        if id and not info.isPassive and not OPENS_WINDOW[id] and (spellType == nil or info.itemType == spellType)
          and not (canShow and canShow(id)) then
          return id
        end
      end
    end
  end
end

-- Fishing's cast (its spell ID: what the button casts), or nil if this character hasn't learned it.
local function fishingSpell()
  for _, id in ipairs(FISHING_CASTS) do
    if knows(id) then return id end
  end
  return castInSpellBook()
end

local waiting = false -- (something waits for combat to end: the key's spell, the binding, the reach)

-- The Cast Fishing key's spell (at login, and when professions or spells change): Fishing's cast,
-- or none while Gargoyle Fishing is turned off (then the key does nothing). Not in combat: then after it.
local function setUpKey()
  if locked() then
    waiting = true
    return
  end
  local spell = G.IsEnabled("fishing") and fishingSpell() or nil
  if keyButton:GetAttribute("spell") ~= spell then keyButton:SetAttribute("spell", spell) end
end

-- ---- One key: while Fishing is channelled, the Cast Fishing key is Interact With Target (the
-- game's own binding, INTERACTTARGET), so the same key reels in. Cleared when fishing stops. ----

local function oneKey()
  return db().oneKey ~= false -- (on unless turned off)
end

local oneKeyBound = false

local function clearKey()
  if not oneKeyBound then return end
  if locked() then
    waiting = true
    return
  end
  ClearOverrideBindings(keyOwner)
  oneKeyBound = false
end

local toldNoKey = false
local function bindInteract()
  if locked() or not oneKey() then return end
  local keys = { GetBindingKey(KEY_BINDING) }
  for _, key in ipairs(keys) do SetOverrideBinding(keyOwner, true, key, "INTERACTTARGET") end
  oneKeyBound = #keys > 0
  if #keys == 0 and not toldNoKey then
    toldNoKey = true
    G.say("one-key fishing needs a key: bind one to Cast Fishing in Key Bindings > Gargoyle.")
  end
end

-- ---- The Interact key's reach while you fish (game settings, "CVars"): 10 yards to start with,
-- not enough for the bobber. As fishing starts: what they were is kept in GargoyleDB.fishing.reach
-- (so a crash or /reload mid-cast puts them back at the next login), then the reach is 30 yards,
-- the arc wider, and soft targeting on for anything (3: Any). Put back as fishing stops, as combat
-- starts (or after it) and as you log out. ----

local function cvar(name)
  local ok, value = pcall(GetCVar, name)
  if ok and value ~= nil then return tostring(value) end
  return nil
end

local REACH = { { "softTargetInteract", 3, true }, -- (true: only raised, never lowered)
                { "SoftTargetInteractRange", 30 }, { "SoftTargetInteractArc", 2 } }

-- Louder splash, the same way: effects up to full (and on), music and ambient sounds down to nothing.
-- (Sound_EnableAllSound and the master volume are the player's own: never touched. A setting this
-- game doesn't have is skipped.)
local LOUDER = { { "Sound_EnableSFX", 1, true }, { "Sound_SFXVolume", 1, true },
                 { "Sound_MusicVolume", 0 }, { "Sound_AmbienceVolume", 0 } }

-- Keep the game's own values of a list of settings in GargoyleDB.fishing[field], then set them
-- (only the ones not already at the value: setting them again while they are does nothing).
local function settingsOut(field, list)
  local saved = db()
  if type(saved[field]) ~= "table" then -- (already kept: those are the game's own, keep them)
    local was = {}
    for _, r in ipairs(list) do was[r[1]] = cvar(r[1]) end
    saved[field] = was
  end
  for _, r in ipairs(list) do
    local name, value, raiseOnly = r[1], r[2], r[3]
    local now = tonumber(cvar(name))
    if now ~= nil and not (raiseOnly and now >= value) and now ~= value then pcall(SetCVar, name, tostring(value)) end
  end
end

-- keep: leave the record in GargoyleDB (at logout, in case the game doesn't keep a setting changed
-- then: the next login puts them back again).
local function settingsBack(field, list, keep)
  local saved = db()
  if type(saved[field]) ~= "table" then return end
  if locked() then
    waiting = true
    return
  end
  for _, r in ipairs(list) do
    local was = saved[field][r[1]]
    if type(was) == "string" and cvar(r[1]) ~= was then pcall(SetCVar, r[1], was) end
  end
  if not keep then saved[field] = nil end
end

local function louder()
  return db().louder ~= false -- (on unless turned off)
end

local function reachOut()
  if locked() or not oneKey() then return end
  settingsOut("reach", REACH)
end

local function soundOut()
  if locked() or not louder() then return end
  settingsOut("sound", LOUDER)
end

local function reachBack(keep)
  settingsBack("reach", REACH, keep)
end

local function soundBack(keep)
  settingsBack("sound", LOUDER, keep)
end

local function isFishing(spellID)
  return spellID ~= nil and (IS_CAST[spellID] or spellID == keyButton:GetAttribute("spell"))
end

local events = CreateFrame("Frame")
events:SetScript("OnEvent", function(_, event, unit, _, spellID)
  if event == "PLAYER_REGEN_DISABLED" then -- (just before combat locks things: clear them now)
    clearKey()
    reachBack()
    soundBack()
  elseif event == "PLAYER_REGEN_ENABLED" then
    if waiting then
      waiting = false
      clearKey()
      reachBack()
      soundBack()
      setUpKey()
    end
  elseif event == "UNIT_SPELLCAST_CHANNEL_START" then
    if unit == "player" and isFishing(spellID) then
      bindInteract()
      reachOut()
      soundOut()
    end
  elseif event == "UNIT_SPELLCAST_CHANNEL_STOP" then
    if unit == "player" then -- (fishing ended)
      clearKey()
      reachBack()
      soundBack()
    end
  elseif event == "PLAYER_LOGOUT" then
    reachBack(true)
    soundBack(true)
  else -- (SKILL_LINES_CHANGED, SPELLS_CHANGED, LEARNED_SPELL_IN_SKILL_LINE: maybe a new rank)
    setUpKey()
  end
end)

local EVENTS = { "PLAYER_REGEN_DISABLED", "PLAYER_REGEN_ENABLED", "UNIT_SPELLCAST_CHANNEL_START",
                 "UNIT_SPELLCAST_CHANNEL_STOP", "PLAYER_LOGOUT", "SKILL_LINES_CHANGED", "SPELLS_CHANGED",
                 "LEARNED_SPELL_IN_SKILL_LINE" }

function Fishing:OnLogin()
  db()
  reachBack() -- (left over from a crash or a /reload while fishing)
  soundBack()
  setUpKey()
end

function Fishing:OnEnable()
  for _, event in ipairs(EVENTS) do pcall(events.RegisterEvent, events, event) end
  setUpKey()
end

-- Off: the Cast Fishing key does nothing (its button has no spell) and one-key mode stops.
function Fishing:OnDisable()
  events:UnregisterAllEvents()
  clearKey()
  reachBack()
  soundBack()
  setUpKey()
  if waiting then pcall(events.RegisterEvent, events, "PLAYER_REGEN_ENABLED") end -- (to finish after combat)
end

Fishing.options = {
  { "One key: the Cast Fishing key also reels in (the game's Interact key, with its reach set to 30 yards while you fish)",
    oneKey,
    function(on)
      db().oneKey = on and true or false
      if not on then
        clearKey()
        reachBack()
      end
    end },
  { "Louder splash: while you fish, sound effects go up to full and music and ambient sounds go down, so you can hear the bite",
    louder,
    function(on)
      db().louder = on and true or false
      if not on then soundBack() end
    end },
}

-- ---- /gargoyle fishing test: the game's interact range settings ----

-- What the game's Interact key reaches is set by these (game settings, "CVars"): the test shows
-- them, sets a longer range and a wider arc, and shows what the game kept (it may cap them).
local CVARS = { "softTargetInteract", "SoftTargetInteractRange", "SoftTargetInteractArc", "SoftTargetInteractRangeIsHard" }
local TRY = { { "SoftTargetInteractRange", "30" }, { "SoftTargetInteractArc", "2" } }

function Fishing.Test()
  if locked() then
    G.say("not in combat: try again after the fight.")
    return
  end
  for _, name in ipairs(CVARS) do G.say(name .. " is " .. (cvar(name) or "not in this game")) end
  local saved = db()
  for _, try in ipairs(TRY) do
    local name, value = try[1], try[2]
    local was = cvar(name)
    if was then
      saved.before = type(saved.before) == "table" and saved.before or {}
      if saved.before[name] == nil then saved.before[name] = was end -- (the first test's: the game's own)
      pcall(SetCVar, name, value)
      G.say(string.format("set %s to %s: the game kept %s", name, value, cvar(name) or "nothing"))
    end
  end
  G.say("/gargoyle fishing restore puts them back as they were.")
end

function Fishing.Restore()
  if locked() then
    G.say("not in combat: try again after the fight.")
    return
  end
  local saved = db()
  if type(saved.before) ~= "table" or next(saved.before) == nil then
    G.say("nothing to put back: /gargoyle fishing test hasn't changed anything.")
    return
  end
  for _, try in ipairs(TRY) do
    local name = try[1]
    local was = saved.before[name]
    if type(was) == "string" then
      pcall(SetCVar, name, was)
      G.say(string.format("%s is %s again", name, cvar(name) or "nothing"))
    end
  end
  saved.before = nil
end

local HELP = "/gargoyle fishing test shows the game's interact range settings and tries a longer range; "
  .. "/gargoyle fishing restore puts them back."

-- "/gargoyle fishing ..." (the core's /gargoyle handles everything else).
local gargoyle = SlashCmdList.GARGOYLE
SlashCmdList.GARGOYLE = function(message)
  local text = strtrim(message or ""):lower()
  local command = text:match("^fishing%s*(.*)$")
  if command == "test" then
    Fishing.Test()
  elseif command == "restore" then
    Fishing.Restore()
  elseif command then
    G.say(HELP)
  else
    gargoyle(message)
    if text == "help" then G.say(HELP) end
  end
end
