-- Raid signups: your guilds' upcoming raids from the website, and signing up in game.
--
-- The raids come from the Gargoyle app (ns.sync, as fresh as your last login or reload).
-- A signup made here goes into GargoyleDB.outbox; the game saves that on reload or
-- logout, and the app sends it to the website, which applies the same rules as signing up
-- there (your character, on that guild's roster, before the raid starts). Once the
-- website has it, the app lists it in GargoyleSync.done and it leaves the outbox.
local _, ns = ...

local Raids = {
  title = "Raid signups",
  description = "Your guilds' upcoming raids, who's coming, and signing up in game.",
}
ns.RegisterModule("raids", Raids)
ns.Raids = Raids

local STATUSES = { "accepted", "tentative", "declined" }
local STATUS_LABEL = { accepted = "Coming", tentative = "Tentative", declined = "Can't come" }
local STATUS_COLOR = { accepted = "|cff40c040", tentative = "|cffe0c040", declined = "|cffe05050" }
local ROLES = { "tank", "healer", "dps" }
local ROLE_LABEL = { tank = "Tank", healer = "Healer", dps = "Damage" }
local ROLE_PLURAL = { tank = "Tanks", healer = "Healers", dps = "Damage" }
-- Why the website turned a signup down (results from the app; see app_api.py).
local REASONS = {
  stale = "it was changed on the website or in Discord after you made it",
  started = "the raid had already started",
  invalid = "that character isn't on the guild's roster any more",
  not_found = "the raid was deleted",
}
local KEEP_DAYS = 30 -- unsent signups older than this are dropped
local NAMES_SHOWN = 14 -- per role in the roster

-- Text typed by other players, shown as it is: "|" starts the game's color, icon and link
-- codes, so it's doubled to show a plain "|".
local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

local function isOneOf(value, options)
  for _, v in ipairs(options) do
    if v == value then return true end
  end
  return false
end

-- ---- Data ----

-- Every upcoming raid in your guilds, soonest first.
function Raids.List()
  local raids, now = {}, time()
  for _, guild in ipairs(ns.sync.guilds) do
    for _, raid in ipairs(guild.raids) do
      if raid.start > now then raids[#raids + 1] = raid end
    end
  end
  table.sort(raids, function(a, b)
    if a.start ~= b.start then return a.start < b.start end
    return a.id < b.id
  end)
  return raids
end

-- A signup made here that the website hasn't confirmed yet.
function Raids.Pending(raid)
  for i = #GargoyleDB.outbox, 1, -1 do
    local action = GargoyleDB.outbox[i]
    if action.raid == raid.id then return action end
  end
end

-- Your signup: the one waiting to sync, else what the website last said. Nil if none.
function Raids.Mine(raid)
  local pending = Raids.Pending(raid)
  if pending then
    return { status = pending.status, role = pending.role, character = pending.character, note = pending.note, pending = true }
  end
  for _, s in ipairs(raid.signups) do
    if s.mine then
      return { status = s.status, role = s.role, character = s.character, note = s.note, pending = false }
    end
  end
end

-- Your characters on this raid's guild roster (only those can sign up).
function Raids.Characters(raid)
  local found = {}
  for _, c in ipairs(ns.sync.characters) do
    if c.guild == raid.guild.id then found[#found + 1] = c end
  end
  return found
end

function Raids.Character(id)
  for _, c in ipairs(ns.sync.characters) do
    if c.id == id then return c end
  end
end

-- Who to sign up with: the one you used before, else the character you're playing (imported
-- from the game, or named like it), else the first.
function Raids.DefaultCharacter(raid)
  local characters = Raids.Characters(raid)
  local mine = Raids.Mine(raid)
  for _, c in ipairs(characters) do
    if mine and c.id == mine.character then return c end
  end
  local key = ns.PlayerKey()
  for _, c in ipairs(characters) do
    if key and c.game == key then return c end
  end
  for _, playing in ipairs({ ns.PlayerName() or "", (UnitName("player")) or "" }) do -- (full name, then first)
    for _, c in ipairs(characters) do
      if c.name:lower() == playing:lower() then return c end
    end
  end
  return characters[1]
end

-- Everyone coming, with your own change (if any) in place of what the website had.
function Raids.Roster(raid)
  local roster = {}
  for _, s in ipairs(raid.signups) do
    if not s.mine then roster[#roster + 1] = s end
  end
  local mine = Raids.Mine(raid)
  if mine then
    local c = Raids.Character(mine.character)
    roster[#roster + 1] = { name = c and c.name or "You", class = c and c.class or "", role = mine.role,
                            status = mine.status, mine = true }
  end
  return roster
end

function Raids.Counts(raid)
  local counts = { accepted = 0, tentative = 0, declined = 0, tank = 0, healer = 0, dps = 0 }
  for _, s in ipairs(Raids.Roster(raid)) do
    if counts[s.status] then counts[s.status] = counts[s.status] + 1 end
    if s.status == "accepted" and counts[s.role] then counts[s.role] = counts[s.role] + 1 end
  end
  return counts
end

-- Record a signup to send. Returns nil, or why it can't be made.
function Raids.SignUp(raid, status, characterId, role, note)
  if raid.start <= time() then return "That raid has started, so signups are closed." end
  if not isOneOf(status, STATUSES) or not isOneOf(role, ROLES) then return "Pick a status and a role." end
  local ok = false
  for _, c in ipairs(Raids.Characters(raid)) do
    if c.id == characterId then ok = true end
  end
  if not ok then return "Pick one of your characters on this guild's roster." end
  -- Only the latest change per raid needs sending.
  for i = #GargoyleDB.outbox, 1, -1 do
    if GargoyleDB.outbox[i].raid == raid.id then table.remove(GargoyleDB.outbox, i) end
  end
  GargoyleDB.outbox[#GargoyleDB.outbox + 1] = {
    id = string.format("%x-%04x", time(), math.random(0, 0xffff)),
    raid = raid.id, character = characterId, status = status, role = role,
    note = ns.Cut(note or "", 200), at = time(), title = raid.title, start = raid.start,
  }
end

-- At login: drop what the website has answered (saying so when it said no), and what can't
-- be sent any more (the raid started, or it's very old).
function Raids:OnLogin()
  local kept, now = {}, time()
  for _, action in ipairs(GargoyleDB.outbox) do
    if type(action) == "table" and type(action.id) == "string" then
      local result = ns.sync.done[action.id]
      if result then
        if result ~= "saved" then
          ns.say(string.format("your signup for %s wasn't saved: %s.", plain(action.title or "a raid"), REASONS[result] or plain(result)))
        end
      elseif (action.start or 0) > now and now - (action.at or 0) < KEEP_DAYS * 86400 then
        kept[#kept + 1] = action
      end
    end
  end
  GargoyleDB.outbox = kept
end

-- (The new-raid glow and reminders follow the feature being on or off: RaidAlerts.lua.)
function Raids:OnEnable()
  ns.RaidAlerts.Update()
end

function Raids:OnDisable()
  ns.RaidAlerts.Update()
end

-- ---- The tab ----

local ROW_HEIGHT, ROWS = 40, 9
-- The game's art: the small role icons it puts in text (its INLINE_TANK_ICON and so on, at
-- 16 pixels), and the ready check's marks.
local ROLE_ICON = { tank = "UI-LFG-RoleIcon-Tank-Micro-GroupFinder", healer = "UI-LFG-RoleIcon-Healer-Micro-GroupFinder",
                    dps = "UI-LFG-RoleIcon-DPS-Micro-GroupFinder" }
local STATUS_ICON = { accepted = "UI-LFG-ReadyMark", tentative = "UI-LFG-PendingMark", declined = "UI-LFG-DeclineMark" }
local ui = {}
local selected, offset = nil, 0
local picks = {} -- raid id -> { character, role } chosen in the dropdowns, not yet signed up

local function classColor(class)
  local color = RAID_CLASS_COLORS and RAID_CLASS_COLORS[(class or ""):upper()]
  return color and color.colorStr and ("|c" .. color.colorStr) or "|cffffffff"
end

local function when(start)
  return date("%a %d %b, %H:%M", start)
end
Raids.When = when

local function statusText(status)
  return string.format("%s %s%s|r", ns.Icon(STATUS_ICON[status], 16), STATUS_COLOR[status] or "",
    STATUS_LABEL[status] or plain(status))
end

local function selectedRaid(raids)
  for _, raid in ipairs(raids or Raids.List()) do
    if raid.id == selected then return raid end
  end
end

local function pick(raid)
  local p = picks[raid.id]
  if not p then
    local mine, c = Raids.Mine(raid), Raids.DefaultCharacter(raid)
    local role = (mine and mine.role) or (c and c.role)
    p = { character = c and c.id, role = isOneOf(role, ROLES) and role or "dps" }
    picks[raid.id] = p
  end
  return p
end

local function rosterText(raid)
  local counts, lines = Raids.Counts(raid), {}
  local roster = Raids.Roster(raid)
  table.sort(roster, function(a, b) return a.name:lower() < b.name:lower() end)
  for _, role in ipairs(ROLES) do
    local names = {}
    for _, s in ipairs(roster) do
      if s.status == "accepted" and s.role == role then
        if #names < NAMES_SHOWN then names[#names + 1] = classColor(s.class) .. plain(s.name) .. "|r" end
      end
    end
    if counts[role] > 0 then
      local more = counts[role] > #names and string.format(" +%d", counts[role] - #names) or ""
      lines[#lines + 1] = string.format("%s %s (%d): %s%s", ns.Icon(ROLE_ICON[role], 16), ROLE_PLURAL[role], counts[role],
        table.concat(names, ", "), more)
    end
  end
  if #lines == 0 then return "|cff909090No one is coming yet.|r" end
  return table.concat(lines, "\n")
end

function Raids.Waiting()
  local n = #GargoyleDB.outbox
  if n == 1 then return "1 signup" end
  if n > 1 then return n .. " signups" end
end

-- fromMenu: a dropdown changed, and it updates its own text.
function Raids:Refresh(fromMenu)
  if not ui.list then return end
  if ns.UpdateStatus then ns.UpdateStatus() end
  local raids = Raids.List()
  offset = math.max(0, math.min(offset, #raids - ROWS))
  if not selectedRaid(raids) then selected = raids[1] and raids[1].id end
  if ui.list:IsVisible() then ns.RaidAlerts.Seen(raids) end
  local manyGuilds = #ns.sync.guilds > 1
  for i, row in ipairs(ui.rows) do
    local raid = raids[i + offset]
    row.raid = raid
    row:SetShown(raid ~= nil)
    if raid then
      local mine, counts = Raids.Mine(raid), Raids.Counts(raid)
      row.when:SetText(when(raid.start) .. (manyGuilds and ("  ·  " .. plain(raid.guild.name)) or ""))
      row.title:SetText((ns.RaidAlerts.IsNew(raid) and "|cff19ff19New|r  " or "") .. plain(raid.title))
      row.status:SetText(mine and statusText(mine.status) or "|cff909090Not signed up|r")
      row.count:SetText(string.format("%d%s coming", counts.accepted, raid.size and ("/" .. raid.size) or ""))
      row.selectedBg:SetShown(raid.id == selected)
    end
  end
  ui.none:SetShown(#raids == 0)
  ui.none:SetText(ns.sync.loaded and "No upcoming raids."
    or "No raid data yet. The Gargoyle app brings it in (see the addon's install notes).")

  local raid = selectedRaid(raids)
  ui.detail:SetShown(raid ~= nil)
  if not raid then return end
  local counts = Raids.Counts(raid)
  ui.title:SetText(plain(raid.title))
  ui.when:SetText(string.format("%s  ·  %s%s", when(raid.start), plain(raid.guild.name),
    raid.size and string.format("  ·  %d players", raid.size) or ""))
  ui.roles:SetText(string.format("%s %d      %s %d      %s %d", ns.Icon(ROLE_ICON.tank, 16), counts.tank,
    ns.Icon(ROLE_ICON.healer, 16), counts.healer, ns.Icon(ROLE_ICON.dps, 16), counts.dps))
  ui.totals:SetText(string.format("%s%d coming|r%s · %d tentative · %d can't come", STATUS_COLOR.accepted, counts.accepted,
    raid.size and ("/" .. raid.size) or "", counts.tentative, counts.declined))
  ui.notes:SetText(raid.notes ~= "" and plain(raid.notes) or "|cff909090No notes.|r")
  ui.roster:SetText(rosterText(raid))

  local mine, characters, p = Raids.Mine(raid), Raids.Characters(raid), pick(raid)
  local character = Raids.Character(p.character)
  if mine then
    local c = Raids.Character(mine.character)
    ui.mine:SetText(string.format("%s as %s%s%s", statusText(mine.status), ROLE_LABEL[mine.role] or plain(mine.role),
      c and (" on " .. plain(c.name)) or "", mine.pending and "  |cffb0b0b0(waiting to sync)|r" or ""))
  else
    ui.mine:SetText("|cff909090Not signed up yet.|r")
  end
  if not fromMenu then
    ui.character:GenerateMenu()
    ui.role:GenerateMenu()
  end
  ui.character:SetEnabled(#characters > 1)
  ui.role:SetEnabled(character ~= nil)
  if ui.noteFor ~= raid.id then -- (a note being typed stays while the dropdowns change)
    ui.noteFor = raid.id
    ui.note:SetText(mine and mine.note or "")
  end
  for _, status in ipairs(STATUSES) do
    local b = ui.statusButtons[status]
    b:SetEnabled(character ~= nil)
    if mine and mine.status == status then b:LockHighlight() else b:UnlockHighlight() end
  end
  ui.hint:SetText(#characters == 0 and "Add one of your characters to this guild's roster on the website to sign up here." or "")
end

-- Opens the window on a raid (the reminder's button).
function Raids.Show(raidId)
  for i, raid in ipairs(Raids.List()) do
    if raid.id == raidId then
      selected = raidId
      offset = math.max(i - ROWS, math.min(offset, i - 1)) -- (scrolled so it's in the list)
    end
  end
  ns.OpenWindow("raids")
end

local function signUp(status)
  local raid = selectedRaid()
  if not raid then return end
  local p = pick(raid)
  local problem = Raids.SignUp(raid, status, p.character, p.role, ui.note:GetText())
  ui.note:ClearFocus()
  if problem then
    ns.say(problem)
  elseif not Raids.toldAboutSync then
    Raids.toldAboutSync = true
    ns.say("signup saved. With the Gargoyle app running, click Reload UI (or log out) to send it to the website.")
  end
  Raids:Refresh()
end

function Raids:CreatePanel(panel)
  -- Left: the raids, soonest first.
  ui.list = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  ui.list:SetPoint("TOPLEFT")
  ui.list:SetPoint("BOTTOMLEFT")
  ui.list:SetWidth(272)
  ui.list:EnableMouseWheel(true)
  ui.list:SetScript("OnMouseWheel", function(_, delta)
    offset = offset - delta
    Raids:Refresh()
  end)
  local heading = ui.list:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  heading:SetPoint("TOPLEFT", 10, -8)
  heading:SetText("Upcoming raids")
  ui.none = ui.list:CreateFontString(nil, "ARTWORK", "GameFontDisable")
  ui.none:SetPoint("TOPLEFT", 10, -32)
  ui.none:SetWidth(250)
  ui.none:SetJustifyH("LEFT")

  ui.rows = {}
  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, ui.list)
    row:SetSize(264, ROW_HEIGHT - 2)
    row:SetPoint("TOPLEFT", 4, -26 - (i - 1) * ROW_HEIGHT)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.selectedBg = row:CreateTexture(nil, "BACKGROUND")
    row.selectedBg:SetAllPoints()
    row.selectedBg:SetColorTexture(1, 0.82, 0, 0.16)
    row.status = row:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    row.status:SetPoint("TOPRIGHT", -8, -5)
    row.when = row:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
    row.when:SetPoint("TOPLEFT", 8, -5)
    row.when:SetPoint("RIGHT", row.status, "LEFT", -6, 0)
    row.when:SetJustifyH("LEFT")
    row.when:SetWordWrap(false)
    row.count = row:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
    row.count:SetPoint("BOTTOMRIGHT", -8, 6)
    row.title = row:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    row.title:SetPoint("BOTTOMLEFT", 8, 5)
    row.title:SetPoint("RIGHT", row.count, "LEFT", -6, 0)
    row.title:SetJustifyH("LEFT")
    row.title:SetWordWrap(false)
    row:SetScript("OnClick", function(self)
      selected = self.raid and self.raid.id
      Raids:Refresh()
    end)
    ui.rows[i] = row
  end

  -- Right: the raid picked, who's coming, and your signup.
  local inset = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  inset:SetPoint("TOPLEFT", ui.list, "TOPRIGHT", 6, 0)
  inset:SetPoint("BOTTOMRIGHT")
  local d = CreateFrame("Frame", nil, inset)
  d:SetPoint("TOPLEFT", 14, -12)
  d:SetPoint("BOTTOMRIGHT", -14, 10)
  ui.detail = d
  local function line(font, anchor, gap)
    local fs = d:CreateFontString(nil, "ARTWORK", font)
    if anchor then fs:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, -gap) else fs:SetPoint("TOPLEFT") end
    fs:SetPoint("RIGHT")
    fs:SetJustifyH("LEFT")
    return fs
  end
  ui.title = line("GameFontNormalLarge")
  ui.when = line("GameFontHighlightSmall", ui.title, 4)
  ui.roles = line("GameFontHighlight", ui.when, 10)
  ui.totals = d:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  ui.totals:SetPoint("RIGHT")
  ui.totals:SetPoint("TOP", ui.roles, "TOP", 0, -2)
  ui.totals:SetJustifyH("RIGHT")
  ui.notes = line("GameFontHighlightSmall", ui.roles, 10)
  ui.notes:SetHeight(36)
  ui.notes:SetJustifyV("TOP")
  ui.notes:SetMaxLines(3)
  ui.roster = line("GameFontHighlightSmall", ui.notes, 8)
  ui.roster:SetHeight(74)
  ui.roster:SetJustifyV("TOP")

  local divider = d:CreateTexture(nil, "ARTWORK")
  divider:SetHeight(1)
  divider:SetPoint("TOPLEFT", ui.roster, "BOTTOMLEFT", 0, -6)
  divider:SetPoint("RIGHT")
  divider:SetColorTexture(1, 0.82, 0, 0.3)
  local yours = d:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  yours:SetPoint("TOPLEFT", divider, "BOTTOMLEFT", 0, -10)
  yours:SetText("Your signup")
  ui.mine = d:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  ui.mine:SetPoint("LEFT", yours, "RIGHT", 12, 0)
  ui.mine:SetPoint("RIGHT")
  ui.mine:SetJustifyH("LEFT")

  local characterLabel = d:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  characterLabel:SetPoint("TOPLEFT", yours, "BOTTOMLEFT", 0, -12)
  characterLabel:SetText("Character")
  ui.character = CreateFrame("DropdownButton", nil, d, "WowStyle1DropdownTemplate")
  ui.character:SetWidth(200)
  ui.character:SetPoint("TOPLEFT", characterLabel, "BOTTOMLEFT", 0, -6)
  ui.character:SetDefaultText("No character")
  ui.character:SetupMenu(function(_, root)
    local raid = selectedRaid()
    if not raid then return end
    for _, c in ipairs(Raids.Characters(raid)) do
      root:CreateRadio(classColor(c.class) .. plain(c.name) .. "|r",
        function(id) return pick(raid).character == id end,
        function(id) pick(raid).character = id; Raids:Refresh(true) end, c.id)
    end
  end)

  local roleLabel = d:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  roleLabel:SetPoint("TOPLEFT", characterLabel, "TOPLEFT", 216, 0)
  roleLabel:SetText("Role")
  ui.role = CreateFrame("DropdownButton", nil, d, "WowStyle1DropdownTemplate")
  ui.role:SetWidth(150)
  ui.role:SetPoint("TOPLEFT", roleLabel, "BOTTOMLEFT", 0, -6)
  ui.role:SetDefaultText("Role")
  ui.role:SetupMenu(function(_, root)
    local raid = selectedRaid()
    if not raid then return end
    for _, role in ipairs(ROLES) do
      root:CreateRadio(ns.Icon(ROLE_ICON[role], 16) .. " " .. ROLE_LABEL[role],
        function(r) return pick(raid).role == r end,
        function(r) pick(raid).role = r; Raids:Refresh(true) end, role)
    end
  end)

  local noteLabel = d:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  noteLabel:SetPoint("TOPLEFT", ui.character, "BOTTOMLEFT", 0, -16)
  noteLabel:SetText("Note")
  ui.note = CreateFrame("EditBox", nil, d, "InputBoxTemplate")
  ui.note:SetSize(320, 20)
  ui.note:SetPoint("LEFT", noteLabel, "RIGHT", 14, 0)
  ui.note:SetAutoFocus(false)
  ui.note:SetMaxLetters(200)
  ui.note:SetScript("OnEscapePressed", ui.note.ClearFocus)
  ui.note:SetScript("OnEnterPressed", ui.note.ClearFocus)

  ui.statusButtons = {}
  local previous
  for _, status in ipairs(STATUSES) do
    local b = CreateFrame("Button", nil, d, "UIPanelButtonTemplate")
    b:SetSize(112, 24)
    b:SetText(STATUS_LABEL[status])
    if previous then b:SetPoint("LEFT", previous, "RIGHT", 8, 0) else b:SetPoint("TOPLEFT", noteLabel, "BOTTOMLEFT", 0, -16) end
    b:SetScript("OnClick", function() signUp(status) end)
    ui.statusButtons[status] = b
    previous = b
  end
  ui.hint = d:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  ui.hint:SetPoint("TOPLEFT", ui.statusButtons.accepted, "BOTTOMLEFT", 0, -8)
  ui.hint:SetPoint("RIGHT")
  ui.hint:SetJustifyH("LEFT")
end
