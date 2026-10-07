-- Gargoyle Damage Tooltips: adds a breakdown of your spells' damage and healing to their
-- tooltips, the same one gargoyle.gg's talent planner shows: base numbers, the share of your
-- spell damage, healing or attack power, your talents' bonuses, crit, and what that comes to
-- per cast, per second and per mana.
--
-- It only reads your own character through the game's addon API (spell power, crit, attack
-- power, weapon damage, talents, a spell's cast time and cost) and adds lines to tooltips.
-- The spells' base numbers and shares come with it (Data\<Class>.lua). It's turned on or off
-- in Gargoyle's options (Options > AddOns > Gargoyle), which use On() and SetOn() below.
local _, ns = ...

GargoyleTooltips = {}
local T = GargoyleTooltips

function T.On()
  return not (type(GargoyleTooltipsDB) == "table" and GargoyleTooltipsDB.on == false)
end

function T.SetOn(on)
  if type(GargoyleTooltipsDB) ~= "table" then GargoyleTooltipsDB = {} end
  GargoyleTooltipsDB.on = on and true or false
end

local function data()
  local _, class = UnitClass("player")
  return ns.data and ns.data[class]
end

-- The game's numbers can be "secret" (hidden from addons) in some situations; then there's
-- nothing to work with, and nothing is shown.
local function plain(v)
  if issecretvalue and issecretvalue(v) then return nil end
  return type(v) == "number" and v or nil
end

-- ---- Your talents (points spent, by talent spell and by name) ----

local talentRanks -- read when first needed, again after talents change

local function spellName(spellID)
  if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(spellID) end
  if GetSpellInfo then return (GetSpellInfo(spellID)) end
end

local function readTalents()
  local ranks = { bySpell = {}, byName = {} }
  if C_Traits and C_Traits.GetTreeNodes and C_ClassTalents and C_ClassTalents.GetActiveConfigID then
    -- WoW Forever: one talent tree with the classic three as groups in it.
    local configID = C_ClassTalents.GetActiveConfigID()
    local config = configID and C_Traits.GetConfigInfo(configID)
    local treeID = config and config.treeIDs and config.treeIDs[1]
    for _, nodeID in ipairs(treeID and C_Traits.GetTreeNodes(treeID) or {}) do
      local node = C_Traits.GetNodeInfo(configID, nodeID)
      local rank = node and (node.ranksPurchased or node.activeRank) or 0
      if rank > 0 then
        local entryID = (node.activeEntry and node.activeEntry.entryID) or (node.entryIDs and node.entryIDs[1])
        local entry = entryID and C_Traits.GetEntryInfo(configID, entryID)
        local definition = entry and entry.definitionID and C_Traits.GetDefinitionInfo(entry.definitionID)
        local spell = definition and definition.spellID
        local name = definition and ((definition.overrideName ~= "" and definition.overrideName) or (spell and spellName(spell)))
        if spell then ranks.bySpell[spell] = rank end
        if name then ranks.byName[name] = rank end
      end
    end
  elseif GetNumTalentTabs and GetNumTalents and GetTalentInfo then
    for tab = 1, GetNumTalentTabs() do
      for index = 1, GetNumTalents(tab) do
        local name, _, _, _, rank = GetTalentInfo(tab, index)
        if type(name) == "string" and type(rank) == "number" and rank > 0 then ranks.byName[name] = rank end
      end
    end
  end
  return ranks
end

local function rankOf(talent)
  talentRanks = talentRanks or readTalents()
  for _, spell in ipairs(talent.spells) do
    if talentRanks.bySpell[spell] then return talentRanks.bySpell[spell] end
  end
  return talentRanks.byName[talent.name] or 0
end

