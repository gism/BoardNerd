# BoardNerd

**📊 Report: [gism.github.io/BoardNerd](https://gism.github.io/BoardNerd/)**

Statistics on Kilter Board boulders: growth, setters, grades, angles and hold usage.
Previously [KilterNerd](https://github.com/gism/KilterNerd), rebuilt on the new Kilter app API
after the Aurora app was retired in March 2026.

## Build the database

```
python kilter_dump.py dump kilter.db      # full catalogue (boulders) into kilter.db
python kilter_dump.py stats kilter.db     # per-angle stats for every listed boulder (slow, resumable)
python kilter_dump.py sync kilter_sync.db # holes, hold roles, grades, beta videos
```

Other modes: `probe` (counts per board + paging check), `curated out.db` (curated set with stats),
`stats-probe` (bulk stats endpoint search).

Credentials are read from `KILTER_EMAIL` / `KILTER_PASSWORD`, or prompted for.
The API is documented in [API.md](API.md).

## Build the report

```
python kilter_report.py                   # reads kilter.db + kilter_sync.db, writes docs/
```

`docs/index.html` is self-contained (data embedded) and is what GitHub Pages serves.
Don't run it while `kilter_dump.py` is writing to `kilter.db`.

Standard library only. The 3D views load Plotly from a CDN on first use.
