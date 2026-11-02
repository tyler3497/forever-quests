# ForeverDB-only quest dataset

A dataset built **only** from ForeverDB's API. It is kept entirely separate
from the main database in `data/` (QuestieDB / TrinityCore TDB /
NorgannonDB) — nothing here is merged with that data, it is not part of
`manifest.json`, and it is not part of the companion app's download
contract. It exists so ForeverDB's observed names, locations, and chain
links can be compared against the main data without mixing sources.

- Source: ForeverDB API (`https://foreverdb.net/api/v1`)
- Docs: `https://foreverdb.net/developers`
- Auth: `X-API-Key` header (read from the `FOREVERDB_API_KEY` environment
  variable; the key is never stored in this repo)
- Limits: 60 requests/min, 10,000/day per key (the puller stays under both)

## Contents

- `pull.py` — the puller: full quest list (100 per page) plus one detail
  call per quest, resumable from cached responses, then builds `data/`
- `data/quests.json` — 3,862 quests keyed by ID, ForeverDB fields only:
  name, level, required level, side, zone (with UI map ID), starts/ends
  (NPC / object / item names with map locations, labeled seen-in-Forever
  vs Classic data), and chain links
- `data/meta.json` — source, credit, counts, and the API meta response

Pulled 2026-11-02 from client build 1.60.1.70707.

## Coverage note

ForeverDB's `/meta` endpoint counts 6,614 quests, but its quest-list
endpoint returns 3,862. This dataset covers everything the list endpoint
returns; the remaining records counted in meta are not reachable through
that endpoint (at least with no filters). All 3,862 listed quests carry
`knownInForever: true`; 1,071 have Forever as their data source and
2,791 are Classic-sourced records.

## Raw cache

Per-quest raw responses are cached locally while pulling so an
interrupted run resumes without re-spending API budget. The cache is
**not** committed; re-running `pull.py` from a fresh checkout re-fetches
everything (about 3,900 calls, inside one day's limit).

## Credit

<a href="https://foreverdb.net">Data from ForeverDB.net</a> — required by
ForeverDB wherever this data is shown.
