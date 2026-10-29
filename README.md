# BoardNerd

Download the Kilter Board climb catalogue from the new Kilter app's API into a
local SQLite file for analysis.

```
python kilter_dump.py probe               # climb counts per board + paging check
python kilter_dump.py dump kilter.db      # full catalogue (climbs, grades)
python kilter_dump.py curated out.db      # curated set, with per-angle stats
python kilter_dump.py stats-probe         # look for a bulk stats endpoint
```

Credentials are read from `KILTER_EMAIL` / `KILTER_PASSWORD`, or prompted for.
Standard library only.
