#!/usr/bin/env python3
"""Import the 108 confirmed Zephras Isle quests (TDB sort 16593) into
forever-quests as v1.2.0.

Sources, in priority order:
  - NorgannonDB (zmarotrix/NorgannonDB, GPL-3.0, snapshot 2026-10-20):
    name, level, minLevel, starters, finishers, objectives text and
    structured objectives, prerequisites, next-in-chain, exclusivity,
    races, classes, source item, reputation rewards, fallback item rewards.
  - TrinityCore Forever TDB (release forever-tdb-2026-10-14):
    item, choice, XP and money rewards (same split as v1.1.0: TDB for
    items/money/XP). TDB reputation columns are NOT used.
  - TDB quest_template_addon: fills gaps only (max level, skill, rep
    thresholds, prev/next chain links, breadcrumb) where NorgannonDB
    has nothing.

Zone: areaId 16593 maps to uiMapId 2521 in QuestieDB's Forever zone
tables (reviewed against Forever DBC data).

Usage: python3 tools/import_zephras.py <norgannon_quests.lua>
    <TDB_world.sql> <ids.json>
Writes: data/quests.json, data/zones.json (QuestDB.lua is rebuilt
separately by tools/build_lua.py). Prints import statistics as JSON.
"""

import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from merge_tdb_rewards import extract_tdb_rewards, TUPLE_RE, FIELD_RE, to_int


# --- Minimal Lua table parser (subset used by NorgannonDB's packed file) ---
class LuaParser:
    def __init__(self, text):
        self.s, self.i = text, 0

    def skip(self):
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.s.startswith("--", self.i):
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def parse(self):
        self.skip()
        return self.value()

    def value(self):
        self.skip()
        c = self.s[self.i]
        if c == "{":
            return self.table()
        if c == '"':
            return self.string()
        if c == "'":
            return self.string("'")
        if c == "[":
            if self.s.startswith("[[", self.i):
                end = self.s.find("]]", self.i + 2)
                v = self.s[self.i + 2:end]
                self.i = end + 2
                return v
            self.i += 1
            v = self.value()
            self.skip()
            assert self.s[self.i] == "]", "expected ]"
            self.i += 1
            return ("__bracket__", v)
        m = re.match(r"-?\d+(\.\d+)?", self.s[self.i:])
        if m:
            self.i += len(m.group(0))
            return float(m.group(0)) if "." in m.group(0) else int(m.group(0))
        m = re.match(r"[A-Za-z_]\w*", self.s[self.i:])
        if m:
            self.i += len(m.group(0))
            word = m.group(0)
            if word == "true":
                return True
            if word == "false":
                return False
            if word == "nil":
                return None
            return ("__ident__", word)
        raise ValueError("unexpected char %r at %d" % (c, self.i))

    def string(self, quote='"'):
        assert self.s[self.i] == quote
        self.i += 1
        out = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\" and self.i + 1 < len(self.s):
                nxt = self.s[self.i + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\"}.get(nxt, nxt))
                self.i += 2
            elif c == quote:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
                self.i += 1
        raise ValueError("unterminated string")

    def table(self):
        assert self.s[self.i] == "{"
        self.i += 1
        result, arr = {}, []
        while True:
            self.skip()
            if self.i >= len(self.s):
                raise ValueError("unterminated table")
            if self.s[self.i] == "}":
                self.i += 1
                break
            save = self.i
            try:
                key = self.value()
            except ValueError:
                key = None
            self.skip()
            if key is not None and self.i < len(self.s) and self.s[self.i] == "=":
                self.i += 1
                val = self.value()
                if isinstance(key, tuple) and key[0] == "__bracket__":
                    result[key[1]] = val
                elif isinstance(key, tuple):
                    result[key[1]] = val
                else:
                    result[key] = val
            else:
                self.i = save
                arr.append(self.value())
            self.skip()
            if self.i < len(self.s) and self.s[self.i] in ",;":
                self.i += 1
        if arr and not result:
            return arr
        if result and not arr:
            return result
        merged = dict(result)
        for idx, v in enumerate(arr, 1):
            merged[idx] = v
        return merged


def parse_norgannon(path):
    records = {}
    pat = re.compile(r'^R\((\d+),"(?:\\.|[^"\\])*",\[\[(.*)\]\]\)?\s*$')
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("R("):
                continue
            # Split header: R(id,"name",[[body]])
            m = re.match(r'^R\((\d+),', line)
            if not m:
                continue
            qid = int(m.group(1))
            rest = line[m.end():]
            # name is a double-quoted string
            name_parser = LuaParser(rest)
            name = name_parser.string()
            name_parser.skip()
            if rest[name_parser.i] == ")":
                # Stub record: id + name only, no body table.
                records[qid] = {"name": name, "body": {}}
                continue
            assert rest[name_parser.i] == ",", "expected comma after name"
            name_parser.i += 1
            name_parser.skip()
            assert rest.startswith("[[", name_parser.i)
            end = rest.find("]]", name_parser.i + 2)
            body = rest[name_parser.i + 2:end]
            # The packed body is a table-constructor body (no outer braces);
            # the loader wraps it, so wrap it here before parsing.
            records[qid] = {"name": name, "body": LuaParser("{" + body + "}").parse()}
    return records


def parse_addon_rows(sql, want_ids):
    m = re.search(r"CREATE TABLE `quest_template_addon` \((.*?)\)\s*ENGINE", sql, re.S)
    cols = []
    for ln in m.group(1).splitlines():
        s = ln.strip()
        if s.startswith("PRIMARY KEY") or s.startswith("UNIQUE KEY") or s.startswith("KEY "):
            break
        mm = re.match(r"`([^`]+)`", s)
        if mm:
            cols.append(mm.group(1))
    start = sql.find("INSERT INTO `quest_template_addon` VALUES")
    end = sql.find("UNLOCK TABLES", start)
    region = sql[start:end if end != -1 else len(sql)]
    rows = {}
    for tup in TUPLE_RE.finditer(region):
        fields = FIELD_RE.findall(tup.group(0)[1:-1])
        if len(fields) != len(cols):
            continue
        qid = to_int(fields[0])
        if qid in want_ids:
            rows[qid] = dict(zip(cols, fields))
    return rows


def as_int_list(v):
    if isinstance(v, list):
        return [x for x in v if isinstance(x, int)]
    if isinstance(v, int):
        return [v]
    return []


def main():
    norg_path, world_sql, ids_path = sys.argv[1:4]
    repo = __file__.rsplit("/tools/", 1)[0]
    ids = json.load(open(ids_path))
    norg = parse_norgannon(norg_path)
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
        "addon_prev": 0, "addon_next": 0, "orphan_refs": [],
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
        q = {"id": qid, "name": rec["name"], "areaId": 16593, "zoneOrSort": 16593}
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
            # Fallback only when the TDB has neither fixed nor choice items:
            # NorgannonDB does not distinguish the two, so using its items
            # alongside TDB choice items would list the same items twice.
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

    # Orphan check: chain/prereq references that resolve nowhere.
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

    if not any(z.get("areaId") == 16593 for z in zones):
        zones.append({"areaId": 16593, "questCount": 0, "uiMapId": 2521})
    for z in zones:
        if z.get("areaId") == 16593:
            z["questCount"] = sum(1 for v in quests.values() if v.get("areaId") == 16593)
    json.dump(quests, open(repo + "/data/quests.json", "w"), sort_keys=True, separators=(",", ":"))
    json.dump(zones, open(repo + "/data/zones.json", "w"), indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
