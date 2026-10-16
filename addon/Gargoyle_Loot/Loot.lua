-- Gargoyle Loot: every item in WoW Forever now and where it comes from, in the Gargoyle window, as
-- on the website's Loot pages. An addon of its own that needs Gargoyle (the core), which it uses
-- through the Gargoyle table.
--
-- On the left, where items come from: everything, your wishlist, dungeons, raids, merchants and
-- reputation, professions, and item sets. Each group shows all its items, and opens a list of
-- its places (or professions, factions, sets) to pick just one. Above the list, a search within
-- what's picked, and filters: slot, type, usable by the character you play, up to its level,
-- and upgrades only. Each item
-- shows where it comes from, how much better it is for your Gargoyle character (the core's
-- Upgrades.lua) and a wishlist star (the wishlist is on the website too: the Gargoyle app keeps
-- them in step). Point at an item for the game's own tooltip (hold Shift to compare it with
-- what you wear); Ctrl-click tries it on in the game's dressing room, Shift-click links it in
-- your chat box, as in your bags. An item set can be tried on whole.
--
-- Its data (Data/Loot.lua) is ids, names, levels and where items come from; icons, tooltips and
-- the items' own names come from the game. It only shows things: the dressing room and the chat
-- link are the game's own, and only when you click.
local _, ns = ...
local G = Gargoyle
local Upgrades, Wishlist, Items = G.Upgrades, G.Wishlist, G.Items

local Loot = {
  title = "Loot",
  description = "Every item in WoW Forever now and where it comes from: search them all, see which are upgrades "
    .. "for your character, try them on, and keep a wishlist (on the website too).",
}
G.RegisterModule("loot", Loot)
ns.Loot, G.Loot = Loot, Loot

local ITEMS, PLACES = ns.LOOT_ITEMS or {}, ns.LOOT_PLACES or {}
local DUNGEONS, RAIDS = {}, {}
for _, p in ipairs(PLACES) do table.insert(p.raid and RAIDS or DUNGEONS, p) end
-- The groups on the left (title: the group; one: what a single one of its list is called).
local CATEGORIES = {
  { key = "all", title = "Everything" },
  { key = "wish", title = "Wishlist" },
  { key = "dungeon", title = "Dungeons", list = DUNGEONS },
  { key = "raid", title = "Raids", list = RAIDS },
  { key = "vendor", title = "Merchants and reputation", list = ns.LOOT_VENDORS or {} },
  { key = "craft", title = "Professions", list = ns.LOOT_CRAFTING or {} },
  { key = "set", title = "Item sets", list = ns.LOOT_SETS or {} },
}
local LISTS, TITLES = {}, {}
for _, c in ipairs(CATEGORIES) do LISTS[c.key], TITLES[c.key] = c.list, c.title end
local PLACE_KINDS = { dungeon = true, raid = true }
local SLOTS = {
  { "", "Any slot" }, { "head", "Head" }, { "neck", "Neck" }, { "shoulder", "Shoulder" }, { "back", "Back" },
  { "chest", "Chest" }, { "wrist", "Wrist" }, { "hands", "Hands" }, { "waist", "Waist" }, { "legs", "Legs" },
  { "feet", "Feet" }, { "finger", "Finger" }, { "trinket", "Trinket" }, { "weapon", "Weapon" },
  { "off_hand", "Off hand or shield" }, { "ranged", "Ranged" },
}
local SLOT_NAMES = { one_hand = "One-hand", two_hand = "Two-hand", main_hand = "Main hand", off_hand = "Off hand",
                     shirt = "Shirt", tabard = "Tabard" }
for _, s in ipairs(SLOTS) do SLOT_NAMES[s[1]] = SLOT_NAMES[s[1]] or s[2] end
local WEAPON_SLOTS = { one_hand = true, main_hand = true, two_hand = true }
local NAV_ROWS, NAV_HEIGHT = 19, 21
local ROWS, ROW_HEIGHT = 11, 31
local GREEN, GREY, GOLD = "|cff3fd35c", "|cffb0b0b0", "|cffffd100"

