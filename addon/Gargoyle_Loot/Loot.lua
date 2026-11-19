-- Gargoyle Loot: every item in WoW Forever now and where it comes from, in the Gargoyle window, as
-- on the website's Loot pages. An addon of its own that needs Gargoyle (the core), which it uses
-- through the Gargoyle table.
--
-- Along the top, dropdowns pick where items come from, left to right: the group (everything,
-- your wishlist, dungeons, raids, merchants and reputation, professions, item sets); then, for a
-- group with a list, all of it or just one (a dungeon, a faction, a profession, a set: sets by
-- class); then, in one dungeon or raid, all its bosses or one. Below them, a search within
-- what's picked, and filters: slot, type, usable by the character you play, up to its level,
-- and upgrades only. The list of items takes the whole width: each row shows the item, where it
-- comes from, its slot and type, its level, how much better it is for your Gargoyle character
-- (the core's Upgrades.lua) and a wishlist star (the wishlist is on the website too: the
-- Gargoyle app keeps them in step). Point at an item for the game's own tooltip (hold Shift to
-- compare it with what you wear); Ctrl-click tries it on in the game's dressing room,
-- Shift-click links it in your chat box, as in your bags. An item set can be tried on whole.
--
-- Its data (Data/Loot.lua) is ids, names, levels and where items come from; icons, tooltips and
-- the items' own names come from the game. It only shows things: the dressing room and the chat
-- link are the game's own, and only when you click.
local _, ns = ...
local G = Gargoyle
if not G or (G.API or 1) < 2 then -- (an older Gargoyle addon: it hasn't what this needs)
  print("|cffd4a017Gargoyle|r: Gargoyle Loot needs a newer Gargoyle addon. Update it with the Gargoyle app (or turn Gargoyle Loot off).")
  return
end
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
-- The groups, in the first dropdown (list: what the second one offers; all: its first choice).
local CATEGORIES = {
  { key = "all", title = "Everything" },
  { key = "wish", title = "Wishlist" },
  { key = "dungeon", title = "Dungeons", list = DUNGEONS, all = "All dungeons" },
  { key = "raid", title = "Raids", list = RAIDS, all = "All raids" },
  { key = "vendor", title = "Merchants and reputation", list = ns.LOOT_VENDORS or {}, all = "All merchants and reputation" },
  { key = "craft", title = "Professions", list = ns.LOOT_CRAFTING or {}, all = "All professions" },
  { key = "set", title = "Item sets", list = ns.LOOT_SETS or {}, all = "All item sets" },
}
local LISTS, TITLES, ALL = {}, {}, {}
for _, c in ipairs(CATEGORIES) do LISTS[c.key], TITLES[c.key], ALL[c.key] = c.list, c.title, c.all end
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
-- The list: rows of two lines, in columns (x and width in the row) that line up.
local ROWS, ROW_HEIGHT, LIST_WIDTH = 12, 27, 776
local COLUMNS = { name = { 34, 470 }, slot = { 512, 96 }, level = { 616, 48 }, gain = 76 }
local MENU_HEIGHT = 320 -- (a dropdown's longest list before it scrolls, as the Raids tab's)
local GREEN, GREY, GOLD, RED = "|cff3fd35c", "|cffb0b0b0", "|cffffd100", "|cffff5f5f"

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

local function titleCase(text)
  return (text:gsub("^%l", string.upper))
end

-- Item sets by class, for the second dropdown: the classes that can wear all of a set's pieces
-- (a set some classes share is under each of them; one anyone can wear, under "Any class").
local CLASS_ORDER = { "warrior", "paladin", "hunter", "rogue", "priest", "shaman", "mage", "warlock", "druid" }
local SET_GROUPS = {}
do
  local byClass, anyone, order = {}, {}, {}
  for _, c in ipairs(CLASS_ORDER) do byClass[c], order[#order + 1] = {}, c end
  for i, set in ipairs(LISTS.set) do
    local shared -- (class -> true: who can wear every piece that names its classes)
    for _, id in ipairs(set.items or {}) do
      local it = byId[id]
      if it and it.classes then
        local these = {}
        for _, c in ipairs(it.classes) do these[c] = shared == nil or shared[c] or nil end
        shared = these
      end
    end
    local any = true
    for c in pairs(shared or {}) do
      any = false
      if not byClass[c] then byClass[c], order[#order + 1] = {}, c end
    end
    if any then anyone[#anyone + 1] = i end
    for _, c in ipairs(order) do
      if shared and shared[c] then table.insert(byClass[c], i) end
    end
  end
  for _, c in ipairs(order) do
    if #byClass[c] > 0 then
      local name = LOCALIZED_CLASS_NAMES_MALE and LOCALIZED_CLASS_NAMES_MALE[c:upper()] or titleCase(c)
      SET_GROUPS[#SET_GROUPS + 1] = { name = name, sets = byClass[c] }
    end
  end
  if #anyone > 0 then SET_GROUPS[#SET_GROUPS + 1] = { name = "Any class", sets = anyone } end
end

local ui = {}
local offset = 0
local entries, listTitle, listKey, pickKey = {}, "", nil, nil -- the list: { header = text } or { item = it }

local function plain(text)
  return (tostring(text or ""):gsub("|", "||"))
end

local function clamp(value, most)
  return math.max(0, math.min(value, most))
end

local function db()
  return GargoyleDB.loot
end

-- What's picked: the group's list entry (a place, a faction, a set...) and, in a place, the boss.
local function picked()
  local s = db()
  local g = LISTS[s.cat] and s.index and LISTS[s.cat][s.index]
  local b = g and PLACE_KINDS[s.cat] and s.boss and g.bosses and g.bosses[s.boss]
  return g, b
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
  if not name and not loading[it.id] then
    loading[it.id] = Items.Load(it.id, function()
      loading[it.id] = nil
      refreshSoon()
    end) or "unknown" -- (an item the game doesn't know: not asked again)
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

-- ---- The list ----

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

local function unique(ids)
  local seen, out = {}, {}
  for _, id in ipairs(ids or {}) do
    if not seen[id] then
      seen[id] = true
      out[#out + 1] = id
    end
  end
  return out
end

-- The items of what's picked (a whole group, one of its list, or one boss), with headers, and
-- the search and filters applied.
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
  local g, boss = picked()
  if not g then return out, "" end
  if boss then
    add(unique(boss.items))
    return out, g.name .. "  ·  " .. boss.name
  elseif PLACE_KINDS[cat] then
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

local function filters()
  local class, side, level = player()
  local s = db()
  return {
    words = words(ui.search and ui.search:GetText() or ""), slot = s.slot or "", type = s.type or "",
    usable = s.usable == true, myLevel = s.myLevel == true, ups = s.ups == true,
    class = class, side = side, level = level or 60, character = Upgrades.Chosen(),
  }
end

local ITEM_PARTS = { "icon", "name", "from", "slotText", "typeText", "levelText", "gain", "star" }

local function showRow(row, entry, character, level)
  row.entry = entry
  local it = entry and entry.item
  row.header:SetShown(entry ~= nil and it == nil)
  for _, part in ipairs(ITEM_PARTS) do row[part]:SetShown(it ~= nil) end
  row.upgrade:Hide()
  row.itemID = it and it.id
  if not entry then return end
  if not it then
    row.header:SetText(entry.bonus and entry.header or (GOLD .. plain(entry.header) .. "|r"))
    return
  end
  local name, quality, icon = itemInfo(it)
  row.icon:SetTexture(icon or 134400) -- (the game's "?" until it's loaded)
  row.name:SetText(qualityColor(quality) .. plain(name) .. "|r" .. (it.new and (" " .. GREEN .. "New|r") or ""))
  row.from:SetText(GREY .. plain(fromText(it)) .. "|r")
  row.slotText:SetText(plain(SLOT_NAMES[it.slot] or it.slot or ""))
  row.typeText:SetText(it.type and (GREY .. plain(titleCase(it.type)) .. "|r") or "")
  row.levelText:SetText(it.level and ((it.level > level and RED or GREY) .. "Level " .. it.level .. "|r") or "")
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
    return text .. ". Items not seen in play yet, and from raids not released yet, aren't listed."
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

-- The dropdowns along the top: the second shown for a group with a list, the third in one
-- dungeon or raid with more than one boss. Their menus are made again when what's picked
-- changes (not the one being picked from: the game updates that one itself).
local function updatePicks(fromMenu)
  local s = db()
  local g = picked()
  ui.place:SetShown(LISTS[s.cat] ~= nil)
  ui.boss:SetShown(PLACE_KINDS[s.cat] and g ~= nil and #(g.bosses or {}) > 1)
  local key = table.concat({ s.cat, tostring(s.index), tostring(s.boss), Wishlist.Count() }, "\031")
  if key == pickKey and fromMenu then return end
  pickKey = key
  for _, menu in ipairs({ ui.group, ui.place, ui.boss }) do
    if menu ~= fromMenu then menu:GenerateMenu() end
  end
end

-- fromMenu: true when it's for a change made on the tab (a dropdown: the one picked from).
function Loot:Refresh(fromMenu)
  if not ui.panel then return end
  local s = db()
  local character = Upgrades.Chosen()
  updatePicks(fromMenu)
  local f = filters()
  local wishes = 0
  for _ in ipairs(GargoyleDB.wishes) do wishes = wishes + 1 end
  local key = table.concat({ s.cat, tostring(s.index), tostring(s.boss), ui.search:GetText(), f.slot, f.type,
    tostring(f.usable), tostring(f.myLevel), tostring(f.ups), tostring(f.level), tostring(character and character.id),
    Wishlist.Count(), wishes }, "\031")
  if key ~= listKey then -- (else it's the same list: scrolled, or an item's info came in)
    entries, listTitle = build(f)
    listKey = key
  end
  local title = listTitle
  offset = clamp(offset, #entries - ROWS)
  for i, row in ipairs(ui.rows) do showRow(row, entries[i + offset], character, f.level) end
  ui.title:SetText(plain(title))
  ui.more:SetText(#entries > ROWS and (GREY .. "Scroll for more|r") or "")
  -- Its button: open the place in the Dungeons tab, or try the set on.
  local g = picked()
  ui.openPlace:SetShown(PLACE_KINDS[s.cat] and g ~= nil and G.Journal ~= nil and G.Journal.Open ~= nil
    and G.IsEnabled("journal"))  -- (not when Dungeons is turned off)
  ui.tryOn:SetShown(s.cat == "set" and g ~= nil)
  if not fromMenu then ui.who:GenerateMenu() end
  for key, box in pairs(ui.checks) do box:SetChecked(s[key] == true) end
  ui.status:SetText(status(character, entries, title))
end

-- Picks a group (index nil: all of it), one of its list, and in a dungeon or raid one boss (nil:
-- all of them). The search stays: it searches what's picked. fromMenu: the dropdown picked from.
function Loot.Pick(cat, index, boss, fromMenu)
  if not TITLES[cat] then return end
  local s = db()
  local list = LISTS[cat]
  s.cat = cat
  s.index = (list and index and list[index]) and index or nil
  local g = PLACE_KINDS[cat] and s.index and list[s.index]
  s.boss = (g and boss and g.bosses and g.bosses[boss]) and boss or nil
  offset = 0
  Loot:Refresh(fromMenu or true)
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

-- The first dropdown: the groups.
local function groupMenu(menu, root)
  for _, c in ipairs(CATEGORIES) do
    local label = c.key == "wish" and string.format("Wishlist (%d)", Wishlist.Count()) or c.title
    root:CreateRadio(label, function(key) return db().cat == key end, function(key) Loot.Pick(key, nil, nil, menu) end, c.key)
  end
end

-- The second: all of the group, or one of its list (0: all of it).
local function placeMenu(menu, root)
  local cat = db().cat
  local list = LISTS[cat]
  if not list then return end
  local function radio(parent, label, i)
    parent:CreateRadio(label, function(v) return db().cat == cat and (db().index or 0) == v end,
      function(v) Loot.Pick(cat, v ~= 0 and v or nil, nil, menu) end, i)
  end
  root:SetScrollMode(MENU_HEIGHT) -- (it scrolls only when it's longer)
  radio(root, ALL[cat], 0)
  if cat == "set" then -- (by class: a list of its own beside each)
    for _, group in ipairs(SET_GROUPS) do
      local sub = root:CreateButton(string.format("%s (%d)", group.name, #group.sets))
      sub:SetScrollMode(MENU_HEIGHT)
      for _, i in ipairs(group.sets) do radio(sub, list[i].name, i) end
    end
    return
  end
  local kind
  for i, g in ipairs(list) do
    if cat == "vendor" and g.rep ~= kind then -- (factions first, then merchants by place)
      kind = g.rep
      root:CreateTitle(g.rep and "Reputation" or "Merchants, by place")
    end
    radio(root, g.name, i)
  end
end

-- The third: in one dungeon or raid, all its bosses or one (0: all).
local function bossMenu(menu, root)
  local s = db()
  local cat, index = s.cat, s.index
  local g = picked()
  if not (PLACE_KINDS[cat] and g) then return end
  local function radio(label, i)
    root:CreateRadio(label, function(v) return (db().boss or 0) == v end,
      function(v) Loot.Pick(cat, index, v ~= 0 and v or nil, menu) end, i)
  end
  root:SetScrollMode(MENU_HEIGHT)
  radio("All bosses", 0)
  for i, b in ipairs(g.bosses or {}) do radio(b.name, i) end
end

-- The second dropdown's text: what's picked (a set some classes share is in several lists, and
-- the game would show each of them).
local function placeLabel()
  local g = picked()
  return g and g.name or ALL[db().cat]
end

local function createTop(panel)
  ui.group = CreateFrame("DropdownButton", nil, panel, "WowStyle1DropdownTemplate")
  ui.group:SetWidth(190)
  ui.group:SetPoint("TOPLEFT", 6, -4)
  ui.group:SetDefaultText("Everything")
  ui.group:SetupMenu(groupMenu)
  ui.place = CreateFrame("DropdownButton", nil, panel, "WowStyle1DropdownTemplate")
  ui.place:SetWidth(220)
  ui.place:SetPoint("LEFT", ui.group, "RIGHT", 8, 0)
  ui.place:SetDefaultText("")
  ui.place:SetSelectionText(placeLabel)
  ui.place:SetupMenu(placeMenu)
  ui.boss = CreateFrame("DropdownButton", nil, panel, "WowStyle1DropdownTemplate")
  ui.boss:SetWidth(180)
  ui.boss:SetPoint("LEFT", ui.place, "RIGHT", 8, 0)
  ui.boss:SetDefaultText("All bosses")
  ui.boss:SetupMenu(bossMenu)
  local function button(label, onClick, tip)
    local b = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    b:SetSize(140, 22)
    b:SetPoint("TOPRIGHT", -4, -5)
    b:SetText(label)
    b:SetScript("OnClick", onClick)
    G.Tooltip(b, label, tip)
    return b
  end
  ui.openPlace = button("Open in Dungeons", function()
    local p = picked()
    if p then G.Journal.Open(p.id or p.name) end
  end, "Its bosses, their abilities and its quests, on the Dungeons tab.")
  ui.tryOn = button("Try on the set", function()
    local g = picked()
    for _, id in ipairs(g and g.items or {}) do Items.Preview(id) end
  end, "Shows every piece on your character in the game's dressing room.")

  -- The search and filters.
  ui.search = CreateFrame("EditBox", nil, panel, "SearchBoxTemplate")
  ui.search:SetSize(200, 20)
  ui.search:SetPoint("TOPLEFT", 12, -36)
  ui.search:SetAutoFocus(false)
  ui.search:SetMaxLetters(60)
  ui.search:HookScript("OnTextChanged", function()
    offset = 0
    Loot:Refresh(true)
  end)
  local slots = dropdown(panel, 130, SLOTS, "slot", "Any slot")
  slots:SetPoint("LEFT", ui.search, "RIGHT", 10, 0)
  local typeOptions = {}
  for _, t in ipairs(TYPES) do typeOptions[#typeOptions + 1] = { t, t == "" and "Any type" or titleCase(t) } end
  local kinds = dropdown(panel, 130, typeOptions, "type", "Any type")
  kinds:SetPoint("LEFT", slots, "RIGHT", 6, 0)
  ui.who = Upgrades.Menu(panel)
  ui.who:SetWidth(160)
  ui.who:SetPoint("TOPRIGHT", -4, -34)
  local who = text(panel, "GameFontNormalSmall")
  who:SetPoint("RIGHT", ui.who, "LEFT", -6, 0)
  who:SetText("Upgrades for")
  ui.checks = {}
  local x = 4
  for _, c in ipairs({ { "usable", "Usable by me", 110 }, { "myLevel", "Up to my level", 118 }, { "ups", "Upgrades only", 112 } }) do
    local box = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    box:SetSize(22, 22)
    box:SetPoint("TOPLEFT", x, -62)
    local label = text(panel, "GameFontHighlightSmall")
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
  -- What the list is, beside them.
  ui.title = text(panel, "GameFontNormal")
  ui.title:SetPoint("TOPLEFT", x + 10, -67)
  ui.title:SetPoint("RIGHT", -110, 0)
  ui.more = text(panel, "GameFontDisableSmall")
  ui.more:SetPoint("TOPRIGHT", -6, -68)
  ui.more:SetJustifyH("RIGHT")
end

-- A text in a column of a row: its x and width (COLUMNS), at the top or bottom of the row.
local function column(row, font, where, x, width)
  local fs = text(row, font)
  fs:SetPoint(where, x, where == "TOPLEFT" and -1 or (where == "BOTTOMLEFT" and 1 or 0))
  fs:SetWidth(width)
  return fs
end

local function createList(panel)
  local list = CreateFrame("Frame", nil, panel)
  list:SetPoint("TOPLEFT", 0, -88)
  list:SetSize(LIST_WIDTH, ROWS * ROW_HEIGHT)
  wheel(list, function(delta) offset = offset - delta * 3 end)
  ui.rows = {}
  local name, slot, level = COLUMNS.name, COLUMNS.slot, COLUMNS.level
  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, list)
    row:SetSize(LIST_WIDTH, ROW_HEIGHT - 2)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.upgrade = row:CreateTexture(nil, "BACKGROUND")
    row.upgrade:SetAllPoints()
    row.upgrade:SetColorTexture(0.25, 0.83, 0.36, 0.14)
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetSize(22, 22)
    row.icon:SetPoint("LEFT", 4, 0)
    -- The item and where it comes from; its slot and type; its level; the upgrade; the star.
    row.name = column(row, "GameFontHighlightSmall", "TOPLEFT", name[1], name[2])
    row.from = column(row, "GameFontHighlightSmall", "BOTTOMLEFT", name[1], name[2])
    row.slotText = column(row, "GameFontHighlightSmall", "TOPLEFT", slot[1], slot[2])
    row.typeText = column(row, "GameFontHighlightSmall", "BOTTOMLEFT", slot[1], slot[2])
    row.levelText = column(row, "GameFontHighlightSmall", "LEFT", level[1], level[2])
    row.star = Items.Star(row, 16)
    row.star:SetPoint("RIGHT", -6, 0)
    row.gain = text(row, "GameFontHighlightSmall")
    row.gain:SetPoint("RIGHT", row.star, "LEFT", -6, 0)
    row.gain:SetWidth(COLUMNS.gain)
    row.gain:SetJustifyH("RIGHT")
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
  createTop(panel)
  createList(panel)
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

-- What's saved (GargoyleDB.loot), checked: a group, place or boss that's gone (or a 1.0.0 beta's
-- "place") starts on all of it. 1.0.6 and before kept which groups were open on the left.
function Loot:OnLogin()
  local s = db()
  s.open = nil
  if type(s.cat) ~= "string" or not TITLES[s.cat] then s.cat, s.index = "all", nil end
  if type(s.index) ~= "number" or not (LISTS[s.cat] and LISTS[s.cat][s.index]) then s.index = nil end
  local g = PLACE_KINDS[s.cat] and s.index and LISTS[s.cat][s.index]
  if type(s.boss) ~= "number" or not (g and g.bosses and g.bosses[s.boss]) then s.boss = nil end
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
