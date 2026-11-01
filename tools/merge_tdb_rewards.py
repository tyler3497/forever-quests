#!/usr/bin/env python3
"""Merge TrinityCore Forever TDB quest rewards into forever-quests.

Source split (per project decision 2026-11-01):
  - reputation rewards: QuestieDB (already in quests.json) -- TDB reputation
    columns are intentionally IGNORED, even for quests that lack a QuestieDB
    reputation entry.
  - item, money and XP rewards: TDB quest_template (advocaite/TrinityCore
    forever branch, release forever-tdb-2026-10-14).

Only quests already present in quests.json are modified. TDB rows for other
quest IDs are counted and reported, not added: the TDB holds every expansion's
quests, so importing all of them would flood a Forever database with
non-Forever quests.

Money/XP representation: the TDB stores XP and money as difficulty columns
plus multipliers (RewardXPDifficulty/RewardMoneyDifficulty), resolved to
final numbers through the client's QuestXP / QuestMoneyReward tables, plus a
flat copper bonus (RewardBonusMoney). Those raw values are stored as-is;
resolving them to exact XP/copper numbers is a future step that needs the
client tables.

Usage: python3 tools/merge_tdb_rewards.py <world-sql> <repo-dir>
Writes: <repo-dir>/data/quests.json, <repo-dir>/data/QuestDB.lua
Prints: merge statistics as JSON.
"""

import json
import re
import sys

TUPLE_RE = re.compile(r"\((?:[^'()]|'(?:\\.|[^'\\])*')*\)")
FIELD_RE = re.compile(r"'(?:\\.|[^'\\])*'|[^,]+")


def parse_create_columns(sql):
    m = re.search(r"CREATE TABLE `quest_template` \((.*?)\)\s*ENGINE", sql, re.S)
    if not m:
        m = re.search(r"CREATE TABLE `quest_template` \((.*?)\)\s*;", sql, re.S)
    cols = []
    for ln in m.group(1).splitlines():
        s = ln.strip()
        if s.startswith("PRIMARY KEY") or s.startswith("UNIQUE KEY") or s.startswith("KEY "):
            break
        mm = re.match(r"`([^`]+)`", s)
        if mm:
            cols.append(mm.group(1))
    return cols


def unquote(field):
    field = field.strip()
    if len(field) >= 2 and field.startswith("'") and field.endswith("'"):
        body = field[1:-1]
        return body.replace("\\'", "'").replace("\\\\", "\\")
    return field


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_tdb_rewards(sql):
    cols = parse_create_columns(sql)
    rewards = {}
    total_rows = 0
    # Slice to the quest_template data region only: from the first INSERT to
    # the UNLOCK TABLES that ends the table's dump. Scanning tuples across
    # the whole region (instead of splitting statements at ';') is required
    # because quest text legitimately contains semicolons.
    start = sql.find("INSERT INTO `quest_template` VALUES")
    end = sql.find("UNLOCK TABLES", start)
    region = sql[start:end if end != -1 else len(sql)]
    for tup in TUPLE_RE.finditer(region):
        fields = FIELD_RE.findall(tup.group(0)[1:-1])
        if len(fields) != len(cols):
            continue
        qid = to_int(fields[0])
        if qid == 0:
            continue
        total_rows += 1
        d = dict(zip(cols, fields))

        def num(name):
            return to_int(d.get(name))

        fixed = []
        for i in range(1, 5):
            item = num(f"RewardItem{i}")
            if item:
                fixed.append({"itemId": item, "amount": num(f"RewardAmount{i}")})
        choice = []
        for i in range(1, 7):
            item = num(f"RewardChoiceItemID{i}")
            if item:
                choice.append({"itemId": item, "amount": num(f"RewardChoiceItemQuantity{i}")})
        xp = None
        if num("RewardXPDifficulty"):
            xp = {"difficulty": num("RewardXPDifficulty"), "multiplier": num("RewardXPMultiplier") or 1}
        money = None
        if num("RewardMoneyDifficulty") or num("RewardBonusMoney"):
            money = {
                "difficulty": num("RewardMoneyDifficulty"),
                "multiplier": num("RewardMoneyMultiplier") or 1,
                "bonus": num("RewardBonusMoney"),
            }
        rewards[qid] = {"items": fixed, "choice": choice, "xp": xp, "money": money}
    return rewards, total_rows


