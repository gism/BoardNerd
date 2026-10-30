"""Load the community MoonBoard problem dumps (one JSON file per board/holdsetup) into SQLite.

Usage:
    python moon_load_dumps.py <dumps_dir> [moon.db]

<dumps_dir> is searched recursively for *.json files shaped like:
    {"holdsetup": <id>, "count": <n>, "problems": [ {...}, ... ]}

Each problem has a nested "configurations" list (one entry per angle); that list is
flattened into its own table, keyed on (problem_id, apiId). Only the Python standard
library is used - this mirrors the Table helper in kilter_dump.py.
"""
import glob
import json
import os
import sqlite3
import sys


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


def load_file(db, path, problems_t, configs_t):
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    holdsetup = payload.get("holdsetup")
    problems = payload.get("problems") or []
    name = os.path.splitext(os.path.basename(path))[0]

    flat_problems, flat_configs = [], []
    for p in problems:
        configs = p.pop("configurations", []) or []
        p["boardName"] = name
        flat_problems.append(p)
        for c in configs:
            c = {**c, "problemId": p["id"], "holdsetup": holdsetup}
            flat_configs.append(c)

    problems_t.add(flat_problems)
    configs_t.add(flat_configs)
    db.commit()
    print(f"{name}: {len(flat_problems)} problems (declared count={payload.get('count')}), "
          f"{len(flat_configs)} angle-configurations")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    dumps_dir = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "moon.db"

    files = sorted(glob.glob(os.path.join(dumps_dir, "**", "*.json"), recursive=True))
    if not files:
        sys.exit(f"No .json files found under {dumps_dir}")

    db = sqlite3.connect(out_path)
    problems_t = Table(db, "problems", ["id"])
    configs_t = Table(db, "problem_configurations", ["problemId", "apiId"])

    for f in files:
        load_file(db, f, problems_t, configs_t)

    print()
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        print(f"{t}: {db.execute(f'SELECT COUNT(*) FROM {chr(34)}{t}{chr(34)}').fetchone()[0]} rows")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
