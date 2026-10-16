-- Upgrades and the wishlist: shared by the module addons (Gargoyle_Dungeons, Gargoyle_Loot).
--
-- Upgrades: the items that are upgrades for one of your Gargoyle characters, with how much
-- better each one is. The website's planner works those out (from the character's gear,
-- talents and level) and the Gargoyle app brings them in. For each character you play, you
-- pick whose upgrades are shown ("Upgrades for"); it starts on the Gargoyle character kept up
-- to date from it. Items you're wearing aren't marked.
--
-- The wishlist: items you want, kept per Gargoyle character on your account. Stars you click in
-- game wait in GargoyleDB.wishes until the app sends them (like signups), and the website's
-- list comes back with the app's data.
--
-- Item tooltips anywhere in the game get a line for each: "Gargoyle: upgrade for Jainamage,
-- +12.3 (4%)" and "On Jainamage's wishlist". It only shows things.
local _, ns = ...

local Upgrades, Wishlist = {}, {}
ns.Upgrades, ns.Wishlist = Upgrades, Wishlist

local GREEN, GOLD = "|cff3fd35c", "|cffffd100"
local MAX_WISHES = 200 -- (per character, as on the website)
local KEEP_DAYS = 30 -- a wishlist change the app never sent is let go of after this

-- ---- Whose upgrades ----

-- The Gargoyle character whose upgrades (and wishlist) go with the one you're playing: the one
-- picked, else the one kept up to date from it. Nil for no one.
function Upgrades.Chosen()
  local key = ns.PlayerKey()
  local picked = key and GargoyleDB.upgradesFor[key]
  if picked == false then return end
  local fromGame
  for _, c in ipairs(ns.sync.characters) do
    if picked and c.id == picked then return c end
    if key and c.game == key then fromGame = c end
  end
  return fromGame
end

function Upgrades.Choose(id)
  local key = ns.PlayerKey()
  if key then GargoyleDB.upgradesFor[key] = id or false end
  if ns.RefreshShown then ns.RefreshShown(true) end
end

local function worn(itemID)
  local isEquipped = (C_Item and C_Item.IsEquippedItem) or IsEquippedItem
  if not isEquipped then return false end
  local ok, yes = pcall(isEquipped, itemID)
  return ok and yes == true
end
Upgrades.Worn = worn

-- How much better an item is for the character ({gain, gain in %}), or nil.
function Upgrades.Gain(itemID, character)
  character = character or Upgrades.Chosen()
  local gain = character and character.upgrades and character.upgrades.items[itemID]
  if gain and not worn(itemID) then return gain end
end

-- "+12.3 (4.1%)": one decimal under 10, as on the website.
function Upgrades.GainText(gain)
  local points = gain[1] >= 10 and string.format("%d", math.floor(gain[1] + 0.5)) or string.format("%.1f", gain[1])
  return string.format("+%s (%s%%)", points, gain[2] >= 10 and string.format("%d", math.floor(gain[2] + 0.5)) or string.format("%.1f", gain[2]))
end