def lua_escape(s):
    out = []
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32:
            out.append("\\%03d" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def to_lua(v, depth):
    pad = "  " * (depth + 1)
    close = "  " * depth
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return lua_escape(v)
    if isinstance(v, list):
        if not v:
            return "{}"
        parts = [pad + to_lua(x, depth + 1) + "," for x in v]
        return "{\n" + "\n".join(parts) + "\n" + close + "}"
    if isinstance(v, dict):
        if not v:
            return "{}"
        parts = []
        for k in sorted(v, key=str):
            ks = "[%d]" % k if isinstance(k, int) else "[" + lua_escape(str(k)) + "]"
            parts.append(pad + ks + " = " + to_lua(v[k], depth + 1) + ",")
        return "{\n" + "\n".join(parts) + "\n" + close + "}"
    raise TypeError(type(v))


def main():
    world_sql, repo = sys.argv[1], sys.argv[2]
    with open(world_sql, encoding="utf-8", errors="replace") as f:
        sql = f.read()
    tdb, total_rows = extract_tdb_rewards(sql)

    quests_path = repo + "/data/quests.json"
    with open(quests_path) as f:
        quests = json.load(f)

    stats = {
        "tdb_rows": total_rows,
        "tdb_quest_ids": len(tdb),
        "merged": 0,
        "with_items": 0,
        "with_choice": 0,
        "with_xp": 0,
        "with_money": 0,
        "no_tdb_row": 0,
        "tdb_only_ids": 0,
        "tdb_only_ge_90000": 0,
        "fixed_amount_zero": 0,
        "choice_amount_zero": 0,
    }
    our_ids = {int(k) for k in quests}
    for qid in tdb:
        if qid not in our_ids:
            stats["tdb_only_ids"] += 1
            if qid >= 90000:
                stats["tdb_only_ge_90000"] += 1

    for key in sorted(quests, key=lambda k: int(k)):
        qid = int(key)
        q = quests[key]
        row = tdb.get(qid)
        if row is None:
            stats["no_tdb_row"] += 1
            continue
        stats["merged"] += 1
        rewards = q.get("rewards") or {}
        sources = {}
        if rewards.get("reputation"):
            sources["reputation"] = "questiedb"
        if row["items"]:
            rewards["items"] = row["items"]
            sources["items"] = "tdb"
            stats["with_items"] += 1
            stats["fixed_amount_zero"] += sum(1 for it in row["items"] if it["amount"] == 0)
        if row["choice"]:
            rewards["choice"] = row["choice"]
            sources["choice"] = "tdb"
            stats["with_choice"] += 1
            stats["choice_amount_zero"] += sum(1 for it in row["choice"] if it["amount"] == 0)
        if row["xp"]:
            rewards["xp"] = row["xp"]
            sources["xp"] = "tdb"
            stats["with_xp"] += 1
        if row["money"]:
            rewards["money"] = row["money"]
            sources["money"] = "tdb"
            stats["with_money"] += 1
        if rewards:
            q["rewards"] = rewards
        if sources:
            q["rewardSources"] = sources

    with open(quests_path, "w") as f:
        json.dump(quests, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")

    zones = json.load(open(repo + "/data/zones.json"))
    lua_quests = {int(k): v for k, v in quests.items()}
    lua_data = {"version": "1.1.0", "quests": lua_quests, "zones": zones}
    with open(repo + "/data/QuestDB.lua", "w") as f:
        f.write(
            "-- Generated by tools/merge_tdb_rewards.py from QuestieDB + TDB data. "
            "Do not edit by hand.\n"
        )
        f.write("ForeverQuestsDB = " + to_lua(lua_data, 0) + "\n")

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
