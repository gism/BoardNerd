"""Dump the Kilter Board (new app) climb catalogue into a local SQLite file.

Usage:
    python kilter_dump.py probe              # counts per product + which paging params work
    python kilter_dump.py dump [kilter.db]   # download the full catalogue into SQLite
    python kilter_dump.py curated [out.db]   # just the curated set (fast)

Credentials come from KILTER_EMAIL / KILTER_PASSWORD, or are prompted for.
Only the Python standard library is used.
"""
import getpass
import json
import os
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://portal.kiltergrips.com/api"
TOKEN_URL = "https://idp.kiltergrips.com/realms/kilter/protocol/openid-connect/token"
EDGES = "/climbs/climbdetails/productName/edges"
# Every board the catalogue endpoint serves (counts in API.md).
PRODUCTS = ["Kilter Board Original", "Kilter Board Homewall", "JUUL", "Spire", "UP Board"]
BOX = {"edgeLeft": -1000, "edgeRight": 1000, "edgeBottom": -1000, "edgeTop": 1000}
PAGE_SIZE = 5000

# Paging candidates: (where the params go, index param, size param, index of page 2 relative to size).
# "page" style advances by 1, "offset" style advances by the page size.
# body offset/limit is the one the server honours (probed Oct 2026); the rest are fallbacks.
SCHEMES = [
    ("body", "offset", "limit", "offset"),
    ("body", "page", "pageSize", "page"),
    ("query", "page", "pageSize", "page"),
    ("body", "page", "size", "page"),
    ("query", "page", "size", "page"),
    ("query", "offset", "limit", "offset"),
    ("body", "page", "limit", "page"),
    ("body", "skip", "take", "offset"),
]


class Session:
    def __init__(self):
        email = os.environ.get("KILTER_EMAIL") or input("Kilter email: ")
        password = os.environ.get("KILTER_PASSWORD") or getpass.getpass("Kilter password: ")
        self._set(self._token({"grant_type": "password", "username": email, "password": password}))

    def _token(self, form):
        form = {"client_id": "kilter", "scope": "openid offline_access", **form}
        req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            sys.exit(f"Login failed ({e.code}): {e.read()[:300]!r}")

    def _set(self, tok):
        self.access = tok["access_token"]
        self.refresh = tok.get("refresh_token")
        self.expires = time.time() + tok.get("expires_in", 300) - 30

    def get(self, path, params=None, timeout=120):
        return self.request("GET", path, params, None, timeout)

    def post(self, path, body, params=None, timeout=120):
        return self.request("POST", path, params, body, timeout)

    def request(self, method, path, params=None, body=None, timeout=120):
        if time.time() > self.expires and self.refresh:
            self._set(self._token({"grant_type": "refresh_token", "refresh_token": self.refresh}))
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": f"Bearer {self.access}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:500].decode(errors="replace")
        except (socket.timeout, TimeoutError):
            return 0, "timeout"


def split(payload):
    """Return (climbs, stats) from any response envelope."""
    if isinstance(payload, list):
        return payload, []
    if isinstance(payload, dict):
        climbs = payload.get("climbs") or payload.get("content") or payload.get("data") or []
        return climbs, payload.get("climbStats") or []
    return [], []


def page_request(s, product, scheme, index, size, timeout=60):
    where, idx, sz, _ = scheme
    body = {"productName": product, **BOX}
    paging = {idx: index, sz: size}
    if where == "body":
        return s.post(EDGES, {**body, **paging}, timeout=timeout)
    return s.post(EDGES, body, paging, timeout=timeout)


def detect_scheme(s, product, verbose=False):
    """First scheme that returns exactly 3 items, and different ones on page 2."""
    for scheme in SCHEMES:
        nxt = 1 if scheme[3] == "page" else 3
        st1, p1 = page_request(s, product, scheme, 0, 3, timeout=30)
        st2, p2 = page_request(s, product, scheme, nxt, 3, timeout=30)
        a, b = split(p1)[0], split(p2)[0]
        ok = st1 == 200 and st2 == 200 and len(a) == 3 and len(b) == 3 \
            and a[0].get("climbUuid") != b[0].get("climbUuid")
        if verbose:
            print(f"  {scheme[0]:5} {scheme[1]}/{scheme[2]:8} -> [{st1}] {len(a) if st1 == 200 else a!r:>8} "
                  f"items, page2 [{st2}] {len(b) if st2 == 200 else b!r}  {'OK' if ok else ''}")
        if ok:
            return scheme
    return None


