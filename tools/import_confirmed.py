#!/usr/bin/env python3
"""Import the remaining confirmed-Forever quests (TDB + NorgannonDB,
Expansion = -2, minus the Zephras Isle group already imported) into
forever-quests as v1.3.0.

Same source rules as tools/import_zephras.py:
  - NorgannonDB: name, level, starters, finishers, objectives,
    prerequisites, chains, races, classes, reputation, fallback items.
  - TDB: item, choice, XP, money rewards (reputation NOT used).
  - TDB quest_template_addon: gap-fill only (max level, skill, rep
    thresholds, prev/next chain links, breadcrumb).

Zone handling (generalized from the Zephras importer):
  - zoneOrSort comes from the NorgannonDB record body, falling back to
    the TDB QuestSortID passed via the optional sorts file.
  - Positive zoneOrSort = areaId; uiMapId from QuestieDB's Forever zone
    mapping, else the generic mapping, else areaId-only (no uiMapId key),
    matching the existing unmapped areas 25 and 1417.
  - Negative zoneOrSort = sortId (category, like the existing sort quests).
  - zones.json quest counts are recomputed from quests.json for every
    area; new areas are appended.

Usage: python3 tools/import_confirmed.py <norgannon_quests.lua>
    <TDB_world.sql> <ids.json> [sorts.json] [forever_map.lua] [generic_map.lua]
    [--norgannon-only]
Writes: data/quests.json, data/zones.json (QuestDB.lua is rebuilt
separately by tools/build_lua.py). Prints import statistics as JSON.

With --norgannon-only, quests are built purely from NorgannonDB records
(no TDB rewards, no TDB addon-table gap-fill). Use it for quests that
are referenced by confirmed quests but are not themselves TDB-confirmed
(the 94493 precedent): a single Forever source, no retail data mixed in.
"""

import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from merge_tdb_rewards import extract_tdb_rewards, TUPLE_RE, FIELD_RE, to_int
from import_zephras import parse_norgannon, parse_addon_rows, as_int_list


