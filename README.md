# BoardNerd

**📊 Report: [gism.github.io/BoardNerd](https://gism.github.io/BoardNerd/)**

Statistics on climbing-wall boulders: growth, setters, grades, angles and hold usage. Covers
Kilter Board and MoonBoard, picked from one dropdown on the report page. Previously
[KilterNerd](https://github.com/gism/KilterNerd), rebuilt on the new Kilter app API after the
Aurora app was retired in March 2026.

## Kilter Board

```
python kilter_dump.py dump kilter.db      # full catalogue (boulders) into kilter.db
python kilter_dump.py stats kilter.db     # per-angle stats for every listed boulder (slow, resumable)
python kilter_dump.py sync kilter_sync.db # holes, hold roles, grades, beta videos
```

Other `kilter_dump.py` modes: `probe` (counts per board + paging check), `curated out.db`
(curated set with stats), `stats-probe` (bulk stats endpoint search).

Credentials are read from `KILTER_EMAIL` / `KILTER_PASSWORD`, or prompted for.
The API is documented in [API.md](API.md).

## MoonBoard

The MoonBoard app's own API (`restapimoonboard.ems-x.com`, used by older third-party clients
like [spookykat/MoonBoard](https://github.com/spookykat/MoonBoard)) is dead, and the current
app's backend hasn't been found. Instead, `moon_load_dumps.py` reads a directory of per-board
JSON dumps (one file per holdsetup, shaped `{"holdsetup", "count", "problems": [...]}`) into
`moon.db`:

```
python moon_load_dumps.py <dumps_dir> moon.db   # load every *.json dump found under dumps_dir
```

`moon_report.py` isn't run directly - `kilter_report.py` imports it and folds its boards into
the same report (see below), including hold usage: each problem's `moves` field encodes hold
positions as a column letter (A left .. K right) and row number (1 bottom .. 18 top), decoded
in `moon_report.py`. The per-hold *role* (start/hand/finish/foot) is a best-effort guess for
everything but start/finish/foot holds themselves - see the comment at the top of that file.

## Build the report

```
python kilter_report.py   # reads kilter.db + kilter_sync.db + moon.db, writes docs/index.html
```

`moon.db` is optional - if it's missing, the report is built with Kilter boards only.
`docs/index.html` is self-contained (data embedded) and is what GitHub Pages serves.
Don't run it while a dump script is still writing to one of its databases.

Standard library only. The 3D views (Kilter boards) load Plotly from a CDN on first use.