local byId, types = {}, {}
-- (the core's stars, here and on the Dungeons tab: only on items in the game now)
G.Wishable = function(id) return byId[id] ~= nil end
for _, it in ipairs(ITEMS) do
  byId[it.id] = it
  if it.type then types[it.type] = true end
end
local TYPES = { "" }
for t in pairs(types) do TYPES[#TYPES + 1] = t end
table.sort(TYPES)

local ui = {}
local navOffset, offset = 0, 0
local entries, listTitle, listKey = {}, "", nil -- the list on the right: { header = text } or { item = it }

local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

local function clamp(value, most)
  return math.max(0, math.min(value, most))
end

local function db()
  return GargoyleDB.loot
end

local function titleCase(text)
  return (text:gsub("^%l", string.upper))
end

-- ---- Where an item comes from ----

local function chanceText(pct)
  if pct >= 10 then return string.format("%d%%", math.floor(pct + 0.5)) end
  return (string.format("%.1f", pct):gsub("%.0$", "")) .. "%"
end

local function sourceText(s)
  local kind = s[1]
  if kind == "drop" then
    local p = PLACES[s[2]]
    return (p and p.name or "?") .. " · " .. s[3] .. (s[4] and (" · " .. chanceText(s[4])) or "")
  elseif kind == "quest" then
    local p = PLACES[s[3]]
    return "Quest: " .. s[2] .. (p and (" (" .. p.name .. ")") or "")
  elseif kind == "craft" then
    return string.format("%s (skill %d)", s[2], s[3] or 0)
  elseif kind == "vendor" then
    return "Sold by " .. s[2] .. ", " .. s[3] .. ((s[5] and s[5] ~= "") and (" · " .. s[5] .. ", " .. s[6]) or "")
  elseif kind == "rep" then
    return s[2] .. ", " .. s[3]
  end
  return "?"
end

local function fromText(it)
  local first = it.from and it.from[1]
  if not first then return "Where it comes from isn't known yet" end
  return sourceText(first) .. (#it.from > 1 and string.format(" (and %d more)", #it.from - 1) or "")
end

-- What the tooltip adds: every place it comes from, and a recipe's reagents.
local function tooltipLines(it)
  local lines = {}
  for i, s in ipairs(it.from or {}) do
    if i > 5 then
      lines[#lines + 1] = string.format("and %d more", #it.from - 5)
      break
    end
    lines[#lines + 1] = "From: " .. sourceText(s)
    if s[1] == "craft" then
      if s[4] and s[4] ~= "" then lines[#lines + 1] = "  Learned: " .. s[4] end
      local reagents = {}
      for _, r in ipairs(s[5] or {}) do
        local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
        local name = getInfo and getInfo(r[1])
        reagents[#reagents + 1] = string.format("%d %s", r[2], name or ("item " .. r[1]))
      end
      if #reagents > 0 then lines[#lines + 1] = "  Needs: " .. table.concat(reagents, ", ") end
    end
  end
  if #lines == 0 then lines[1] = "Where it comes from isn't known yet." end
  return lines
end

-- ---- Items, from the game ----

local loading, soon = {}, false

local function refreshSoon()
  if soon then return end
  soon = true
  local function go()
    soon = false
    if ui.panel and ui.panel:IsVisible() then Loot:Refresh(true) end
  end
  if C_Timer and C_Timer.After then C_Timer.After(0.2, go) else go() end
end

-- The game's name, quality and icon for an item (it's asked for, and the tab redrawn, when the
-- game hasn't loaded it yet): until then, our own name.
local function itemInfo(it)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  local name, _, quality, _, _, _, _, _, _, icon
  if getInfo then name, _, quality, _, _, _, _, _, _, icon = getInfo(it.id) end
  if not name and not loading[it.id] and Item and Item.CreateFromItemID then
    loading[it.id] = true
    Item:CreateFromItemID(it.id):ContinueOnItemLoad(function()
      loading[it.id] = nil
      refreshSoon()
    end)
  end
  return name or it.name, quality or it.q, icon
end

local function qualityColor(quality)
  if C_Item and C_Item.GetItemQualityColor and quality then
    local _, _, _, hex = C_Item.GetItemQualityColor(quality)
    if type(hex) == "string" then return "|c" .. hex end
  end
  return ""
end

-- ---- The filters ----

local function player()
  local _, classFile = UnitClass("player")
  local side = UnitFactionGroup and UnitFactionGroup("player")
  return type(classFile) == "string" and classFile:lower() or nil, side, UnitLevel and UnitLevel("player") or 60
end

local function usable(it, class, side)
  if it.classes and class then
    local ok = false
    for _, c in ipairs(it.classes) do ok = ok or c == class end
    if not ok then return false end
  end
  return not (it.side and side and it.side ~= side)
end

local hay -- (item id -> its words, lower case: worked out the first time you search)

local function words(text)
  local out = {}
  for w in text:lower():gmatch("%S+") do out[#out + 1] = w end
  return out
end

local function haystack(it)
  hay = hay or {}
  if not hay[it.id] then
    local parts = { it.name, SLOT_NAMES[it.slot] or it.slot, it.type or "" }
    for _, s in ipairs(it.from or {}) do parts[#parts + 1] = sourceText(s) end
    hay[it.id] = table.concat(parts, " "):lower()
  end
  return hay[it.id]
end

local function passes(it, f)
  for _, w in ipairs(f.words) do
    if not haystack(it):find(w, 1, true) then return false end
  end
  if f.slot == "weapon" then
    if not WEAPON_SLOTS[it.slot] then return false end
  elseif f.slot ~= "" and it.slot ~= f.slot then
    return false
  end
  if f.type ~= "" and it.type ~= f.type then return false end
  if f.usable and not usable(it, f.class, f.side) then return false end
  if f.myLevel and (it.level or 0) > f.level then return false end
  if f.ups and not Upgrades.Gain(it.id, f.character) then return false end
  return true
end

-- ---- The list on the right ----

local function whereFirst(it)
  local s = it.from and it.from[1]
  if not s then return "Where it comes from isn't known yet" end
  if s[1] == "drop" or (s[1] == "quest" and PLACES[s[3]]) then
    local p = PLACES[s[1] == "drop" and s[2] or s[3]]
    return p and p.name or "?"
  end
  if s[1] == "craft" then return s[2] end
  if s[1] == "vendor" then return (s[5] ~= "" and s[5]) or s[3] end
  return s[2]
end

-- A place's items, each once (an item more than one boss drops is under the first).
local function placeItems(p, add, header)
  local seen = {}
  for _, b in ipairs(p.bosses or {}) do
    local ids = {}
    for _, id in ipairs(b.items) do
      if not seen[id] then
        seen[id] = true
        ids[#ids + 1] = id
      end
    end
    add(ids, header and (p.name .. "  ·  " .. b.name) or b.name)
  end
end

-- The items of what's picked on the left (a whole group, or one of its list), with headers,
-- and the search and filters applied.
local function build(f)
  local out = {}
  local function add(ids, header)
    local first = #out + 1
    if header then out[first] = { header = header } end
    for _, id in ipairs(ids) do
      local it = byId[id]
      if it and passes(it, f) then out[#out + 1] = { item = it } end
    end
    if header and #out == first then out[first] = nil end -- (a header with nothing under it)
  end
  local cat, index = db().cat, db().index
  local searching = #f.words > 0
  if cat == "all" then
    local ids = {}
    for _, it in ipairs(ITEMS) do ids[#ids + 1] = it.id end
    add(ids)
    return out, searching and "Search everything" or "Everything"
  end
  if LISTS[cat] and not index then -- (the whole group)
    for _, g in ipairs(LISTS[cat]) do
      if PLACE_KINDS[cat] then placeItems(g, add, true) else add(g.items, g.name) end
    end
    return out, (searching and "Search: " or "All ") .. TITLES[cat]:lower()
  end
  if cat == "wish" then
    local groups, names = {}, {}
    for id in pairs(Wishlist.Items(f.character)) do
      local it = byId[id]
      local where = it and whereFirst(it) or "Not in the game now"
      if not groups[where] then
        groups[where] = {}
        names[#names + 1] = where
      end
      table.insert(groups[where], id)
    end
    table.sort(names)
    for _, where in ipairs(names) do
      table.sort(groups[where], function(a, b) return (byId[a] and byId[a].name or "") < (byId[b] and byId[b].name or "") end)
      add(groups[where], where)
    end
    return out, "Wishlist"
  end
  local g = LISTS[cat] and LISTS[cat][index]
  if not g then return out, "" end
  if PLACE_KINDS[cat] then
    placeItems(g, add, false)
  elseif cat == "set" then
    local have = 0
    for _, id in ipairs(g.items) do if Upgrades.Worn(id) then have = have + 1 end end
    for _, b in ipairs(g.bonuses or {}) do
      out[#out + 1] = { header = string.format("%s%d pieces: %s|r", have >= b[1] and GREEN or GREY, b[1], plain(b[2])), bonus = true }
    end
    add(g.items, string.format("Pieces (%d of %d in the game now, you wear %d)", #g.items, g.pieces or #g.items, have))
  else
    add(g.items)
  end
  return out, g.name
end

-- ---- Drawing ----

-- The left: each group (its list, under it, when it's open).
local function navEntries()
  local out = {}
  for _, c in ipairs(CATEGORIES) do
    if c.key == "wish" then
      out[#out + 1] = { cat = "wish", label = string.format("Wishlist (%d)", Wishlist.Count()), group = true }
    elseif not c.list then
      out[#out + 1] = { cat = c.key, label = c.title, group = true }
    else
      local open = db().open[c.key]
      out[#out + 1] = { cat = c.key, label = (open and "- " or "+ ") .. c.title, count = #c.list, group = true }
      if open then
        for i, g in ipairs(c.list) do out[#out + 1] = { cat = c.key, index = i, label = g.name, sub = true } end
      end
    end
  end
  return out
end

local function filters()
  local class, side, level = player()
  local s = db()
  return {
    words = words(ui.search and ui.search:GetText() or ""), slot = s.slot or "", type = s.type or "",
    usable = s.usable == true, myLevel = s.myLevel == true, ups = s.ups == true,
    class = class, side = side, level = level or 60, character = Upgrades.Chosen(),
  }
end

local function showRow(row, entry, character)
  row.entry = entry
  local it = entry and entry.item
  row.header:SetShown(entry ~= nil and it == nil)
  row.icon:SetShown(it ~= nil)
  row.name:SetShown(it ~= nil)
  row.from:SetShown(it ~= nil)
  row.gain:SetShown(it ~= nil)
  row.star:SetShown(it ~= nil)
  row.upgrade:Hide()
  row.itemID = it and it.id
  if not entry then return end
  if not it then
    row.header:SetText(entry.bonus and entry.header or (GOLD .. plain(entry.header) .. "|r"))
    return
  end
  local name, quality, icon = itemInfo(it)
  row.icon:SetTexture(icon or 134400) -- (the game's "?" until it's loaded)
  local facts = { SLOT_NAMES[it.slot] or it.slot }
  if it.type then facts[#facts + 1] = titleCase(it.type) end
  if it.level then facts[#facts + 1] = "level " .. it.level end
  row.name:SetText(qualityColor(quality) .. plain(name) .. "|r" .. (it.new and (" " .. GREEN .. "New|r") or ""))
  row.from:SetText(GREY .. plain(table.concat(facts, ", ") .. "  ·  " .. fromText(it)) .. "|r")
  local gain = Upgrades.Gain(it.id, character)
  row.gain:SetText(gain and (GREEN .. Upgrades.GainText(gain) .. "|r") or "")
  row.upgrade:SetShown(gain ~= nil)
  row.star.itemID = it.id
  row.star:Update()
end

local function status(character, list, title)
  local missing = Upgrades.Missing(character)
  local n, ups = 0, 0
  for _, e in ipairs(list) do
    if e.item then
      n = n + 1
      if Upgrades.Gain(e.item.id, character) then ups = ups + 1 end
    end
  end
  local text = string.format("%d item%s", n, n == 1 and "" or "s")
  if n == 0 and title ~= "Wishlist" then
    return text .. ". Items above the beta's level cap, and from raids not released yet, aren't listed."
  end
  if missing then return text .. ". " .. missing end
  text = text .. (ups > 0 and string.format(", %s%d upgrade%s|r for %s", GREEN, ups, ups == 1 and "" or "s", Upgrades.Who(character))
    or (" (none an upgrade for " .. Upgrades.Who(character) .. ")")) .. "."
  if character.upgrades.stale then text = text .. " " .. plain(character.name) .. " has changed since: open it in the planner to update." end
  if title == "Wishlist" and n == 0 then
    text = "Nothing on " .. plain(character.name) .. "'s wishlist yet: click an item's star to add it."
  end
  return text
end

function Loot:Refresh(fromMenu)
  if not ui.panel then return end
  local s = db()
  local character = Upgrades.Chosen()
  -- The left: where items come from.
  local nav = navEntries()
  navOffset = clamp(navOffset, #nav - NAV_ROWS)
  for i, row in ipairs(ui.nav) do
    local e = nav[i + navOffset]
    row:SetShown(e ~= nil)
    if e then
      row.entry = e
      row.label:SetText((e.sub and "   " or "") .. (e.group and GOLD or "") .. plain(e.label) .. (e.group and "|r" or "")
        .. (e.count and (GREY .. " " .. e.count .. "|r") or ""))
      row.selectedBg:SetShown(e.cat == s.cat and e.index == s.index)
    end
  end
  -- The right: its items.
  local f = filters()
  local wishes = 0
  for _ in ipairs(GargoyleDB.wishes) do wishes = wishes + 1 end
  local key = table.concat({ s.cat, tostring(s.index), ui.search:GetText(), f.slot, f.type, tostring(f.usable),
    tostring(f.myLevel), tostring(f.ups), tostring(f.level), tostring(character and character.id), Wishlist.Count(),
    wishes }, "\031")
  if key ~= listKey then -- (else it's the same list: scrolled, or an item's info came in)
    entries, listTitle = build(f)
    listKey = key
  end
  local title = listTitle
  offset = clamp(offset, #entries - ROWS)
  for i, row in ipairs(ui.rows) do showRow(row, entries[i + offset], character) end
  ui.title:SetText(plain(title))
  ui.more:SetText(#entries > ROWS and (GREY .. "Scroll for more|r") or "")
  -- Its button: open the place in the Dungeons tab, or try the set on.
  local g = LISTS[s.cat] and s.index and LISTS[s.cat][s.index]
  ui.openPlace:SetShown(PLACE_KINDS[s.cat] and g ~= nil and G.Journal ~= nil and G.Journal.Open ~= nil)
  ui.tryOn:SetShown(s.cat == "set" and g ~= nil)
  if not fromMenu then ui.who:GenerateMenu() end
  for key, box in pairs(ui.checks) do box:SetChecked(s[key] == true) end
  ui.status:SetText(status(character, entries, title))
end

-- Picks a group (index nil: all of it) or one of its list. A group opens its list; picking it
-- again while it's picked closes it. The search stays: it searches what's picked.
function Loot.Pick(cat, index)
  local s = db()
  if LISTS[cat] and not index then
    if s.cat == cat and not s.index then s.open[cat] = not s.open[cat] or nil else s.open[cat] = true end
  end
  s.cat, s.index = cat, index
  offset = 0
  Loot:Refresh(true)
end

-- ---- Building the tab ----

local function text(parent, font, wrap)
  local fs = parent:CreateFontString(nil, "ARTWORK", font)
  fs:SetJustifyH("LEFT")
  if not wrap then fs:SetWordWrap(false) end
  return fs
end

local function wheel(frame, scroll)
  frame:EnableMouseWheel(true)
  frame:SetScript("OnMouseWheel", function(_, delta)
    scroll(delta)
    Loot:Refresh(true)
  end)
end

local function dropdown(parent, width, options, key, label)
  local menu = CreateFrame("DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
  menu:SetWidth(width)
  menu:SetDefaultText(label)
  menu:SetupMenu(function(_, root)
    for _, o in ipairs(options) do
      root:CreateRadio(o[2], function(value) return (db()[key] or "") == value end, function(value)
        db()[key] = value
        offset = 0
        Loot:Refresh(true)
      end, o[1])
    end
  end)
  return menu
end

local function createNav(panel)
  local nav = CreateFrame("Frame", nil, panel)
  nav:SetPoint("TOPLEFT", 4, -4)
  nav:SetSize(196, NAV_ROWS * NAV_HEIGHT)
  wheel(nav, function(delta) navOffset = navOffset - delta * 3 end)
  ui.nav = {}
  for i = 1, NAV_ROWS do
    local row = CreateFrame("Button", nil, nav)
    row:SetSize(194, NAV_HEIGHT - 1)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * NAV_HEIGHT)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.selectedBg = row:CreateTexture(nil, "BACKGROUND")
    row.selectedBg:SetAllPoints()
    row.selectedBg:SetColorTexture(1, 0.82, 0, 0.16)
    row.label = text(row, "GameFontHighlightSmall")
    row.label:SetPoint("LEFT", 6, 0)
    row.label:SetPoint("RIGHT", -4, 0)
    row:SetScript("OnClick", function(self) Loot.Pick(self.entry.cat, self.entry.index) end)
    ui.nav[i] = row
  end
end

local function createTop(right)
  ui.search = CreateFrame("EditBox", nil, right, "SearchBoxTemplate")
  ui.search:SetSize(210, 20)
  ui.search:SetPoint("TOPLEFT", 6, -2)
  ui.search:SetAutoFocus(false)
  ui.search:SetMaxLetters(60)
  ui.search:HookScript("OnTextChanged", function()
    offset = 0
    Loot:Refresh(true)
  end)
  local slots = dropdown(right, 150, SLOTS, "slot", "Any slot")
  slots:SetPoint("LEFT", ui.search, "RIGHT", 10, 0)
  local typeOptions = {}
  for _, t in ipairs(TYPES) do typeOptions[#typeOptions + 1] = { t, t == "" and "Any type" or titleCase(t) } end
  local kinds = dropdown(right, 150, typeOptions, "type", "Any type")
  kinds:SetPoint("LEFT", slots, "RIGHT", 6, 0)
  ui.checks = {}
  local x = 0
  for _, c in ipairs({ { "usable", "Usable by me", 110 }, { "myLevel", "Up to my level", 118 }, { "ups", "Upgrades only", 112 } }) do
    local box = CreateFrame("CheckButton", nil, right, "UICheckButtonTemplate")
    box:SetSize(22, 22)
    box:SetPoint("TOPLEFT", x, -26)
    local label = text(right, "GameFontHighlightSmall")
    label:SetPoint("LEFT", box, "RIGHT", 2, 0)
    label:SetText(c[2])
    box:SetScript("OnClick", function(self)
      db()[c[1]] = self:GetChecked() and true or nil
      offset = 0
      Loot:Refresh(true)
    end)
    ui.checks[c[1]] = box
    x = x + c[3]
  end
  local who = text(right, "GameFontNormalSmall")
  who:SetPoint("TOPLEFT", x + 4, -31)
  who:SetText("Upgrades for")
  ui.who = Upgrades.Menu(right)
  ui.who:SetWidth(150)
  ui.who:SetPoint("LEFT", who, "RIGHT", 6, 0)
end

local function createList(right)
  ui.title = text(right, "GameFontNormal")
  ui.title:SetPoint("TOPLEFT", 6, -56)
  ui.title:SetPoint("RIGHT", -150, 0)
  ui.more = text(right, "GameFontDisableSmall")
  ui.more:SetPoint("LEFT", ui.title, "RIGHT", 6, 0)
  local function button(label, onClick, tip)
    local b = CreateFrame("Button", nil, right, "UIPanelButtonTemplate")
    b:SetSize(140, 20)
    b:SetPoint("TOPRIGHT", -4, -52)
    b:SetText(label)
    b:SetScript("OnClick", onClick)
    G.Tooltip(b, label, tip)
    return b
  end
  ui.openPlace = button("Open in Dungeons", function()
    local p = LISTS[db().cat][db().index]
    if p then G.Journal.Open(p.id or p.name) end
  end, "Its bosses, their abilities and its quests, on the Dungeons tab.")
  ui.tryOn = button("Try on the set", function()
    local g = LISTS.set[db().index]
    for _, id in ipairs(g and g.items or {}) do Items.Preview(id) end
  end, "Shows every piece on your character in the game's dressing room.")
  local list = CreateFrame("Frame", nil, right)
  list:SetPoint("TOPLEFT", 0, -76)
  list:SetSize(576, ROWS * ROW_HEIGHT)
  wheel(list, function(delta) offset = offset - delta * 3 end)
  ui.rows = {}
  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, list)
    row:SetSize(574, ROW_HEIGHT - 2)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.upgrade = row:CreateTexture(nil, "BACKGROUND")
    row.upgrade:SetAllPoints()
    row.upgrade:SetColorTexture(0.25, 0.83, 0.36, 0.14)
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetSize(24, 24)
    row.icon:SetPoint("LEFT", 4, 0)
    row.star = Items.Star(row, 16)
    row.star:SetPoint("RIGHT", -6, 0)
    row.gain = text(row, "GameFontHighlightSmall")
    row.gain:SetPoint("RIGHT", row.star, "LEFT", -8, 0)
    row.name = text(row, "GameFontHighlightSmall")
    row.name:SetPoint("TOPLEFT", row.icon, "TOPRIGHT", 6, 0)
    row.name:SetPoint("RIGHT", row.gain, "LEFT", -6, 0)
    row.from = text(row, "GameFontHighlightSmall")
    row.from:SetPoint("BOTTOMLEFT", row.icon, "BOTTOMRIGHT", 6, -1)
    row.from:SetPoint("RIGHT", row.gain, "LEFT", -6, 0)
    row.header = text(row, "GameFontNormalSmall")
    row.header:SetPoint("LEFT", 6, 0)
    row.header:SetPoint("RIGHT", -6, 0)
    row:SetScript("OnEnter", function(self)
      if self.itemID then Items.Tooltip(self, self.itemID, tooltipLines(byId[self.itemID])) end
    end)
    row:SetScript("OnLeave", function() GameTooltip:Hide() end)
    row:SetScript("OnClick", function(self)
      if self.itemID then Items.Click(self.itemID) end
    end)
    ui.rows[i] = row
  end
end

function Loot:CreatePanel(panel)
  ui.panel = panel
  createNav(panel)
  local right = CreateFrame("Frame", nil, panel)
  right:SetPoint("TOPLEFT", 204, -4)
  right:SetPoint("BOTTOMRIGHT", -4, 24)
  createTop(right)
  createList(right)
  ui.status = text(panel, "GameFontHighlightSmall", true)
  ui.status:SetPoint("BOTTOMLEFT", 14, 6)
  ui.status:SetPoint("RIGHT", -14, 0)
  ui.status:SetMaxLines(2)
  panel:SetScript("OnShow", function() Loot:Refresh() end)
end

-- ---- In a dungeon: what on your wishlist drops there ----

local here

local function currentPlace()
  if not GetInstanceInfo then return end
  local _, kind, _, _, _, _, _, instanceID = GetInstanceInfo()
  if (kind == "party" or kind == "raid") and type(instanceID) == "number" then
    for _, p in ipairs(PLACES) do
      if p.id == instanceID then return p end
    end
  end
end

function Loot.TellOn()
  return db().tell ~= false
end

function Loot.SetTellOn(on)
  db().tell = on and true or false
end

function Loot.Tell(p)
  local character = Upgrades.Chosen()
  if not (p and character and Loot.TellOn()) then return end
  local wished, found, seen = Wishlist.Items(character), {}, {}
  for _, b in ipairs(p.bosses or {}) do
    for _, id in ipairs(b.items) do
      if wished[id] and not seen[id] then
        seen[id] = true
        local link = Items.Link(id)
        found[#found + 1] = (link or plain(byId[id] and byId[id].name or ("item " .. id))) .. " (" .. plain(b.name) .. ")"
      end
    end
  end
  if #found > 0 then
    G.say(string.format("on %s's wishlist, from %s: %s.", plain(character.name), plain(p.name), table.concat(found, ", ")))
  end
end

local watcher = CreateFrame("Frame")
watcher:SetScript("OnEvent", function()
  local now = currentPlace()
  if now ~= here then
    here = now
    if now then Loot.Tell(now) end
  end
end)

-- More options for Gargoyle's options page (the core lists them).
Loot.options = {
  { "Tell me in chat which wishlist items drop in the dungeon I go into", Loot.TellOn, Loot.SetTellOn },
}

function Loot:OnLogin()
  local s = db()
  s.open = type(s.open) == "table" and s.open or {}
  if type(s.cat) ~= "string" or not TITLES[s.cat] then s.cat, s.index = "all", nil end -- (and 1.0.0 betas' "place")
  if type(s.index) ~= "number" or not (LISTS[s.cat] and LISTS[s.cat][s.index]) then s.index = nil end
  for _, key in ipairs({ "slot", "type" }) do
    if type(s[key]) ~= "string" then s[key] = nil end
  end
  here = currentPlace()
end

function Loot:OnEnable()
  for _, event in ipairs({ "PLAYER_ENTERING_WORLD", "ZONE_CHANGED_NEW_AREA" }) do
    pcall(watcher.RegisterEvent, watcher, event)
  end
end

function Loot:OnDisable()
  watcher:UnregisterAllEvents()
end
