# forever-quests

Quest data for World of Warcraft Forever, kept separate from any addon that
uses it, so the data and the addon can each be updated without touching the
other. The companion app (Tyler's WoW Tools) downloads updates from here.

## Status

- **Version 1.1.0** — 4,244 quests across 91 zones, with rewards merged
  (see below).
- **Not yet verified against the live Forever client.** The source data is
  QuestieDB's Forever dataset plus TrinityCore's Forever world database
  (see Provenance), but no in-game cross-check has run yet — Forever
  launches November 4, 2026. Treat quest contents as curated, not as
  confirmed live data, until that check happens.

## What is in here

- `data/quests.json` — the canonical database. One object keyed by quest ID
  (as a string, e.g. `"7"`).
- `data/zones.json` — zones that contain quests: area ID, UI map ID, and
  quest count. Zone *names* are intentionally not stored here; the addon
  resolves them at runtime with `C_Map.GetMapInfo(uiMapId).name`, which is
  always locale-correct.
- `data/QuestDB.lua` — the same data as a Lua table
  (`ForeverQuestsDB = { version, quests, zones }`), ready to drop into an
  addon folder and load from its `.toc`. This is the file the companion
  app installs.
- `manifest.json` — the consumption contract: version, source, counts,
  and SHA-256 checksums for every data file.
- `tools/convert.lua` — the converter that builds the data files from
  QuestieDB sources, so a refresh is a re-run, not a hand edit.

## Quest record format

| Field | Meaning |
| --- | --- |
| `id`, `name` | Quest ID and title |
| `areaId` | AreaTable zone ID, when the quest belongs to a zone |
| `sortId` | QuestSort category ID, when it belongs to a sort (class, profession, …) instead of a zone |
| `requiredLevel`, `questLevel`, `requiredMaxLevel` | Level requirements |
| `requiredRaces`, `requiredClasses` | Bitmasks (0 / absent = unrestricted in this source) |
| `requiredSkill`, `requiredMinRep`, `requiredMaxRep` | `{ id, value }` pairs |
| `requiredRanks` | `[{ id, value }]` profession-rank alternatives |
| `requiredSpell`, `requiredSpecialization` | Spell / spec gate |
| `sourceItemId`, `requiredSourceItems` | Item given by / needed for the quest |
| `preQuestGroup`, `preQuestSingle` | Prerequisites (all of / one of) |
| `childQuests`, `inGroupWith`, `exclusiveTo` | Chain / group / exclusivity links |
| `nextQuestInChain`, `parentQuest`, `breadcrumbForQuestId`, `breadcrumbs`, `availableUntilCompleted`, `availableStartingWith`, `disabledByQuest` | Chain and availability links |
| `questFlags`, `specialFlags` | Quest flag bitmasks |
| `startedBy`, `finishedBy` | `{ npcs: [...], objects: [...], items: [...] }` — IDs only, no names (see Gaps) |
| `objectivesText` | Objective description lines |
| `objectives` | `{ creatures, objects, items, reputation, killCredits, spells }` — raw rows from the source |
| `triggerEnd` | `{ text, zones: [{ zoneId, coords: [[x, y], …] }] }` for explore-style objectives |
| `extraObjectives` | Hidden-objective rows, raw from the source |
| `rewards.reputation` | `[{ factionId, amount }]` — from QuestieDB |
| `rewards.items` | `[{ itemId, amount }]` fixed item rewards — from the TDB |
| `rewards.choice` | `[{ itemId, amount }]` pick-one item rewards — from the TDB |
| `rewards.xp` | `{ difficulty, multiplier }` — from the TDB (see below) |
| `rewards.money` | `{ difficulty, multiplier, bonus }` — from the TDB (see below) |
| `rewardSources` | Which source each reward category came from (`questiedb` / `tdb`) |

XP and money are stored the way the TDB stores them: a difficulty column
plus a multiplier, resolved to final numbers through the client's QuestXP
/ QuestMoneyReward tables, plus a flat copper bonus (`money.bonus`, e.g.
5,400 for quest 444) that needs no lookup. Converting difficulty +
multiplier to exact XP/copper numbers needs those client tables and is a
future step — the raw values are recorded faithfully in the meantime.
TDB reputation columns are intentionally **not** used: reputation comes
from QuestieDB only, per the project's source split.

## Known gaps (not invented, not hidden)

- **XP/money difficulty values are unresolved.** `rewards.xp` and
  `rewards.money` carry the TDB's difficulty + multiplier, not final
  XP/copper numbers. Only `money.bonus` is directly usable copper.
- **TDB reputation is unused by design** (see above). Quests with no
  QuestieDB reputation entry have no reputation reward here, even if the
  TDB has one.
- **TDB-only quests are not imported.** The TDB holds 48,801 quest rows
  across all expansions; 44,557 of them are not in this database, including
  2,510 with IDs ≥ 90000 (the range new Forever quests use). Importing all
  of them would flood a Forever database with non-Forever quests, so v1.1.0
  merges TDB rewards only into the existing 4,244 quests. Deciding which
  TDB-only quests are genuinely Forever is the next data question.
- **Starter/finisher names are not included** — only NPC/object/item IDs.
  A future `data/npcs.json` name map (from QuestieDB's Forever NPC data)
  would fill this in.
- **2 area IDs have no UI map mapping** in QuestieDB's zone tables, so
  their quests carry `areaId` but no `uiMapId`: area 25 (15 quests) and
  area 1417 (10 quests). Those quests are still in `quests.json`.
- **1 quest has neither a zone nor a sort** in the source data.
- **983 quests belong to a sort category** (class/profession/…) rather
  than a zone; they are in `quests.json` with `sortId` set and do not
  appear in `zones.json`.

## How the companion app consumes this (contract)

1. Fetch `manifest.json` (raw from `main`, or from a release).
2. Compare `dataVersion` with the installed version.
3. If newer, download `data/QuestDB.lua`, verify its SHA-256 against the
   manifest, and write it into the quest addon's folder (the addon loads
   it from its `.toc`).
4. Record the installed `dataVersion`.

The quest addon itself and the companion download feature are separate
next steps; this repo only has to keep the contract above stable.

## Regenerating

```sh
# Pin a QuestieDB commit, then fetch its three source files:
#   data/Forever/foreverQuestDB.lua
#   support/Forever/Zones/areaIdToUiMapId.lua
#   support/Zones/areaIdToUiMapId.lua
lua5.1 tools/convert.lua <questDB.lua> <foreverArea.lua> <genericArea.lua> data

# Then merge TDB rewards (QuestieDB rep kept, TDB items/money/XP added):
python3 tools/merge_tdb_rewards.py <TDB_full_world_forever_*.sql> .
```

Then rebuild `manifest.json` with fresh checksums and bump `dataVersion`.

## Provenance and license

Derived from [QuestieDB](https://github.com/Questie/QuestieDB) (`data/Forever`),
itself derived from [Questie](https://github.com/Questie/Questie). Quest
records follow QuestieDB's quest schema (36 fields); the converter reads
the field map from the source file itself rather than a hardcoded copy.
Zone mappings come from QuestieDB's Forever zone tables (reviewed against
Forever DBC data through build 1.60.1.70291) with the generic tables as
fallback.

Reward data (v1.1.0) comes from the TrinityCore Forever world database:
[advocaite/TrinityCore](https://github.com/advocaite/TrinityCore) (`forever`
branch), release `forever-tdb-2026-10-14`
(`TDB_full_forever_2026_10_14.7z`, SHA-256
`373cdca7963927d4d67933032b4b858a811eae0af960d4de4ff19833a88d4f41`),
built from TrinityCore TDB 1210.26091 plus the branch's updates and custom
files, with the world converted from VMaNGOS plus Zephras Isle, other
Forever content, and packet-sniff imports. Only the item, money, and XP
columns of its `quest_template` are used; reputation stays QuestieDB-only.

This repo is licensed under the **GNU General Public License v3.0**
(see `LICENSE.md`), matching QuestieDB's license for this derived data.