-- ---- The math (as the website's spell tooltips do it) ----

local SCHOOLS = { Physical = 1, Holy = 2, Fire = 3, Nature = 4, Frost = 5, Shadow = 6, Arcane = 7 }
local HEALERS = { PRIEST = true, PALADIN = true, DRUID = true, SHAMAN = true }
-- Damage, healing and crit damage bonuses multiply together (+10% and +20% is +32%).
local MULTIPLY = { damage = true, healing = true, crit_damage = true }

local function has(list, value)
  for _, v in ipairs(list) do
    if v == value then return true end
  end
end

-- Your talents' bonus to `stat` for a part: the total (in %) and each talent's share.
-- `general`: also the bonuses that apply to everything (the game's own crit chance already
-- has those, so crit leaves them out, and spell crit also leaves out a school's own: "Fire
-- spells").
local function talentBonus(stat, scopes, general, skip)
  local total, items = 0, {}
  for _, talent in ipairs(data().talents) do
    for _, effect in ipairs(talent.effects) do
      local applies = effect.stat == stat and ((effect.scope == nil and general) or (effect.scope and has(scopes, effect.scope)))
      if applies and not (skip and effect.scope and skip(effect.scope)) then
        local rank = rankOf(talent)
        local value = rank > 0 and effect.values[math.min(rank, #effect.values)]
        if value and value ~= 0 then
          total = MULTIPLY[stat] and ((1 + total / 100) * (1 + value / 100) - 1) * 100 or total + value
          items[#items + 1] = { talent.name, value }
        end
      end
    end
  end
  return total, items
end

-- Spell damage for a school ("Frostfire": the better of the two).
local function spellDamage(school)
  local best = 0
  for name, index in pairs(SCHOOLS) do
    if index > 1 and school and school:find(name, 1, true) then
      best = math.max(best, plain(GetSpellBonusDamage(index)) or 0)
    end
  end
  return best
end

local function attackPower(ranged)
  local base, plus, minus
  if ranged then base, plus, minus = UnitRangedAttackPower("player") else base, plus, minus = UnitAttackPower("player") end
  return math.max(0, (plain(base) or 0) + (plain(plus) or 0) + (plain(minus) or 0))
end

local function schoolSpells(scope)
  for name in pairs(SCHOOLS) do
    if scope == name .. " spells" then return true end
  end
end

-- One part (direct damage, over time, a heal, a weapon strike...) worked out: its rows and
-- its average with crits.
local function workOut(part, rows)
  local physical = part.kind == "weapon" or part.kind == "physical"
  local heal = part.kind == "heal" or (part.kind == "absorb" and HEALERS[select(2, UnitClass("player"))])
  local min, max
  if part.kind == "weapon" then
    local low, high
    if part.ranged then
      local _
      _, low, high = UnitRangedDamage("player")
    else
      low, high = UnitDamage("player")
    end
    low, high = plain(low), plain(high)
    if not low or not high or high <= 0 then return end
    min, max = low * part.pct / 100, high * part.pct / 100
    rows[#rows + 1] = { (part.ranged and "Ranged weapon" or "Weapon") .. " damage" .. (part.pct ~= 100 and (" × " .. part.pct .. "%") or ""), { min, max } }
    if part.bonus and part.bonus ~= 0 then
      rows[#rows + 1] = { "Ability bonus", "+" .. ns.num(part.bonus) }
      min, max = min + part.bonus, max + part.bonus
    end
  else
    min, max = part.min, part.max
    local label = part.periodic and ("Base, over " .. (part.duration or "the") .. " sec") or "Base"
    if part.combo then label = label .. " at " .. part.combo .. " combo points" end
    rows[#rows + 1] = { label, { min, max } }
    if part.ap then
      local ap = attackPower(part.ranged)
      local added = ap * part.ap / 100
      rows[#rows + 1] = { ns.num(part.ap) .. "% of " .. ns.num(ap) .. " attack power", "+" .. ns.num(added) }
      min, max = min + added, max + added
    end
    if part.coeff then
      local bonus = heal and (plain(GetSpellBonusHealing()) or 0) or spellDamage(part.school)
      local added = bonus * part.coeff
      rows[#rows + 1] = { (heal and "Bonus healing " or "Spell damage ") .. ns.num(bonus) .. " × " .. ns.num(part.coeff * 100, 2) .. "%", "+" .. ns.num(added) }
      min, max = min + added, max + added
    end
  end
  -- Talents: weapon strikes only their own (the game's weapon damage has the rest already).
  local stat = (part.kind == "heal" or part.kind == "absorb") and "healing" or "damage"
  local bonus, items = talentBonus(stat, part.scopes, part.kind ~= "weapon")
  if bonus ~= 0 then
    local mult = 1 + bonus / 100
    local names = {}
    for _, item in ipairs(items) do names[#names + 1] = item[1] .. " " .. ns.signed(item[2]) .. "%" end
    rows[#rows + 1] = { "Talents", "× " .. ns.num(mult, 2) }
    rows[#rows + 1] = { table.concat(names, ", "), nil, "sub" }
    min, max = min * mult, max * mult
  end
  local kindName = (part.kind == "heal" and "healing") or (part.kind == "absorb" and "absorb") or "damage"
  local total = "Total " .. kindName
  if part.periodic and (part.ticks or 1) > 1 then total = total .. " (" .. part.ticks .. " ticks of " .. ns.num(min / part.ticks) .. ")" end
  rows[#rows + 1] = { total, { min, max }, "total" }
  local avg = (min + max) / 2
  if part.crit then
    local chance, critBonus
    if physical then
      chance = plain(part.ranged and GetRangedCritChance() or GetCritChance()) or 0
      chance = chance + talentBonus("crit", part.scopes, false)
      critBonus = 1
    else
      chance = plain(GetSpellCritChance(SCHOOLS[part.school] or 2)) or 0
      chance = chance + talentBonus("spell_crit", part.scopes, false, schoolSpells)
      critBonus = heal and 0.5 or 0.5 * (1 + talentBonus("crit_damage", part.scopes, true) / 100)
    end
    chance = math.max(0, math.min(100, chance))
    if chance > 0 then
      avg = avg * (1 + chance / 100 * critBonus)
      rows[#rows + 1] = { "Crit " .. ns.num(chance, 2) .. "%" .. (part.periodic and " per tick" or "") .. " for "
        .. ns.num((1 + critBonus) * 100) .. "%", "avg " .. ns.num(avg) }
    end
  end
  return avg
end

local function title(part, spell)
  if part.kind == "weapon" then return part.ranged and "Ranged strike" or "Weapon strike" end
  if part.kind == "absorb" then return "Absorb shield" end
  local kindName = part.kind == "heal" and "healing" or "damage"
  local when = part.periodic and (spell.channeled and "Channeled " or "Over time ") or "Direct "
  return when .. kindName .. ((part.school and part.school ~= "Physical") and (" · " .. part.school) or "")
end

local function castTime(spellID, spell)
  if spell.channeled then return spell.cast end
  local ms
  if C_Spell and C_Spell.GetSpellInfo then
    local info = C_Spell.GetSpellInfo(spellID)
    ms = info and info.castTime
  elseif GetSpellInfo then
    ms = select(4, GetSpellInfo(spellID))
  end
  ms = plain(ms)
  return ms and ms / 1000 or spell.cast
end

local function manaCost(spellID)
  local costs = (C_Spell and C_Spell.GetSpellPowerCost and C_Spell.GetSpellPowerCost(spellID))
    or (GetSpellPowerCost and GetSpellPowerCost(spellID))
  for _, cost in ipairs(type(costs) == "table" and costs or {}) do
    if cost.type == 0 then return plain(cost.cost) end -- (0: mana)
  end
end

-- The global cooldown: 1.5 sec, 1 sec for Rogues and Druids in Cat Form.
local function globalCooldown()
  local _, class = UnitClass("player")
  if class == "ROGUE" then return 1 end
  if class == "DRUID" and GetShapeshiftFormID and GetShapeshiftFormID() == 1 then return 1 end
  return 1.5
end

-- Every line for a spell's tooltip: { left, right, style }, or nil if there's nothing to say.
function T.Lines(spellID)
  local known = data()
  local spell = known and known.spells[spellID]
  if not spell then return end
  local lines, perCast, healing, damage, periodic = {}, 0, false, false, false
  for _, part in ipairs(spell.parts) do
    local rows = {}
    local avg = workOut(part, rows)
    if avg then
      lines[#lines + 1] = { title(part, spell), nil, "title" }
      for _, row in ipairs(rows) do lines[#lines + 1] = row end
      perCast = perCast + avg
      if part.kind == "heal" or part.kind == "absorb" then healing = true else damage = true end
      periodic = periodic or part.periodic
    end
  end
  if #lines == 0 then return end
  local kindName = (healing and not damage) and "healing" or "damage"
  lines[#lines + 1] = { "Average " .. kindName .. " per cast" .. (periodic and " (over time included)" or ""), ns.num(perCast), "summary" }
  local cast = castTime(spellID, spell)
  local time = spell.channeled and cast or math.max(cast or 0, globalCooldown())
  if time and time > 0 then
    lines[#lines + 1] = { "Per second of casting (" .. ns.num(time, 2) .. " sec)", ns.num(perCast / time) }
  end
  local mana = manaCost(spellID)
  if mana and mana > 0 then
    lines[#lines + 1] = { "Per mana (" .. ns.num(mana) .. " mana)", ns.num(perCast / mana, 2) }
  end
  return lines
end

-- ---- Numbers as text ----

-- 12.3 below 10, whole numbers above (like the website); `places` for more.
function ns.num(v, places)
  if places then
    local m = 10 ^ places
    return tostring(math.floor(v * m + 0.5) / m)
  end
  if math.abs(v) < 10 then return tostring(math.floor(v * 10 + 0.5) / 10) end
  return tostring(math.floor(v + 0.5))
end

function ns.signed(v)
  return (v >= 0 and "+" or "-") .. ns.num(math.abs(v))
end

local function rangeText(r)
  local a, b = ns.num(r[1]), ns.num(r[2])
  return a == b and a or (a .. " – " .. b)
end

-- ---- Tooltips ----

local GOLD, WHITE, GREY, GREEN = { 1, 0.82, 0 }, { 1, 1, 1 }, { 0.6, 0.6, 0.6 }, { 0.3, 1, 0.3 }

local function addTo(tooltip, spellID)
  if not T.On() or type(spellID) ~= "number" or not plain(spellID) then return end
  if not (tooltip and tooltip.AddLine and tooltip.AddDoubleLine) then return end
  local ok, lines = pcall(T.Lines, spellID) -- (worked out in full first, so a problem adds nothing)
  if not ok or not lines then return end
  tooltip:AddLine(" ")
  for _, line in ipairs(lines) do
    local left, right, style = line[1], line[2], line[3]
    if type(right) == "table" then right = rangeText(right) end
    if style == "title" then
      tooltip:AddLine(left, GOLD[1], GOLD[2], GOLD[3])
    elseif style == "sub" then
      tooltip:AddLine("  " .. left, GREY[1], GREY[2], GREY[3], true)
    else
      local color = (style == "total" and GREEN) or (style == "summary" and GOLD) or WHITE
      tooltip:AddDoubleLine(left, right or "", WHITE[1], WHITE[2], WHITE[3], color[1], color[2], color[3])
    end
  end
  tooltip:Show() -- (resized for the new lines)
end

if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Spell, function(tooltip, info)
    addTo(tooltip, info and info.id)
  end)
elseif GameTooltip and GameTooltip.HookScript then
  GameTooltip:HookScript("OnTooltipSetSpell", function(tooltip)
    local _, spellID = tooltip:GetSpell()
    addTo(tooltip, spellID)
  end)
end

-- Talents are read again after they change (some of these events are only in some clients).
local events = CreateFrame("Frame")
for _, event in ipairs({ "TRAIT_CONFIG_UPDATED", "PLAYER_TALENT_UPDATE", "CHARACTER_POINTS_CHANGED", "SPELLS_CHANGED" }) do
  pcall(events.RegisterEvent, events, event)
end
events:SetScript("OnEvent", function() talentRanks = nil end)
