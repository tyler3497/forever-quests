# forever-quests

Quest data for World of Warcraft Forever, kept separate from any addon that
uses it, so the data and the addon can each be updated without touching the
other. The companion app (Tyler's WoW Tools) downloads updates from here.

## Status

- **Version 1.0.0** — 4,244 quests across 91 zones.
- **Not yet verified against the live Forever client.** The source data is
  QuestieDB's Forever dataset (see Provenance), but no in-game cross-check
  has run yet — Forever launches November 4, 2026. Treat quest contents as
  QuestieDB-curated, not as confirmed live data, until that check happens.

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
| `rewards.reputation` | `[{ factionId, amount }]` |

## Known gaps (not invented, not hidden)

- **Item and money rewards are not in this data.** QuestieDB quest records
  carry reputation rewards only. Item/money rewards live in the live quest
  offer dialog, not in any quest database we have access to. Options for a
  later version: record them in-game from offer dialogs, or source them
  from Wowhead (no public quest API; scraping is fragile). XP rewards are
  level-formulaic, not per-quest, and are likewise absent.
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

This repo is licensed under the **GNU General Public License v3.0**
(see `LICENSE.md`), matching QuestieDB's license for this derived data.