-- Why there are no upgrade marks (or nil when they're there): for the bottom of a tab.
function Upgrades.Missing(character)
  local sync = ns.sync
  if not sync.loaded then
    return "Upgrade marks come from your Gargoyle account: with the Gargoyle app running, reload or log in again."
  end
  if not sync.sendsUpgrades then
    return "Upgrade marks need the newest Gargoyle app. Its window offers it when it's out: update, then reload."
  end
  if not character then
    if #sync.characters == 0 then return "Save a character on the website to see which items are upgrades for it." end
    return "Pick one of your Gargoyle characters (Upgrades for) to see which items are upgrades for it."
  end
  if not character.upgrades then
    return ns.Plain(character.name) .. "'s upgrades haven't been worked out yet: open it in the planner on the website, then sync."
  end
end

-- "Jainamage (Frost, level 42)"
function Upgrades.Who(character)
  local u = character.upgrades
  return ns.Plain(character.name) .. ((u and u.spec and u.level) and string.format(" (%s, level %d)", ns.Plain(u.spec), u.level) or "")
end

-- The "Upgrades for" dropdown: No one, or one of your Gargoyle characters.
function Upgrades.Menu(parent)
  local menu = CreateFrame("DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
  menu:SetWidth(170)
  menu:SetDefaultText("No one")
  menu:SetupMenu(function(_, root)
    root:CreateRadio("No one", function() return Upgrades.Chosen() == nil end, function() Upgrades.Choose(nil) end)
    local list = {}
    for _, c in ipairs(ns.sync.characters) do list[#list + 1] = c end
    table.sort(list, function(a, b) return a.name:lower() < b.name:lower() end)
    for _, c in ipairs(list) do
      root:CreateRadio(ns.Plain(c.name), function(id)
        local chosen = Upgrades.Chosen()
        return chosen ~= nil and chosen.id == id
      end, Upgrades.Choose, c.id)
    end
  end)
  return menu
end

-- ---- The wishlist ----

local function pending(character)
  local changes = {}
  for _, w in ipairs(GargoyleDB.wishes) do
    if w.character == character.id and not ns.sync.done[w.id] then changes[#changes + 1] = w end
  end
  return changes
end

-- The character's wishlist: {item id = true}, the website's with the changes made in game since.
function Wishlist.Items(character)
  character = character or Upgrades.Chosen()
  local items = {}
  if not character then return items end
  for id in pairs(character.wishlist or {}) do items[id] = true end
  for _, w in ipairs(pending(character)) do items[w.item] = w.on or nil end
  return items
end

function Wishlist.Has(itemID, character)
  return Wishlist.Items(character)[itemID] == true
end

function Wishlist.Count(character)
  local n = 0
  for _ in pairs(Wishlist.Items(character)) do n = n + 1 end
  return n
end

-- Puts an item on the character's wishlist or takes it off. Returns nil, or why it can't.
function Wishlist.Set(itemID, on, character)
  character = character or Upgrades.Chosen()
  if not character then return "Pick one of your Gargoyle characters (Upgrades for) to keep a wishlist for it." end
  if type(itemID) ~= "number" then return "That isn't an item." end
  if on and not Wishlist.Has(itemID, character) and Wishlist.Count(character) >= MAX_WISHES then
    return string.format("%s's wishlist is full (%d items).", ns.Plain(character.name), MAX_WISHES)
  end
  -- Only the latest change to each item needs sending, and none if it's back as the website has it.
  for i = #GargoyleDB.wishes, 1, -1 do
    local w = GargoyleDB.wishes[i]
    if w.character == character.id and w.item == itemID and not ns.sync.done[w.id] then table.remove(GargoyleDB.wishes, i) end
  end
  if ((character.wishlist or {})[itemID] == true) ~= (on == true) then
    GargoyleDB.wishes[#GargoyleDB.wishes + 1] = {
      id = string.format("w%x-%04x", time(), math.random(0, 0xffff)),
      character = character.id, item = itemID, on = on == true, at = time(),
    }
  end
  if ns.RefreshShown then ns.RefreshShown(true) end
  if ns.UpdateStatus then ns.UpdateStatus() end
end

function Wishlist.Toggle(itemID, character)
  return Wishlist.Set(itemID, not Wishlist.Has(itemID, character), character)
end

-- "2 wishlist changes" (waiting to sync), or nil.
function Wishlist.Waiting()
  local n = 0
  for _, w in ipairs(GargoyleDB.wishes) do
    if not ns.sync.done[w.id] then n = n + 1 end
  end
  if n > 0 then return string.format("%d wishlist change%s", n, n == 1 and "" or "s") end
end

local function validWish(w)
  return type(w) == "table" and type(w.id) == "string" and type(w.character) == "number" and type(w.item) == "number"
    and type(w.on) == "boolean" and type(w.at) == "number"
end

-- At login: let go of the changes the website has answered (saying so when it said no), and very old ones.
function Wishlist.Tidy()
  local kept, now = {}, time()
  local REASONS = { full = "the wishlist is full", unknown = "that item isn't in Gargoyle's lists",
                    character = "that character isn't on your account any more" }
  for _, w in ipairs(GargoyleDB.wishes) do
    if validWish(w) then
      local result = ns.sync.done[w.id]
      if result then
        if result ~= "saved" then
          ns.say(string.format("a wishlist change wasn't saved: %s.", REASONS[result] or ns.Plain(result)))
        end
      elseif now - w.at < KEEP_DAYS * 86400 then
        kept[#kept + 1] = w
      end
    end
  end
  GargoyleDB.wishes = kept
end

-- ---- Item tooltips anywhere ----

function Upgrades.TooltipsOn()
  return GargoyleDB.tooltipMarks ~= false
end

function Upgrades.SetTooltipsOn(on)
  GargoyleDB.tooltipMarks = on and true or false
end

local function onItemTooltip(tooltip, data)
  if not GargoyleDB or not Upgrades.TooltipsOn() or type(data) ~= "table" or not tooltip.AddLine then return end
  local id = data.id
  if type(id) ~= "number" or (issecretvalue and issecretvalue(id)) then return end
  local character = Upgrades.Chosen()
  if not character then return end
  local gain = Upgrades.Gain(id, character)
  if gain then
    tooltip:AddLine(string.format("%sGargoyle: upgrade for %s, %s|r", GREEN, ns.Plain(character.name), Upgrades.GainText(gain)))
  end
  if Wishlist.Has(id, character) then
    tooltip:AddLine(string.format("%sOn %s's wishlist|r", GOLD, ns.Plain(character.name)))
  end
end

function Upgrades.OnLogin()
  Wishlist.Tidy()
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, onItemTooltip)
  end
end

-- ---- Items in Gargoyle's lists ----

local Items = {}
ns.Items = Items

-- Where each kind of gear is worn (the game's inventory slots).
local SLOTS = {
  INVTYPE_HEAD = { 1 }, INVTYPE_NECK = { 2 }, INVTYPE_SHOULDER = { 3 }, INVTYPE_BODY = { 4 }, INVTYPE_CHEST = { 5 },
  INVTYPE_ROBE = { 5 }, INVTYPE_WAIST = { 6 }, INVTYPE_LEGS = { 7 }, INVTYPE_FEET = { 8 }, INVTYPE_WRIST = { 9 },
  INVTYPE_HAND = { 10 }, INVTYPE_FINGER = { 11, 12 }, INVTYPE_TRINKET = { 13, 14 }, INVTYPE_CLOAK = { 15 },
  INVTYPE_WEAPON = { 16, 17 }, INVTYPE_SHIELD = { 17 }, INVTYPE_2HWEAPON = { 16 }, INVTYPE_WEAPONMAINHAND = { 16 },
  INVTYPE_WEAPONOFFHAND = { 17 }, INVTYPE_HOLDABLE = { 17 }, INVTYPE_RANGED = { 18 }, INVTYPE_THROWN = { 18 },
  INVTYPE_RANGEDRIGHT = { 18 }, INVTYPE_RELIC = { 18 }, INVTYPE_TABARD = { 19 },
}

function Items.Link(id)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  if not getInfo then return end
  local _, link = getInfo(id)
  return link
end

-- What you wear where the item would go: the items' links (none for an empty slot).
function Items.WornThere(id)
  local instant = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
  local equipLoc = instant and select(4, instant(id))
  local links = {}
  for _, slot in ipairs(SLOTS[equipLoc] or {}) do
    local link = GetInventoryItemLink and GetInventoryItemLink("player", slot)
    if link then links[#links + 1] = link end
  end
  return links
end

-- A click on an item with Ctrl or Shift: the game's own handling, as in your bags (Ctrl tries it
-- on in the dressing room, Shift puts its link in the chat box you have open). True if it was one.
function Items.Click(id)
  if not (IsModifiedClick and HandleModifiedItemClick) then return false end
  if not (IsModifiedClick("DRESSUP") or IsModifiedClick("CHATLINK")) then return false end
  local link = Items.Link(id)
  return link ~= nil and HandleModifiedItemClick(link) == true
end

-- Tries the item on in the game's dressing room (the Preview buttons).
function Items.Preview(id)
  local link = Items.Link(id)
  if link and DressUpItemLink then DressUpItemLink(link) end
end

-- The game's tooltip for an item (with Gargoyle's lines, above, and `lines`: more to say, such as
-- where it comes from), what you wear there, and the game's side-by-side comparison when you
-- hold Shift (or always, if that's set in its options).
function Items.Tooltip(owner, id, lines)
  GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
  GameTooltip:SetItemByID(id)
  for _, line in ipairs(lines or {}) do GameTooltip:AddLine(line, 1, 0.82, 0, true) end
  local worn = Items.WornThere(id)
  for i, link in ipairs(worn) do
    GameTooltip:AddLine((i == 1 and "You wear: " or "and: ") .. link, 0.7, 0.7, 0.7)
  end
  GameTooltip:AddLine("Ctrl-click: try it on. Shift-click: link it in chat.", 0.5, 0.5, 0.5)
  GameTooltip:Show()
  if GameTooltip_ShowCompareItem and IsModifiedClick and IsModifiedClick("COMPAREITEMS") then
    pcall(GameTooltip_ShowCompareItem, GameTooltip)
  end
end

-- A star that puts the item on your wishlist or takes it off (button.itemID: the item).
function Items.Star(parent, size)
  local star = CreateFrame("Button", nil, parent)
  star:SetSize(size or 16, size or 16)
  star.icon = star:CreateTexture(nil, "ARTWORK")
  star.icon:SetAllPoints()
  star.icon:SetAtlas("PetJournal-FavoritesIcon")
  function star.Update(self)
    if ns.Wishable and self.itemID and not ns.Wishable(self.itemID) then return self:Hide() end
    self:Show()
    local on = self.itemID ~= nil and Wishlist.Has(self.itemID)
    self.icon:SetDesaturated(not on)
    self.icon:SetAlpha(on and 1 or 0.3)
  end
  star:SetScript("OnClick", function(self)
    local why = Wishlist.Toggle(self.itemID)
    if why then ns.say(why) end
    self:Update()
  end)
  star:SetScript("OnEnter", function(self)
    local character = Upgrades.Chosen()
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    if not character then
      GameTooltip:SetText("Wishlist")
      GameTooltip:AddLine("Pick one of your Gargoyle characters (Upgrades for) to keep a wishlist for it.", 1, 1, 1, true)
    elseif Wishlist.Has(self.itemID) then
      GameTooltip:SetText("On " .. ns.Plain(character.name) .. "'s wishlist")
      GameTooltip:AddLine("Click to take it off.", 1, 1, 1, true)
    else
      GameTooltip:SetText("Add to " .. ns.Plain(character.name) .. "'s wishlist")
      GameTooltip:AddLine("Your wishlist is on the website too (the Gargoyle app sends it).", 1, 1, 1, true)
    end
    GameTooltip:Show()
  end)
  star:SetScript("OnLeave", function() GameTooltip:Hide() end)
  return star
end
