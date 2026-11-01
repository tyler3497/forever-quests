-- tools/convert.lua
-- Converts QuestieDB's Forever quest data into the forever-quests format:
--   data/quests.json  (canonical, keyed by quest ID)
--   data/zones.json   (zones that contain quests, with uiMapIDs)
--   data/QuestDB.lua  (addon-ready Lua, same content as the JSON)
--   stats.json        (counts for manifest assembly)
--
-- Input files are QuestieDB sources, used verbatim:
--   data/Forever/foreverQuestDB.lua
--   support/Forever/Zones/areaIdToUiMapId.lua
--   support/Zones/areaIdToUiMapId.lua (fallback mapping only)
--
-- The quest file stores its data as a long string: QuestieDB.questData is a
-- chunk of the form `return { [questID] = { positional fields } }` where the
-- positions follow QuestieDB.questKeys (also defined in the same file).
-- Field names below come from that table at runtime, not from a hardcoded
-- copy, so a QuestieDB schema change surfaces as a new name instead of a
-- silent mis-mapping.
--
-- Usage: lua5.1 tools/convert.lua <questDB.lua> <foreverArea.lua> <genericArea.lua> <outdir>

local questFile, foreverAreaFile, genericAreaFile, outdir = ...

-- Stub the module loader the QuestieDB files expect.
local modules = { ZoneDB = { private = {} } }
QuestieLoader = {
  ImportModule = function(_, name)
    modules[name] = modules[name] or {}
    return modules[name]
  end,
}

dofile(questFile)
local qdb = modules["QuestieDB"]
assert(qdb.questData, "questData string not found in quest file")
assert(qdb.questKeys, "questKeys not found in quest file")
local questsRaw = assert(loadstring(qdb.questData))()

-- index -> field name, from the file's own questKeys table.
local indexToName = {}
for name, idx in pairs(qdb.questKeys) do indexToName[idx] = name end

-- Load an area->uiMap table out of a ZoneDB file. Returns base + override.
local function loadAreaTables(path)
  local zb = modules["ZoneDB"]
  zb.private.areaIdToUiMapId = nil
  zb.private.areaIdToUiMapIdOverride = nil
  dofile(path)
  local base = zb.private.areaIdToUiMapId
  local over = zb.private.areaIdToUiMapIdOverride
  if type(base) == "string" then base = assert(loadstring(base))() end
  if type(over) == "string" then over = assert(loadstring(over))() end
  return base or {}, over or {}
end

local genericBase, genericOver = loadAreaTables(genericAreaFile)
local foreverBase, foreverOver = loadAreaTables(foreverAreaFile)
-- Layer: generic base, generic override, Forever base, Forever override.
local areaToUiMap = {}
for _, t in ipairs({ genericBase, genericOver, foreverBase, foreverOver }) do
  for k, v in pairs(t) do areaToUiMap[k] = v end
end

-- ---------- normalization helpers ----------

local function isEmpty(t) return t == nil or next(t) == nil end

