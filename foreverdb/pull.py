#!/usr/bin/env python3
"""Pull ForeverDB quest data into a SEPARATE, ForeverDB-only dataset.

This dataset is intentionally kept apart from the forever-quests database
(QuestieDB / TrinityCore TDB / NorgannonDB). Nothing here is merged with
other sources, and nothing here is written into those repos.

Usage (key is never stored in this file or in the repo):
    FOREVERDB_API_KEY=... python3 pull.py probe   # meta + 1 list page + 3 details
    FOREVERDB_API_KEY=... python3 pull.py full    # full list + all details, resumable
    FOREVERDB_API_KEY=... python3 pull.py build   # rebuild data/ from raw/ cache only

Limits (per ForeverDB docs): 60 requests/min, 10,000/day per key.
The script sleeps ~1.1s between calls (~54/min) and stops before 9,500
calls in a single run. It honors 429 Retry-After. Raw responses are cached
under raw/ so an interrupted run resumes without re-spending budget.

Outputs:
    raw/meta.json, raw/list_page_<offset>.json, raw/quest_<id>.json
    data/quests.json  (keyed by quest id, ForeverDB fields only)
    data/meta.json    (source, credit, counts, build)
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = "https://foreverdb.net/api/v1"
ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
KEY = os.environ.get("FOREVERDB_API_KEY", "")
DAILY_CAP = 9500
SLEEP = 1.1

calls = [0]
last = [0.0]


def call(path):
    """GET one API path via curl. Returns parsed JSON. Counts every attempt.

    curl is used instead of urllib: urllib's chunked reader raises
    IncompleteRead on some ForeverDB responses even though the full body
    arrived (quest 1172 is exactly 1332 bytes and parses fine via curl).
    Retries transient failures (429 with Retry-After, 5xx, curl errors,
    timeouts, bad JSON) up to 3 times with backoff.
    """
    for attempt in range(4):
        if calls[0] >= DAILY_CAP:
            raise SystemExit(f"daily cap reached ({DAILY_CAP} calls); stopping")
        wait = SLEEP - (time.time() - last[0])
        if wait > 0:
            time.sleep(wait)
        headers_file = ROOT / ".headers.tmp"
        try:
            calls[0] += 1
            proc = subprocess.run(
                [
                    "curl", "-sS",
                    "-D", str(headers_file),
                    "-H", f"X-API-Key: {KEY}",
                    "-H", "User-Agent: curl/8.5.0",
                    "-w", "\n__CODE__:%{http_code}",
                    BASE + path,
                ],
                capture_output=True, timeout=90,
            )
            last[0] = time.time()
            out = proc.stdout.decode("utf-8", "replace")
            body, _, code = out.rpartition("\n__CODE__:")
            code = code.strip()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"curl exit {proc.returncode}: {proc.stderr.decode()[:200]}"
                )
            if code == "429":
                retry_after = None
                try:
                    m = re.search(
                        r"Retry-After:\s*(\d+)", headers_file.read_text(), re.I
                    )
                    retry_after = float(m.group(1)) if m else None
                except OSError:
                    pass
                pause = (retry_after + 5) if retry_after else 65
                print(f"429 on {path}; sleeping {pause}s (attempt {attempt})", flush=True)
                time.sleep(pause)
                continue
            if code.startswith("5") and attempt < 3:
                pause = 10 * (2**attempt)
                print(f"HTTP {code} on {path}; retrying in {pause}s", flush=True)
                time.sleep(pause)
                continue
            if code != "200":
                raise RuntimeError(f"HTTP {code} on {path}: {body[:200]}")
            return json.loads(body)
        except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as e:
            last[0] = time.time()
            if attempt < 3:
                pause = 5 * (2**attempt)
                print(f"transient error on {path} ({e}); retrying in {pause}s", flush=True)
                time.sleep(pause)
                continue
            raise
    raise SystemExit(f"gave up on {path} after retries")


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    tmp.replace(path)


def list_all():
    """Fetch every quest-list page (limit=100), resuming from cache."""
    pages = []
    offset = 0
    total = None
    while True:
        cached = RAW / f"list_page_{offset}.json"
        if cached.exists():
            page = json.loads(cached.read_text())
        else:
            page = call(f"/quests?limit=100&offset={offset}")
            save(cached, page)
        pages.append(page)
        data = page.get("data", [])
        meta = page.get("meta", {}) or {}
        if total is None:
            total = meta.get("total")
        if not data or len(data) < 100:
            break
        offset += len(data)
        if total is not None and offset >= total:
            break
    ids = []
    for page in pages:
        for q in page.get("data", []):
            qid = q.get("id")
            if qid is not None and qid not in ids:
                ids.append(qid)
    return ids, total


def build():
    """Rebuild data/quests.json + data/meta.json from the raw detail cache."""
    quests = {}
    for f in sorted(RAW.glob("quest_*.json")):
        obj = json.loads(f.read_text())
        d = obj.get("data", obj)
        qid = d.get("id")
        if qid is not None:
            quests[str(qid)] = d
    meta_obj = {}
    mf = RAW / "meta.json"
    if mf.exists():
        meta_obj = json.loads(mf.read_text())
    DATA.mkdir(parents=True, exist_ok=True)
    save(DATA / "quests.json", quests)
    save(
        DATA / "meta.json",
        {
            "source": "ForeverDB",
            "source_url": "https://foreverdb.net",
            "credit": "Data from ForeverDB.net",
            "api": "https://foreverdb.net/api/v1",
            "api_meta": meta_obj.get("data", meta_obj),
            "quest_count": len(quests),
            "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "ForeverDB-only dataset. Not merged with QuestieDB, TDB or NorgannonDB data.",
        },
    )
    return len(quests)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if not KEY and mode != "build":
        raise SystemExit("FOREVERDB_API_KEY is not set")
    RAW.mkdir(parents=True, exist_ok=True)
    if mode == "build":
        print(json.dumps({"built": build()}))
        return
    if mode == "probe":
        meta = call("/meta")
        save(RAW / "meta.json", meta)
        page = call("/quests?limit=100&offset=0")
        save(RAW / "list_page_0.json", page)
        data = page.get("data", [])
        samples = []
        for q in data[:3]:
            det = call(f"/quests/{q['id']}")
            save(RAW / f"quest_{q['id']}.json", det)
            d = det.get("data", det)
            samples.append(
                {
                    "id": d.get("id"),
                    "keys": sorted(d.keys()),
                    "name": d.get("name"),
                    "level": d.get("level"),
                    "zone": d.get("zone"),
                }
            )
        print(
            json.dumps(
                {
                    "calls": calls[0],
                    "meta": meta.get("data", meta),
                    "list_meta": page.get("meta"),
                    "first_page_count": len(data),
                    "samples": samples,
                },
                indent=2,
            )
        )
        return
    if mode == "full":
        meta = call("/meta")
        save(RAW / "meta.json", meta)
        ids, total = list_all()
        print(f"list done: {len(ids)} ids (meta total={total}); calls={calls[0]}", flush=True)
        done = 0
        for qid in ids:
            cached = RAW / f"quest_{qid}.json"
            if cached.exists():
                done += 1
                continue
            det = call(f"/quests/{qid}")
            save(cached, det)
            done += 1
            if done % 500 == 0:
                print(f"details: {done}/{len(ids)} calls={calls[0]}", flush=True)
        n = build()
        print(json.dumps({"calls": calls[0], "ids": len(ids), "built": n}))
        return
    raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            (ROOT / ".headers.tmp").unlink()
        except OSError:
            pass
