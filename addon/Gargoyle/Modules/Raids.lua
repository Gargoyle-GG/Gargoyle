-- Raid signups: your guilds' upcoming raids from the website, signing up in game, and making
-- new raids in game (for officers).
--
-- The raids come from the Gargoyle app (ns.sync, as fresh as your last login or reload).
-- A signup made here goes into GargoyleDB.outbox and a new raid into GargoyleDB.newRaids;
-- the game saves those on reload or logout, and the app sends them to the website, which
-- applies the same rules as there (your character, on that guild's roster, before the raid
-- starts; only officers make raids). Once the website has one, the app lists it in
-- GargoyleSync.done and it leaves the addon's lists.
local _, ns = ...

local Raids = {
  title = "Raid signups",
  description = "Your guilds' upcoming raids (here and on the game's calendar), signing up, and new raids for officers.",
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
-- Why it turned a new raid down.
local MADE_REASONS = {
  past = "its start time had passed by the time it reached the website",
  full = "the guild has as many upcoming raids as it can have",
  kept_full = "the guild keeps as many raids as it can (an officer can delete old ones on the website)",
  invalid = "you're no longer an officer of that guild",
  not_found = "you're no longer in that guild",
}
local KEEP_DAYS = 30 -- unsent signups older than this are dropped
local NAMES_SHOWN = 14 -- per role in the roster
local MAKE_DAYS = 60 -- how far ahead the New raid form's days go
local MAX_MADE = 20 -- new raids waiting to sync at once
local SIZES = { 10, 20, 25, 40 }
local MINUTES = { 0, 15, 30, 45 }

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

local made = {} -- id -> true: new raids made since the last reload (so never sent yet)

-- ---- Data ----

-- Soonest first (the website's raids before ones made here, at the same time).
local function sooner(a, b)
  if a.start ~= b.start then return a.start < b.start end
  if (a.pending or false) ~= (b.pending or false) then return not a.pending end
  return a.id < b.id
end

-- Every upcoming raid in your guilds, from the website.
function Raids.List()
  local raids, now = {}, time()
  for _, guild in ipairs(ns.sync.guilds) do
    for _, raid in ipairs(guild.raids) do
      if raid.start > now then raids[#raids + 1] = raid end
    end
  end
  table.sort(raids, sooner)
  return raids
end

local function guildById(id)
  for _, guild in ipairs(ns.sync.guilds) do
    if guild.id == id then return guild end
  end
end

-- The guilds you can make raids in (you're an officer there).
function Raids.OfficerGuilds()
  local found = {}
  for _, guild in ipairs(ns.sync.guilds) do
    if guild.officer then found[#found + 1] = guild end
  end
  return found
end

-- New raids made here that the website doesn't have yet, shaped like its raids (pending, with
-- a text id).
function Raids.Made()
  local found, now = {}, time()
  for _, r in ipairs(GargoyleDB.newRaids) do
    if r.start > now then
      found[#found + 1] = { id = r.id, title = r.title, start = r.start, size = r.size, notes = r.notes or "",
                            guild = guildById(r.guild) or { id = r.guild, name = "?" }, signups = {}, pending = true }
    end
  end
  return found
end

-- What the list and the calendar show: the website's raids and the new ones made here.
function Raids.Shown()
  local raids = Raids.List()
  for _, raid in ipairs(Raids.Made()) do raids[#raids + 1] = raid end
  table.sort(raids, sooner)
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
  if raid.pending then return "That raid isn't on the website yet. Sign up once it's there." end
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

-- Record a new raid to send, in a guild you're an officer of. Returns nil and the raid's id
-- (a text one until the website has it), or why it can't be made.
function Raids.Make(guildId, title, start, size, notes)
  local guild = guildById(guildId)
  if not (guild and guild.officer) then return "Pick a guild you're an officer of." end
  title = ns.Cut(strtrim(title or ""), 80)
  if title == "" then return "Give the raid a name." end
  if type(start) ~= "number" or start <= time() then return "Pick a time that hasn't passed yet." end
  if start > time() + 366 * 86400 then return "Pick a day within a year." end
  if size ~= nil and not isOneOf(size, SIZES) then return "Pick a size." end
  if #GargoyleDB.newRaids >= MAX_MADE then
    return string.format("That's %d new raids waiting to sync. Send them first (Reload UI with the Gargoyle app running).", MAX_MADE)
  end
  local id = string.format("r%x-%04x", time(), math.random(0, 0xffff))
  GargoyleDB.newRaids[#GargoyleDB.newRaids + 1] = {
    id = id, guild = guild.id, title = title, start = start, size = size,
    notes = ns.Cut(strtrim(notes or ""), 1000), at = time(),
  }
  made[id] = true
  return nil, id
end

-- Take back a new raid made since the last reload (before then the app can't have sent it).
function Raids.Unmake(id)
  if not made[id] then return end
  for i = #GargoyleDB.newRaids, 1, -1 do
    if GargoyleDB.newRaids[i].id == id then table.remove(GargoyleDB.newRaids, i) end
  end
  made[id] = nil
end

function Raids.CanUnmake(id)
  return made[id] == true
end

local function updateCalendar()
  if ns.Calendar then ns.Calendar.Update() end
end

-- A raid you made here, now on the website: you've seen it (no "new raid" alert for it).
local function seenOnWebsite(r)
  local guild = guildById(r.guild)
  for _, raid in ipairs(guild and guild.raids or {}) do
    if raid.title == r.title and raid.start == r.start then GargoyleDB.alerts.seen[raid.id] = raid.start end
  end
end

local function validMade(r)
  return type(r) == "table" and type(r.id) == "string" and type(r.guild) == "number" and type(r.title) == "string"
    and type(r.start) == "number" and (r.size == nil or type(r.size) == "number")
    and (r.notes == nil or type(r.notes) == "string")
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
  local waiting = {}
  for _, r in ipairs(GargoyleDB.newRaids) do
    if validMade(r) then
      local result = ns.sync.done[r.id]
      if result == "saved" then
        seenOnWebsite(r)
      elseif result then
        ns.say(string.format("your new raid %s wasn't made: %s.", plain(r.title), MADE_REASONS[result] or plain(result)))
      elseif r.start > now then
        waiting[#waiting + 1] = r
      end
    end
  end
  GargoyleDB.newRaids = waiting
end

-- (The new-raid glow, reminders and calendar marks follow the feature being on or off.)
function Raids:OnEnable()
  ns.RaidAlerts.Update()
  updateCalendar()
end

function Raids:OnDisable()
  ns.RaidAlerts.Update()
  updateCalendar()
end

-- ---- The tab ----

local ROW_HEIGHT, ROWS = 40, 9
-- The game's art: the small role icons it puts in text (its INLINE_TANK_ICON and so on, at
-- 16 pixels), and the ready check's marks.
local ROLE_ICON = { tank = "UI-LFG-RoleIcon-Tank-Micro-GroupFinder", healer = "UI-LFG-RoleIcon-Healer-Micro-GroupFinder",
                    dps = "UI-LFG-RoleIcon-DPS-Micro-GroupFinder" }
local STATUS_ICON = { accepted = "UI-LFG-ReadyMark", tentative = "UI-LFG-PendingMark", declined = "UI-LFG-DeclineMark" }
local WAITING = "|cffb0b0b0Waiting to sync|r"
local ui = {}
local selected, offset = nil, 0
local picks = {} -- raid id -> { character, role } chosen in the dropdowns, not yet signed up
local making = false -- the New raid form is open
local form = {} -- what's picked in it: guild, day (0 = today), hour, minute, size (nil: not set)

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

-- Your signup in a few words, for the list and the calendar.
function Raids.StatusText(raid)
  if raid.pending then return WAITING end
  local mine = Raids.Mine(raid)
  return mine and statusText(mine.status) or "|cff909090Not signed up|r"
end

local function selectedRaid(raids)
  for _, raid in ipairs(raids or Raids.Shown()) do
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

local function count(n, one, many)
  if n == 1 then return "1 " .. one end
  if n > 1 then return n .. " " .. many end
end

function Raids.Waiting()
  local parts = {}
  parts[#parts + 1] = count(#GargoyleDB.newRaids, "new raid", "new raids")
  parts[#parts + 1] = count(#GargoyleDB.outbox, "signup", "signups")
  if #parts > 0 then return table.concat(parts, ", ") end
end

-- A day of the New raid form (0 = today) at a time of day, in your own time.
local function startOf(day, hour, minute)
  local today = date("*t", time())
  return time({ year = today.year, month = today.month, day = today.day + day, hour = hour, min = minute, sec = 0 })
end

local function dayLabel(day)
  if day == 0 then return "Today" end
  if day == 1 then return "Tomorrow" end
  return date("%a %d %b", startOf(day, 12, 0))
end

local function refreshForm(fromMenu)
  if not fromMenu then
    for _, dropdown in ipairs(ui.formMenus) do dropdown:GenerateMenu() end
  end
  ui.formGuild:SetEnabled(#Raids.OfficerGuilds() > 1)
  local guild = guildById(form.guild)
  ui.formWhen:SetText(string.format("%s, your time  ·  %s%s", when(startOf(form.day, form.hour, form.minute)),
    plain(guild and guild.name or ""), form.size and string.format("  ·  %d players", form.size) or ""))
end

-- fromMenu: a dropdown changed, and it updates its own text.
function Raids:Refresh(fromMenu)
  if not ui.list then return end
  if ns.UpdateStatus then ns.UpdateStatus() end
  local raids = Raids.Shown()
  offset = math.max(0, math.min(offset, #raids - ROWS))
  if not selectedRaid(raids) then selected = raids[1] and raids[1].id end
  if ui.list:IsVisible() then ns.RaidAlerts.Seen(Raids.List()) end
  local manyGuilds = #ns.sync.guilds > 1
  for i, row in ipairs(ui.rows) do
    local raid = raids[i + offset]
    row.raid = raid
    row:SetShown(raid ~= nil)
    if raid then
      local counts = Raids.Counts(raid)
      row.when:SetText(when(raid.start) .. (manyGuilds and ("  ·  " .. plain(raid.guild.name)) or ""))
      row.title:SetText(((not raid.pending and ns.RaidAlerts.IsNew(raid)) and "|cff19ff19New|r  " or "") .. plain(raid.title))
      row.status:SetText(Raids.StatusText(raid))
      row.count:SetText(raid.pending and "" or string.format("%d%s coming", counts.accepted, raid.size and ("/" .. raid.size) or ""))
      row.selectedBg:SetShown(raid.id == selected and not making)
    end
  end
  ui.none:SetShown(#raids == 0)
  ui.none:SetText(ns.sync.loaded and "No upcoming raids."
    or "No raid data yet. The Gargoyle app brings it in (see the addon's install notes).")
  ui.newRaid:SetShown(#Raids.OfficerGuilds() > 0)

  ui.form:SetShown(making)
  if making then
    ui.detail:Hide()
    refreshForm(fromMenu)
    return
  end
  local raid = selectedRaid(raids)
  ui.detail:SetShown(raid ~= nil)
  if not raid then return end
  ui.title:SetText(plain(raid.title))
  ui.when:SetText(string.format("%s  ·  %s%s", when(raid.start), plain(raid.guild.name),
    raid.size and string.format("  ·  %d players", raid.size) or ""))
  ui.notes:SetText(raid.notes ~= "" and plain(raid.notes) or "|cff909090No notes.|r")
  ui.signup:SetShown(not raid.pending)
  ui.unmake:SetShown(raid.pending and Raids.CanUnmake(raid.id))
  if raid.pending then
    ui.roles:SetText(WAITING)
    ui.totals:SetText("")
    ui.roster:SetText("Made in game. It goes to the website, your guild's Discord and everyone's Gargoyle the next "
      .. "time you reload or log out with the Gargoyle app running. Signups open once it's there.")
    return
  end
  local counts = Raids.Counts(raid)
  ui.roles:SetText(string.format("%s %d      %s %d      %s %d", ns.Icon(ROLE_ICON.tank, 16), counts.tank,
    ns.Icon(ROLE_ICON.healer, 16), counts.healer, ns.Icon(ROLE_ICON.dps, 16), counts.dps))
  ui.totals:SetText(string.format("%s%d coming|r%s · %d tentative · %d can't come", STATUS_COLOR.accepted, counts.accepted,
    raid.size and ("/" .. raid.size) or "", counts.tentative, counts.declined))
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

-- Opens the window on a raid (the reminder's button, the calendar's marks).
function Raids.Show(raidId)
  making = false
  for i, raid in ipairs(Raids.Shown()) do
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
  updateCalendar()
end

local function openForm()
  if not ns.sync.makesRaids then
    ns.say("making raids in game needs the newest Gargoyle app. Its window offers it when it's out: update, then reload.")
    return
  end
  local guilds = Raids.OfficerGuilds()
  if #guilds == 0 then return end
  local guild = guildById(form.guild)
  if not (guild and guild.officer) then form.guild = guilds[1].id end
  form.hour, form.minute = form.hour or 20, form.minute or 0
  form.day = startOf(0, form.hour, form.minute) > time() and 0 or 1
  ui.formTitle:SetText("")
  ui.formNotes:SetText("")
  ui.formProblem:SetText("")
  making = true
  Raids:Refresh()
  ui.formTitle:SetFocus()
end

local function closeForm()
  making = false
  ui.formTitle:ClearFocus()
  ui.formNotes:ClearFocus()
  Raids:Refresh()
end

local function makeRaid()
  local problem, id = Raids.Make(form.guild, ui.formTitle:GetText(), startOf(form.day, form.hour, form.minute), form.size,
    ui.formNotes:GetText())
  if problem then
    ui.formProblem:SetText(problem)
    return
  end
  selected = id
  closeForm()
  if not Raids.toldAboutMaking then
    Raids.toldAboutMaking = true
    ns.say("new raid saved. With the Gargoyle app running, click Reload UI (or log out) to send it to the website.")
  end
  updateCalendar()
end

-- A dropdown of radio choices: options() gives { label, value } pairs; get() and set(value).
local function dropdown(parent, width, options, get, set, scroll)
  local menu = CreateFrame("DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
  menu:SetWidth(width)
  menu:SetupMenu(function(_, root)
    if scroll and root.SetScrollMode then root:SetScrollMode(scroll) end
    for _, option in ipairs(options()) do
      root:CreateRadio(option[1], function(value) return get() == value end,
        function(value) set(value); Raids:Refresh(true) end, option[2])
    end
  end)
  return menu
end

-- A field's name, below `anchor` (gap pixels down), or beside `beside` (x pixels along).
local function label(parent, text, anchor, gap, beside, x)
  local fs = parent:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  if beside then
    fs:SetPoint("TOPLEFT", beside, "TOPLEFT", x, 0)
  else
    fs:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, -gap)
  end
  fs:SetText(text)
  return fs
end

local function editBox(parent, width, letters)
  local box = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
  box:SetSize(width, 20)
  box:SetAutoFocus(false)
  box:SetMaxLetters(letters)
  box:SetScript("OnEscapePressed", box.ClearFocus)
  box:SetScript("OnEnterPressed", box.ClearFocus)
  return box
end

-- The New raid form, in place of a raid's details.
local function createForm(inset)
  local f = CreateFrame("Frame", nil, inset)
  f:SetPoint("TOPLEFT", 14, -12)
  f:SetPoint("BOTTOMRIGHT", -14, 10)
  f:Hide()
  ui.form = f
  local heading = f:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  heading:SetPoint("TOPLEFT")
  heading:SetText("New raid")

  local guildLabel = label(f, "Guild", heading, 14)
  ui.formGuild = dropdown(f, 200, function()
    local options = {}
    for _, g in ipairs(Raids.OfficerGuilds()) do options[#options + 1] = { plain(g.name), g.id } end
    return options
  end, function() return form.guild end, function(v) form.guild = v end)
  ui.formGuild:SetPoint("TOPLEFT", guildLabel, "BOTTOMLEFT", 0, -6)
  local sizeLabel = label(f, "Size", nil, nil, guildLabel, 216)
  ui.formSize = dropdown(f, 150, function()
    local options = { { "Not set", 0 } }
    for _, n in ipairs(SIZES) do options[#options + 1] = { n .. " players", n } end
    return options
  end, function() return form.size or 0 end, function(v) form.size = v ~= 0 and v or nil end)
  ui.formSize:SetPoint("TOPLEFT", sizeLabel, "BOTTOMLEFT", 0, -6)

  local titleLabel = label(f, "Raid name", ui.formGuild, 14)
  ui.formTitle = editBox(f, 360, 80)
  ui.formTitle:SetPoint("TOPLEFT", titleLabel, "BOTTOMLEFT", 6, -4)

  local dayName = label(f, "Day", titleLabel, 40) -- (below the name box)
  ui.formDay = dropdown(f, 200, function()
    local options = {}
    for day = 0, MAKE_DAYS - 1 do options[#options + 1] = { dayLabel(day), day } end
    return options
  end, function() return form.day end, function(v) form.day = v end, 320)
  ui.formDay:SetPoint("TOPLEFT", dayName, "BOTTOMLEFT", 0, -6)
  local timeLabel = label(f, "Time (your own)", nil, nil, dayName, 216)
  ui.formHour = dropdown(f, 70, function()
    local options = {}
    for hour = 0, 23 do options[#options + 1] = { string.format("%02d", hour), hour } end
    return options
  end, function() return form.hour end, function(v) form.hour = v end, 320)
  ui.formHour:SetPoint("TOPLEFT", timeLabel, "BOTTOMLEFT", 0, -6)
  ui.formMinute = dropdown(f, 70, function()
    local options = {}
    for _, minute in ipairs(MINUTES) do options[#options + 1] = { string.format("%02d", minute), minute } end
    return options
  end, function() return form.minute end, function(v) form.minute = v end)
  ui.formMinute:SetPoint("LEFT", ui.formHour, "RIGHT", 8, 0)

  local notesLabel = label(f, "Notes", ui.formDay, 14)
  ui.formNotes = editBox(f, 400, 1000)
  ui.formNotes:SetPoint("TOPLEFT", notesLabel, "BOTTOMLEFT", 6, -4)
  ui.formMenus = { ui.formGuild, ui.formSize, ui.formDay, ui.formHour, ui.formMinute }

  ui.formWhen = f:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  ui.formWhen:SetPoint("TOPLEFT", ui.formNotes, "BOTTOMLEFT", -6, -14)
  ui.formWhen:SetPoint("RIGHT")
  ui.formWhen:SetJustifyH("LEFT")
  local makeButton = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  makeButton:SetSize(120, 24)
  makeButton:SetPoint("TOPLEFT", ui.formWhen, "BOTTOMLEFT", 0, -12)
  makeButton:SetText("Make raid")
  makeButton:SetScript("OnClick", makeRaid)
  local cancel = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  cancel:SetSize(100, 24)
  cancel:SetPoint("LEFT", makeButton, "RIGHT", 8, 0)
  cancel:SetText("Cancel")
  cancel:SetScript("OnClick", closeForm)
  ui.formProblem = f:CreateFontString(nil, "ARTWORK", "GameFontRedSmall")
  ui.formProblem:SetPoint("TOPLEFT", makeButton, "BOTTOMLEFT", 0, -8)
  ui.formProblem:SetPoint("RIGHT")
  ui.formProblem:SetJustifyH("LEFT")
  local hint = f:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  hint:SetPoint("BOTTOMLEFT")
  hint:SetPoint("RIGHT")
  hint:SetJustifyH("LEFT")
  hint:SetText("It goes to the website, your guild's Discord and everyone's Gargoyle the next time you reload or log "
    .. "out with the Gargoyle app running. Change or delete it on the website.")
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
  ui.newRaid = CreateFrame("Button", nil, ui.list, "UIPanelButtonTemplate")
  ui.newRaid:SetSize(90, 20)
  ui.newRaid:SetPoint("TOPRIGHT", -6, -4)
  ui.newRaid:SetText("New raid")
  ui.newRaid:SetScript("OnClick", openForm)
  ns.Tooltip(ui.newRaid, "New raid", "Make a raid for your guild (you're an officer). It goes to the website and your "
    .. "guild's Discord with the next sync.")
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
      making = false
      Raids:Refresh()
    end)
    ui.rows[i] = row
  end

  -- Right: the raid picked, who's coming, and your signup (or the New raid form).
  local inset = CreateFrame("Frame", nil, panel, "InsetFrameTemplate")
  inset:SetPoint("TOPLEFT", ui.list, "TOPRIGHT", 6, 0)
  inset:SetPoint("BOTTOMRIGHT")
  local d = CreateFrame("Frame", nil, inset)
  d:SetPoint("TOPLEFT", 14, -12)
  d:SetPoint("BOTTOMRIGHT", -14, 10)
  ui.detail = d
  createForm(inset)
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
  -- A new raid made here, not sent yet: take it back.
  ui.unmake = CreateFrame("Button", nil, d, "UIPanelButtonTemplate")
  ui.unmake:SetSize(140, 24)
  ui.unmake:SetPoint("TOPLEFT", ui.roster, "BOTTOMLEFT", 0, -10)
  ui.unmake:SetText("Don't make it")
  ui.unmake:SetScript("OnClick", function()
    Raids.Unmake(selected)
    selected = nil
    Raids:Refresh()
    updateCalendar()
  end)

  -- Your signup (not for a raid that isn't on the website yet).
  local s = CreateFrame("Frame", nil, d)
  s:SetAllPoints()
  ui.signup = s
  local divider = s:CreateTexture(nil, "ARTWORK")
  divider:SetHeight(1)
  divider:SetPoint("TOPLEFT", ui.roster, "BOTTOMLEFT", 0, -6)
  divider:SetPoint("RIGHT")
  divider:SetColorTexture(1, 0.82, 0, 0.3)
  local yours = s:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  yours:SetPoint("TOPLEFT", divider, "BOTTOMLEFT", 0, -10)
  yours:SetText("Your signup")
  ui.mine = s:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  ui.mine:SetPoint("LEFT", yours, "RIGHT", 12, 0)
  ui.mine:SetPoint("RIGHT")
  ui.mine:SetJustifyH("LEFT")

  local characterLabel = s:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  characterLabel:SetPoint("TOPLEFT", yours, "BOTTOMLEFT", 0, -12)
  characterLabel:SetText("Character")
  ui.character = CreateFrame("DropdownButton", nil, s, "WowStyle1DropdownTemplate")
  ui.character:SetWidth(200)
  ui.character:SetPoint("TOPLEFT", characterLabel, "BOTTOMLEFT", 0, -6)
  ui.character:SetDefaultText("No character")
  ui.character:SetupMenu(function(_, root)
    local raid = selectedRaid()
    if not raid or raid.pending then return end
    for _, c in ipairs(Raids.Characters(raid)) do
      root:CreateRadio(classColor(c.class) .. plain(c.name) .. "|r",
        function(id) return pick(raid).character == id end,
        function(id) pick(raid).character = id; Raids:Refresh(true) end, c.id)
    end
  end)

  local roleLabel = s:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  roleLabel:SetPoint("TOPLEFT", characterLabel, "TOPLEFT", 216, 0)
  roleLabel:SetText("Role")
  ui.role = CreateFrame("DropdownButton", nil, s, "WowStyle1DropdownTemplate")
  ui.role:SetWidth(150)
  ui.role:SetPoint("TOPLEFT", roleLabel, "BOTTOMLEFT", 0, -6)
  ui.role:SetDefaultText("Role")
  ui.role:SetupMenu(function(_, root)
    local raid = selectedRaid()
    if not raid or raid.pending then return end
    for _, role in ipairs(ROLES) do
      root:CreateRadio(ns.Icon(ROLE_ICON[role], 16) .. " " .. ROLE_LABEL[role],
        function(r) return pick(raid).role == r end,
        function(r) pick(raid).role = r; Raids:Refresh(true) end, role)
    end
  end)

  local noteLabel = s:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  noteLabel:SetPoint("TOPLEFT", ui.character, "BOTTOMLEFT", 0, -16)
  noteLabel:SetText("Note")
  ui.note = editBox(s, 320, 200)
  ui.note:SetPoint("LEFT", noteLabel, "RIGHT", 14, 0)

  ui.statusButtons = {}
  local previous
  for _, status in ipairs(STATUSES) do
    local b = CreateFrame("Button", nil, s, "UIPanelButtonTemplate")
    b:SetSize(112, 24)
    b:SetText(STATUS_LABEL[status])
    if previous then b:SetPoint("LEFT", previous, "RIGHT", 8, 0) else b:SetPoint("TOPLEFT", noteLabel, "BOTTOMLEFT", 0, -16) end
    b:SetScript("OnClick", function() signUp(status) end)
    ui.statusButtons[status] = b
    previous = b
  end
  ui.hint = s:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  ui.hint:SetPoint("TOPLEFT", ui.statusButtons.accepted, "BOTTOMLEFT", 0, -8)
  ui.hint:SetPoint("RIGHT")
  ui.hint:SetJustifyH("LEFT")
end