local function idarray(t)
  if isEmpty(t) then return nil end
  local out = {}
  for _, v in ipairs(t) do out[#out + 1] = v end
  return out
end

-- startedBy/finishedBy: positional {npcs?, objects?, items?}
local function givers(t, withItems)
  if isEmpty(t) then return nil end
  local out = {}
  if not isEmpty(t[1]) then out.npcs = idarray(t[1]) end
  if not isEmpty(t[2]) then out.objects = idarray(t[2]) end
  if withItems and not isEmpty(t[3]) then out.items = idarray(t[3]) end
  if isEmpty(out) then return nil end
  return out
end

local function pair(t)
  if isEmpty(t) then return nil end
  return { id = t[1], value = t[2] }
end

local function pairsList(t)
  if isEmpty(t) then return nil end
  local out = {}
  for _, p in ipairs(t) do out[#out + 1] = { id = p[1], value = p[2] } end
  return out
end

-- objectives: six positional groups (creature, object, item, reputation,
-- kill-credit, spell). Rows keep their raw shape; groups are named.
local objectiveGroupNames = { "creatures", "objects", "items", "reputation", "killCredits", "spells" }
local function objectives(t)
  if isEmpty(t) then return nil end
  local out = {}
  for i, name in ipairs(objectiveGroupNames) do
    if not isEmpty(t[i]) then out[name] = t[i] end
  end
  if isEmpty(out) then return nil end
  return out
end

-- triggerEnd: {text, {[zoneID] = {{x,y},...}, ...}}
local function trigger(t)
  if isEmpty(t) then return nil end
  local out = {}
  if t[1] ~= nil then out.text = t[1] end
  if t[2] ~= nil then
    local zones = {}
    for zoneId, coords in pairs(t[2]) do
      zones[#zones + 1] = { zoneId = zoneId, coords = coords }
    end
    table.sort(zones, function(a, b) return a.zoneId < b.zoneId end)
    if #zones > 0 then out.zones = zones end
  end
  if isEmpty(out) then return nil end
  return out
end

local function stringarray(t)
  if isEmpty(t) then return nil end
  local out = {}
  for _, v in ipairs(t) do out[#out + 1] = v end
  return out
end

-- ---------- per-quest conversion ----------

local function convertQuest(id, raw)
  local byName = {}
  for idx, name in pairs(indexToName) do byName[name] = raw[idx] end

  local q = {}
  q.id = id
  q.name = byName.name
  local zoneOrSort = byName.zoneOrSort
  q.zoneOrSort = zoneOrSort
  if zoneOrSort and zoneOrSort > 0 then q.areaId = zoneOrSort end
  if zoneOrSort and zoneOrSort < 0 then q.sortId = -zoneOrSort end
  q.requiredLevel = byName.requiredLevel
  q.questLevel = byName.questLevel
  q.requiredMaxLevel = byName.requiredMaxLevel
  q.requiredRaces = byName.requiredRaces
  q.requiredClasses = byName.requiredClasses
  q.requiredSkill = pair(byName.requiredSkill)
  q.requiredMinRep = pair(byName.requiredMinRep)
  q.requiredMaxRep = pair(byName.requiredMaxRep)
  q.requiredRanks = pairsList(byName.requiredRanks)
  q.requiredSpell = byName.requiredSpell
  q.requiredSpecialization = byName.requiredSpecialization
  q.sourceItemId = byName.sourceItemId
  q.requiredSourceItems = idarray(byName.requiredSourceItems)
  q.preQuestGroup = idarray(byName.preQuestGroup)
  q.preQuestSingle = idarray(byName.preQuestSingle)
  q.childQuests = idarray(byName.childQuests)
  q.inGroupWith = idarray(byName.inGroupWith)
  q.exclusiveTo = idarray(byName.exclusiveTo)
  q.nextQuestInChain = byName.nextQuestInChain
  q.parentQuest = byName.parentQuest
  q.breadcrumbForQuestId = byName.breadcrumbForQuestId
  q.breadcrumbs = idarray(byName.breadcrumbs)
  q.availableUntilCompleted = byName.availableUntilCompleted
  q.availableStartingWith = byName.availableStartingWith
  q.disabledByQuest = byName.disabledByQuest
  q.questFlags = byName.questFlags
  q.specialFlags = byName.specialFlags
  q.startedBy = givers(byName.startedBy, true)
  q.finishedBy = givers(byName.finishedBy, false)
  q.objectivesText = stringarray(byName.objectivesText)
  q.objectives = objectives(byName.objectives)
  q.triggerEnd = trigger(byName.triggerEnd)
  q.extraObjectives = isEmpty(byName.extraObjectives) and nil or byName.extraObjectives
  -- Rewards: QuestieDB quest records carry reputation rewards only. Item,
  -- money and XP rewards are NOT in this source (XP is level-formulaic;
  -- item rewards only exist in the live offer dialog). They are documented
  -- as a gap in the README, not invented here.
  local rep = pairsList(byName.reputationReward)
  if rep then
    local rr = {}
    for _, p in ipairs(rep) do rr[#rr + 1] = { factionId = p.id, amount = p.value } end
    q.rewards = { reputation = rr }
  end
  -- Drop nils.
  local clean = {}
  for k, v in pairs(q) do if v ~= nil then clean[k] = v end end
  return clean
end

-- ---------- JSON encoder (deterministic: sorted keys) ----------

local function jsonEscape(s)
  return (s:gsub('[%z\1-\31\\"]', function(c)
    if c == '"' then return '\\"'
    elseif c == '\\' then return '\\\\'
    elseif c == '\n' then return '\\n'
    elseif c == '\r' then return '\\r'
    elseif c == '\t' then return '\\t'
    else return string.format('\\u%04x', c:byte()) end
  end))
end

local function isArray(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then return false end
    if k > n then n = k end
  end
  return true, n
end

local function toJson(v, depth)
  local tv = type(v)
  if tv == "nil" then return "null"
  elseif tv == "boolean" then return v and "true" or "false"
  elseif tv == "number" then
    if v == math.floor(v) and math.abs(v) < 2^53 then return string.format("%d", v) end
    return tostring(v)
  elseif tv == "string" then return '"' .. jsonEscape(v) .. '"'
  elseif tv == "table" then
    local arr, n = isArray(v)
    if arr then
      local parts = {}
      for i = 1, n do parts[#parts + 1] = toJson(v[i], depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      local keys = {}
      for k in pairs(v) do keys[#keys + 1] = k end
      table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
      local parts = {}
      for _, k in ipairs(keys) do
        parts[#parts + 1] = '"' .. jsonEscape(tostring(k)) .. '":' .. toJson(v[k], depth + 1)
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  else
    error("cannot encode type " .. tv)
  end
end

-- ---------- Lua serializer (same data, addon-ready) ----------

local function luaEscape(s) return string.format("%q", s) end

local function toLua(v, depth)
  local tv = type(v)
  if tv == "nil" then return "nil"
  elseif tv == "boolean" then return v and "true" or "false"
  elseif tv == "number" then
    if v == math.floor(v) and math.abs(v) < 2^53 then return string.format("%d", v) end
    return tostring(v)
  elseif tv == "string" then return luaEscape(v)
  elseif tv == "table" then
    local arr, n = isArray(v)
    local pad = string.rep("  ", depth + 1)
    if arr then
      if n == 0 then return "{}" end
      local parts = {}
      for i = 1, n do parts[#parts + 1] = pad .. toLua(v[i], depth + 1) .. "," end
      return "{\n" .. table.concat(parts, "\n") .. "\n" .. string.rep("  ", depth) .. "}"
    else
      local keys = {}
      for k in pairs(v) do keys[#keys + 1] = k end
      table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
      if #keys == 0 then return "{}" end
      local parts = {}
      for _, k in ipairs(keys) do
        local ks
        if type(k) == "number" then ks = "[" .. k .. "]"
        else ks = '["' .. jsonEscape(tostring(k)) .. '"]' end
        parts[#parts + 1] = pad .. ks .. " = " .. toLua(v[k], depth + 1) .. ","
      end
      return "{\n" .. table.concat(parts, "\n") .. "\n" .. string.rep("  ", depth) .. "}"
    end
  else
    error("cannot serialize type " .. tv)
  end
end

-- ---------- run ----------

local quests = {}
local ids = {}
for id in pairs(questsRaw) do ids[#ids + 1] = id end
table.sort(ids)

local zoneCounts = {}
local unmapped = {}
for _, id in ipairs(ids) do
  local q = convertQuest(id, questsRaw[id])
  quests[id] = q
  if q.areaId then
    zoneCounts[q.areaId] = (zoneCounts[q.areaId] or 0) + 1
    if areaToUiMap[q.areaId] == nil then unmapped[q.areaId] = true end
  end
end

local zones = {}
for areaId, count in pairs(zoneCounts) do
  zones[#zones + 1] = { areaId = areaId, uiMapId = areaToUiMap[areaId], questCount = count }
end
table.sort(zones, function(a, b) return a.areaId < b.areaId end)

local unmappedList = {}
for areaId in pairs(unmapped) do unmappedList[#unmappedList + 1] = areaId end
table.sort(unmappedList)

local function write(path, content)
  local f = assert(io.open(path, "w"))
  f:write(content)
  f:close()
end

write(outdir .. "/quests.json", (function()
  -- JSON objects need string keys: the numeric-ID map must not encode as a
  -- sparse array padded with nulls up to the largest quest ID.
  local asObject = {}
  for id, quest in pairs(quests) do asObject[tostring(id)] = quest end
  return toJson(asObject, 0) .. "\n"
end)())
write(outdir .. "/zones.json", toJson(zones, 0) .. "\n")
local luaData = { version = "1.0.0", quests = quests, zones = zones }
write(outdir .. "/QuestDB.lua",
  "-- Generated by tools/convert.lua from QuestieDB Forever data. Do not edit by hand.\n"
  .. "ForeverQuestsDB = " .. toLua(luaData, 0) .. "\n")
write(outdir .. "/stats.json", toJson({
  questCount = #ids,
  zoneCount = #zones,
  unmappedAreaIds = unmappedList,
  zones = zones,
}, 0) .. "\n")

print(string.format("quests=%d zones=%d unmappedAreas=%d", #ids, #zones, #unmappedList))
if #unmappedList > 0 then
  print("unmapped areaIds: " .. table.concat(unmappedList, ","))
end