def count(s, product):
    st, n = s.post(EDGES + "/count", {"productName": product, **BOX})
    return n if st == 200 and isinstance(n, int) else None


def probe(s):
    for product in PRODUCTS:
        print(f"{product}: {count(s, product)} climbs")
    print("\nPaging test on Kilter Board Original:")
    scheme = detect_scheme(s, "Kilter Board Original", verbose=True)
    print(f"\nWorking scheme: {scheme}")
    if scheme:
        st, p = page_request(s, "Kilter Board Original", scheme, 0, 1)
        climbs, stats = split(p)
        print("Response shape:", list(p) if isinstance(p, dict) else "list")
        print("Sample climb:", json.dumps(climbs[:1])[:800])
        print("Sample stats:", json.dumps(stats[:2])[:800])


def probe_stats(s):
    """Look for a bulk climb_stats endpoint; per-climb calls would be 650k requests."""
    p = "Kilter Board Original"
    st, cur = s.get("/climbs/curated")
    uuids = [c["climbUuid"] for c in cur["climbs"][:3]]  # curated climbs are known to have stats
    page = {"productName": p, **BOX, "offset": 0, "limit": 3}
    tries = [
        ("GET  climb-stat/{uuid}", lambda: s.get(f"/climb-stat/{uuids[0]}")),
        ("GET  climb-stat/{a,b,c}", lambda: s.get(f"/climb-stat/{','.join(uuids)}")),
        ("GET  climb-stat/uuids?uuids=a,b,c", lambda: s.get("/climb-stat/uuids", {"uuids": ",".join(uuids)})),
        ("POST climb-stat/uuids [uuids]", lambda: s.post("/climb-stat/uuids", uuids)),
        ("POST climb-stat/by-uuids [uuids]", lambda: s.post("/climb-stat/by-uuids", uuids)),
        ("POST climbs/climb-stats [uuids]", lambda: s.post("/climbs/climb-stats", uuids)),
        ("POST edges +angle", lambda: s.post(EDGES, {**page, "angle": 40})),
        ("POST edges +includeStats", lambda: s.post(EDGES, {**page, "includeStats": True})),
        ("POST edges +withStats", lambda: s.post(EDGES, {**page, "withStats": True})),
        ("GET  stats", lambda: s.get("/stats")),
        ("GET  climbs/stats", lambda: s.get("/climbs/stats")),
        ("GET  climb-stat/stats", lambda: s.get("/climb-stat/stats")),
        ("GET  climbs/curated?angle=40", lambda: s.get("/climbs/curated", {"angle": 40})),
        ("GET  v2/climb-rating", lambda: s.get("/v2/climb-rating")),
        ("GET  v2/climb-rating/{uuid}", lambda: s.get(f"/v2/climb-rating/{uuids[0]}")),
        ("GET  climb-rating/{uuid}", lambda: s.get(f"/climb-rating/{uuids[0]}")),
    ]
    for label, call in tries:
        st, r = call()
        text = r if isinstance(r, str) else json.dumps(r)
        print(f"== {label} [{st}]\n   {text[:400]}")