def load_map(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    return {int(a): int(u) for a, u in re.findall(r"\[(\d+)\]\s*=\s*(\d+)", txt)}


def main():
    norg_path, world_sql, ids_path = sys.argv[1:4]
    sorts_path = sys.argv[4] if len(sys.argv) > 4 else None
    forever_map_path = sys.argv[5] if len(sys.argv) > 5 else None
    generic_map_path = sys.argv[6] if len(sys.argv) > 6 else None
    repo = __file__.rsplit("/tools/", 1)[0]
    ids = json.load(open(ids_path))
    sorts = {}
    if sorts_path:
        raw = json.load(open(sorts_path))
        sorts = {int(k): v for k, v in raw.items()}
    fmap = load_map(forever_map_path) if forever_map_path else {}
    gmap = load_map(generic_map_path) if generic_map_path else {}
    norg_only = "--norgannon-only" in sys.argv
    norg = parse_norgannon(norg_path)
    tdb, addon = {}, {}
    if not norg_only:
        with open(world_sql, encoding="utf-8", errors="replace") as f:
            sql = f.read()
        tdb, _ = extract_tdb_rewards(sql)
        addon = parse_addon_rows(sql, set(ids))

    quests = json.load(open(repo + "/data/quests.json"))
    zones = json.load(open(repo + "/data/zones.json"))

    stats = {
        "imported": 0, "already_present": 0, "missing_norgannon": 0,
        "tdb_items": 0, "norgannon_items_fallback": 0, "tdb_choice": 0,
        "tdb_xp": 0, "tdb_money": 0, "norgannon_rep": 0,
        "addon_skill": 0, "addon_rep": 0, "addon_maxlevel": 0,
        "addon_prev": 0, "addon_next": 0,
        "new_areas": [], "unmapped_areas": [], "sort_only": 0,
        "orphan_refs": [],
    }
    for qid in ids:
        if str(qid) in quests:
            stats["already_present"] += 1
            continue
        rec = norg.get(qid)
        if not rec:
            stats["missing_norgannon"] += 1
            continue
        b = rec["body"]
        q = {"id": qid, "name": rec["name"]}
        zos = b.get("zoneOrSort") if isinstance(b.get("zoneOrSort"), int) else sorts.get(qid)
        if isinstance(zos, int) and zos != 0:
            q["zoneOrSort"] = zos
            if zos > 0:
                q["areaId"] = zos
            else:
                q["sortId"] = zos
                stats["sort_only"] += 1
        if isinstance(b.get("level"), int):
            q["questLevel"] = b["level"]
        if isinstance(b.get("minLevel"), int):
            q["requiredLevel"] = b["minLevel"]
        for side, key in (("startedBy", "starters"), ("finishedBy", "finishers")):
            src = b.get(key)
            if isinstance(src, dict):
                out = {}
                for kind in ("npcs", "objects", "items"):
                    if src.get(kind):
                        out[kind] = as_int_list(src[kind])
                if out:
                    q[side] = out
        text = b.get("text")
        if isinstance(text, dict) and text.get("objectives"):
            q["objectivesText"] = [t for t in text["objectives"] if isinstance(t, str)]
        obj = b.get("objectives")
        if isinstance(obj, dict):
            groups = {}
            if obj.get("npcs"):
                groups["creatures"] = [[e["id"]] for e in obj["npcs"]
                                       if isinstance(e, dict) and isinstance(e.get("id"), int)]
            if obj.get("items"):
                groups["items"] = [[e["id"]] for e in obj["items"]
                                   if isinstance(e, dict) and isinstance(e.get("id"), int)]
            if obj.get("objects"):
                groups["objects"] = [[e["id"]] for e in obj["objects"]
                                     if isinstance(e, dict) and isinstance(e.get("id"), int)]
            if groups:
                q["objectives"] = groups
            explore = obj.get("explore")
            if isinstance(explore, dict) and explore.get("spawns"):
                zones_out = []
                for zid, coords in explore["spawns"].items():
                    if isinstance(zid, int) and isinstance(coords, list):
                        zones_out.append({"coords": [[c[0], c[1]] for c in coords
                                                     if isinstance(c, list) and len(c) >= 2],
                                          "zoneId": zid})
                if zones_out:
                    q["triggerEnd"] = {"text": "Explore", "zones": zones_out}
        pre = b.get("prerequisites")
        if isinstance(pre, dict):
            if pre.get("all"):
                q["preQuestSingle"] = as_int_list(pre["all"])
            if pre.get("any"):
                q["preQuestGroup"] = as_int_list(pre["any"])
        if b.get("nextQuestInChain") is not None:
            q["nextQuestInChain"] = b["nextQuestInChain"]
        if b.get("exclusiveTo"):
            q["exclusiveTo"] = as_int_list(b["exclusiveTo"])
        if isinstance(b.get("races"), int):
            q["requiredRaces"] = b["races"]
        if isinstance(b.get("classes"), int):
            q["requiredClasses"] = b["classes"]
        if isinstance(b.get("sourceItem"), int):
            q["sourceItemId"] = b["sourceItem"]
        if isinstance(b.get("availableUntilCompleted"), int):
            q["availableUntilCompleted"] = b["availableUntilCompleted"]
        if isinstance(b.get("availableStartingWith"), int):
            q["availableStartingWith"] = b["availableStartingWith"]

        # TDB addon-table gaps (only where NorgannonDB has nothing).
        a = addon.get(qid, {})
        if to_int(a.get("MaxLevel")) > 0:
            q["requiredMaxLevel"] = to_int(a.get("MaxLevel"))
            stats["addon_maxlevel"] += 1
        if to_int(a.get("RequiredSkillID")) > 0:
            q["requiredSkill"] = {"id": to_int(a.get("RequiredSkillID")),
                                  "value": to_int(a.get("RequiredSkillPoints"))}
            stats["addon_skill"] += 1
        if to_int(a.get("RequiredMinRepFaction")) > 0:
            q["requiredMinRep"] = {"id": to_int(a.get("RequiredMinRepFaction")),
                                   "value": to_int(a.get("RequiredMinRepValue"))}
            stats["addon_rep"] += 1
        if to_int(a.get("RequiredMaxRepFaction")) > 0:
            q["requiredMaxRep"] = {"id": to_int(a.get("RequiredMaxRepFaction")),
                                   "value": to_int(a.get("RequiredMaxRepValue"))}
            stats["addon_rep"] += 1
        if to_int(a.get("PrevQuestID")) > 0 and "preQuestSingle" not in q:
            q["preQuestSingle"] = [to_int(a.get("PrevQuestID"))]
            stats["addon_prev"] += 1
        if to_int(a.get("NextQuestID")) > 0 and "nextQuestInChain" not in q:
            q["nextQuestInChain"] = to_int(a.get("NextQuestID"))
            stats["addon_next"] += 1
        if to_int(a.get("BreadcrumbForQuestId")) > 0:
            q["breadcrumbForQuestId"] = to_int(a.get("BreadcrumbForQuestId"))

        # Rewards: TDB items/money/XP, NorgannonDB reputation (+ item fallback).
        rewards, sources = {}, {}
        t = tdb.get(qid, {})
        if t.get("items"):
            rewards["items"] = t["items"]
            sources["items"] = "tdb"
            stats["tdb_items"] += 1
        elif not t.get("choice") and isinstance(b.get("rewards"), dict) and b["rewards"].get("items"):
            rewards["items"] = [{"itemId": i, "amount": 1} for i in b["rewards"]["items"]
                                if isinstance(i, int)]
            sources["items"] = "norgannondb"
            stats["norgannon_items_fallback"] += 1
        if t.get("choice"):
            rewards["choice"] = t["choice"]
            sources["choice"] = "tdb"
            stats["tdb_choice"] += 1
        if t.get("xp"):
            rewards["xp"] = t["xp"]
            sources["xp"] = "tdb"
            stats["tdb_xp"] += 1
        if t.get("money"):
            rewards["money"] = t["money"]
            sources["money"] = "tdb"
            stats["tdb_money"] += 1
        if isinstance(b.get("rewards"), dict) and b["rewards"].get("reputation"):
            rep = [{"factionId": r[0], "amount": r[1]} for r in b["rewards"]["reputation"]
                   if isinstance(r, list) and len(r) >= 2]
            if rep:
                rewards["reputation"] = rep
                sources["reputation"] = "norgannondb"
                stats["norgannon_rep"] += 1
        if rewards:
            q["rewards"] = rewards
        if sources:
            q["rewardSources"] = sources
        quests[str(qid)] = q
        stats["imported"] += 1

    # Orphan check over the imported set.
    all_ids = {int(k) for k in quests}
    for qid in ids:
        q = quests.get(str(qid))
        if not q:
            continue
        refs = []
        refs += q.get("preQuestSingle", []) + q.get("preQuestGroup", [])
        refs += q.get("exclusiveTo", [])
        if q.get("nextQuestInChain"):
            refs.append(q["nextQuestInChain"])
        for r in refs:
            if r not in all_ids:
                stats["orphan_refs"].append({"quest": qid, "ref": r})

    # Zones: recompute every count from quests.json; append new areas.
    counts = {}
    for v in quests.values():
        if isinstance(v.get("areaId"), int):
            counts[v["areaId"]] = counts.get(v["areaId"], 0) + 1
    existing = {z["areaId"]: z for z in zones}
    for areaId, cnt in counts.items():
        if areaId in existing:
            existing[areaId]["questCount"] = cnt
        else:
            entry = {"areaId": areaId, "questCount": cnt}
            ui = fmap.get(areaId) or gmap.get(areaId)
            if ui:
                entry["uiMapId"] = ui
            else:
                stats["unmapped_areas"].append(areaId)
            zones.append(entry)
            stats["new_areas"].append(areaId)
    json.dump(quests, open(repo + "/data/quests.json", "w"), sort_keys=True, separators=(",", ":"))
    json.dump(zones, open(repo + "/data/zones.json", "w"), indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