def fetch_stats(s, db_path, workers=4, include_unlisted=False):
    """Per-climb /climb-stat/{uuid} for every climb in db_path. Resumable: done uuids are recorded."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    db = sqlite3.connect(db_path)
    db.execute('CREATE TABLE IF NOT EXISTS stats_fetched ("climbUuid" PRIMARY KEY)')
    marks = ", ".join("?" * len(PRODUCTS))
    listed = "" if include_unlisted else 'AND c."isListed" = 1 AND c."isDraft" = 0 '
    todo = [u for (u,) in db.execute(
        f'SELECT c."climbUuid" FROM climbs c WHERE c."productName" IN ({marks}) {listed}'
        'AND c."climbUuid" NOT IN (SELECT "climbUuid" FROM stats_fetched)', PRODUCTS)]
    print(f"{len(todo)} climbs to fetch stats for ({workers} parallel requests)")
    stats_t = Table(db, "climb_stats", ["climbUuid", "angle"])
    existing = [r[1] for r in db.execute('PRAGMA table_info("climb_stats")')]
    stats_t.cols = existing

    lock = threading.Lock()

    def one(uuid):
        for attempt in range(4):
            with lock:  # token refresh is not thread-safe
                if time.time() > s.expires:
                    s._set(s._token({"grant_type": "refresh_token", "refresh_token": s.refresh}))
            st, r = s.get(f"/climb-stat/{uuid}", timeout=60)
            if st == 200:
                return uuid, r or []
            time.sleep(2 ** attempt)
        return uuid, None

    done, rows, t0 = 0, 0, time.time()
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(one, u) for u in todo]
        for f in as_completed(futures):
            uuid, stats = f.result()
            if stats is None:
                continue  # leave unrecorded; a rerun retries it
            stats_t.add(stats)
            db.execute('INSERT OR IGNORE INTO stats_fetched VALUES (?)', (uuid,))
            done += 1
            rows += len(stats)
            if done % 500 == 0:
                db.commit()
                rate = done / (time.time() - t0)
                eta = (len(todo) - done) / rate / 60
                print(f"  {done}/{len(todo)} climbs, {rows} stat rows, {rate:.1f}/s, ~{eta:.0f} min left", end="\r")
    db.commit()
    print(f"\nDone: {done} climbs, {rows} stat rows into {db_path}")


SYNC_URL ="https://sync1.kiltergrips.com/sync/stream"


def sync(s, out_path):
    """Stream the app's PowerSync buckets (the source of its local climbs/climb_stats tables).

    Protocol: POST /sync/stream, NDJSON response of checkpoint / data / checkpoint_complete lines.
    Each data op carries object_type (table name), object_id and data (JSON string).
    """
    import uuid as uuidlib
    body = {"buckets": [], "include_checksum": True, "raw_data": True,
            "client_id": str(uuidlib.uuid4()), "parameters": {}}
    req = urllib.request.Request(SYNC_URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Token {s.access}",
        "Content-Type": "application/json",
        "Accept": "application/x-ndjson",
        "User-Agent": "powersync-dart-core/1.0",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        sys.exit(f"Sync refused [{e.code}]: {e.read()[:500].decode(errors='replace')}")

    db = sqlite3.connect(out_path)
    tables, counts, removed = {}, {}, 0
    last_print = 0
    with resp:
        for raw in resp:
            line = raw.strip()
            if not line:
                continue
            msg = json.loads(line)
            if "checkpoint" in msg:
                buckets = msg["checkpoint"].get("buckets", [])
                print(f"checkpoint: {len(buckets)} buckets "
                      f"{[b.get('bucket') for b in buckets][:10]}")
            elif "data" in msg:
                for op in msg["data"].get("data", []):
                    t, oid = op.get("object_type"), op.get("object_id")
                    if op.get("op") == "PUT" and t:
                        row = json.loads(op["data"]) if isinstance(op.get("data"), str) else (op.get("data") or {})
                        row = {"id": oid, **row}
                        if t not in tables:
                            tables[t] = Table(db, t, ["id"])
                        tables[t].add([row])
                        counts[t] = counts.get(t, 0) + 1
                    elif op.get("op") == "REMOVE":
                        removed += 1
                if sum(counts.values()) - last_print >= 20000:
                    last_print = sum(counts.values())
                    db.commit()
                    print("  " + ", ".join(f"{k}={v}" for k, v in counts.items()), end="\r")
            elif "checkpoint_complete" in msg:
                print("\ncheckpoint complete")
                break
            elif "token_expires_in" in msg:
                if msg["token_expires_in"] <= 0:
                    sys.exit("Sync server says the token is expired/invalid for PowerSync.")
            else:
                print("other message:", json.dumps(msg)[:300])
    db.commit()
    print(f"rows: {counts}  (REMOVE ops skipped: {removed})")
    print(f"Saved {out_path}")


class Table:
    """SQLite table that grows columns as new keys appear; upserts on a key."""

    def __init__(self, db, name, key):
        self.db, self.name, self.key, self.cols = db, name, key, []

    def add(self, rows):
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            return
        new = [k for r in rows for k in r if k not in self.cols]
        new = list(dict.fromkeys(new))
        if not self.cols:
            self.cols = new
            cols = ", ".join(f'"{c}"' for c in self.cols)
            self.db.execute(f'CREATE TABLE IF NOT EXISTS "{self.name}" ({cols})')
            keycols = ", ".join(f'"{k}"' for k in self.key)
            self.db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "ux_{self.name}" ON "{self.name}" ({keycols})')
        else:
            for c in new:
                self.db.execute(f'ALTER TABLE "{self.name}" ADD COLUMN "{c}"')
                self.cols.append(c)
        cols = ", ".join(f'"{c}"' for c in self.cols)
        marks = ", ".join("?" * len(self.cols))
        cell = lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v
        self.db.executemany(
            f'INSERT OR REPLACE INTO "{self.name}" ({cols}) VALUES ({marks})',
            [[cell(r.get(c)) for c in self.cols] for r in rows],
        )


def dump(s, out_path):
    db = sqlite3.connect(out_path)
    climbs_t = Table(db, "climbs", ["climbUuid"])
    stats_t = Table(db, "climb_stats", ["climbUuid", "angle"])

    for product in PRODUCTS:
        total = count(s, product)
        if not total:
            print(f"{product}: no climbs, skipping")
            continue
        scheme = detect_scheme(s, product)
        if scheme is None:
            print(f"{product}: no paging detected, fetching {total} in one request (may take minutes)")
            st, p = s.post(EDGES, {"productName": product, **BOX}, timeout=1800)
            if st != 200:
                print(f"  failed [{st}]: {p}")
                continue
            climbs, stats = split(p)
            climbs_t.add(climbs)
            stats_t.add(stats)
            db.commit()
            print(f"  {len(climbs)} climbs, {len(stats)} stats")
            continue

        print(f"{product}: {total} climbs, paging with {scheme[1]}/{scheme[2]} in {scheme[0]}")
        index, got = 0, 0
        while got < total:
            for attempt in range(3):
                st, p = page_request(s, product, scheme, index, PAGE_SIZE, timeout=180)
                if st == 200:
                    break
                time.sleep(5 * (attempt + 1))
            else:
                print(f"\n  giving up at {got}/{total} [{st}]: {p}")
                break
            climbs, stats = split(p)
            if not climbs:
                break
            for c in climbs:
                c.setdefault("productName", product)
            climbs_t.add(climbs)
            stats_t.add(stats)
            db.commit()
            got += len(climbs)
            print(f"  {got}/{total}", end="\r")
            index += 1 if scheme[3] == "page" else PAGE_SIZE
        print()

    status, grades = s.get("/grades")
    if status == 200:
        Table(db, "grades", ["difficultyGradeId"]).add(grades)
    db.commit()
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        print(f"{t}: {db.execute(f'SELECT COUNT(*) FROM {chr(34)}{t}{chr(34)}').fetchone()[0]} rows")
    print(f"Saved {out_path}")


def dump_curated(s, out_path):
    status, cur = s.get("/climbs/curated")
    if status != 200:
        sys.exit(f"curated failed ({status}): {cur}")
    db = sqlite3.connect(out_path)
    Table(db, "climbs", ["climbUuid"]).add(cur.get("climbs", []))
    Table(db, "climb_stats", ["climbUuid", "angle"]).add(cur.get("climbStats", []))
    status, grades = s.get("/grades")
    if status == 200:
        Table(db, "grades", ["difficultyGradeId"]).add(grades)
    db.commit()
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        print(f"{t}: {db.execute(f'SELECT COUNT(*) FROM {chr(34)}{t}{chr(34)}').fetchone()[0]} rows")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    session = Session()
    if mode == "probe":
        probe(session)
    elif mode == "stats":
        fetch_stats(session, out or "kilter.db", include_unlisted="--all" in sys.argv)
    elif mode == "sync":
        sync(session, out or "kilter_sync.db")
    elif mode == "stats-probe":
        probe_stats(session)
    elif mode == "curated":
        dump_curated(session, out or "kilter_curated.db")
    else:
        dump(session, out or "kilter.db")
