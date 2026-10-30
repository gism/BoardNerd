"""MoonBoard half of the BoardNerd report: builds one `product` dict per board/holdsetup
from the database moon_load_dumps.py produces, in the same shape kilter_report.py's
report_template.html already expects. Imported by kilter_report.py - not run directly.

Input: moon.db (problems + problem_configurations), from moon_load_dumps.py.

Hold positions: each problem's "moves" field is "|"-separated "<prefix>~<col><row>~"
segments, e.g. "s~G5~|p~E9~|e~C18~". Column letters run A (left) to K (right), rows 1
(bottom) to 18 (top) - confirmed against every problem in the Oct 2026 dumps, zero parse
failures. The prefix maps to a Kilter-style role; s/e/f are confident (start/finish/foot),
but p/l/r/m (all folded into "hand" here) are a guess - MoonBoard's own app likely uses
them to mark which hand/technique a path hold takes, not a separate role, but that's not
confirmed anywhere official.

No board image is set (BOARD_IMAGES equivalent), so the chart renders holds only, no photo
underneath - same fallback Kilter boards without a photo already use.
"""
import collections
import csv
import os
import re
import sqlite3
import unicodedata

# Font/Fontainebleau bouldering scale, ascending. Wider than what's been seen in any dump
# so far (5+ .. 8B+) in case future dumps reach lower or higher.
FONT_ORDER = [
    "3", "4", "4+", "5", "5+",
    "6A", "6A+", "6B", "6B+", "6C", "6C+",
    "7A", "7A+", "7B", "7B+", "7C", "7C+",
    "8A", "8A+", "8B", "8B+", "8C", "8C+",
    "9A", "9A+", "9B", "9B+", "9C",
]
GRADE_INDEX = {g: i for i, g in enumerate(FONT_ORDER)}
TOP_N = 100
# report_template.html's board chart (circle radii, blur, viewBox padding) is tuned for
# Kilter's hole spacing (4 units between adjacent holes); scale Moon's 1-apart grid to match.
GRID_SCALE = 4
ROLES = ["start", "hand", "finish", "foot"]
ROLE_OF_PREFIX = {"s": 0, "e": 2, "f": 3}  # anything else (p/l/r/m/...) -> 1 "hand"
MOVE_RE = re.compile(r"^([a-z]+)~([A-Za-z]+)(\d+)~$")
# Board order in the report's picker; any other board found in moon.db is appended after these.
BOARDS = [
    "MoonBoard 2024", "MoonBoard Masters 2019", "MoonBoard Masters 2017", "MoonBoard 2016",
    "MoonBoard 2010", "Mini MoonBoard 2025", "Mini MoonBoard 2020",
]


def connect_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def is_emoji(ch):
    cp = ord(ch)
    return (unicodedata.category(ch) == "So" and cp >= 0x2190) or 0x1F1E6 <= cp <= 0x1F1FF


def name_tokens(name):
    words, emojis = [], []
    buf = []
    join_next = False
    for ch in name or "":
        if ch == "‍":  # zero-width joiner: glue the next emoji onto the previous one
            join_next = bool(emojis)
            continue
        if ch == "️" or 0x1F3FB <= ord(ch) <= 0x1F3FF:  # variation selector, skin tones
            if emojis and ch != "️":
                emojis[-1] += ch
            continue
        if is_emoji(ch):
            if join_next:
                emojis[-1] += "‍" + ch
            else:
                emojis.append(ch)
            buf.append(" ")
        else:
            buf.append(ch)
        join_next = False
    for w in "".join(buf).lower().split():
        w = w.strip(".,!?\"'()[]{}:;-_*~`")
        if w:
            words.append(w)
    return words, emojis


def ranked(counter, n=TOP_N):
    total = sum(counter.values()) or 1
    return {"total": sum(counter.values()), "distinct": len(counter),
            "rows": [[k, v, round(100 * v / total, 3)] for k, v in counter.most_common(n)]}


def write_csv(path, header, counter):
    total = sum(counter.values()) or 1
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", *header, "percent"])
        for i, (k, v) in enumerate(counter.most_common(), 1):
            w.writerow([i, k, v, f"{100 * v / total:.3f}"])


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def col_index(letters):
    # Spreadsheet-style base-26: "A" -> 0, "K" -> 10, "AA" -> 26 (not seen in practice; every
    # dump so far uses single letters A-K).
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def parse_moves(moves):
    """"s~G5~|p~E9~|..." -> [(col, row, role), ...]; malformed segments are dropped."""
    out = []
    for seg in (moves or "").split("|"):
        m = MOVE_RE.match(seg)
        if not m:
            continue
        prefix, col, row = m.groups()
        out.append((col_index(col), int(row), ROLE_OF_PREFIX.get(prefix, 1)))
    return out


def angle_value(config):
    # "25°" -> 25, matching kilter_report.py's ANGLES (plain ints); unrecognised -> None.
    m = re.match(r"(\d+)", config or "")
    return int(m.group(1)) if m else None


def boards_present(db):
    present = [p for (p,) in db.execute(
        'SELECT "boardName" FROM problems GROUP BY "boardName" ORDER BY COUNT(*) DESC') if p]
    return [b for b in BOARDS if b in present] + [b for b in present if b not in BOARDS]


def build_board(name, db, angles, out_dir):
    """angles: the report's global angle list (ints, e.g. kilter_report.ANGLES)."""
    print(f"{name}: reading problems")
    growth = collections.Counter()
    growth_active = collections.Counter()
    setters = collections.Counter()
    setter_of = {}
    words = collections.Counter()
    emojis = collections.Counter()
    raw_holds_of = {}  # active problems only: id -> [(col, row, role), ...]
    positions = set()
    n_problems = n_active = 0

    for pid, pname, setter, inserted, deleted, moves in db.execute(
            'SELECT id, name, setter, dateInserted, dateDeleted, moves FROM problems WHERE "boardName" = ?',
            (name,)):
        n_problems += 1
        month = (inserted or "")[:7]
        if month:
            growth[month] += 1
        setter_of[pid] = setter or "(unknown)"
        setters[setter or "(unknown)"] += 1
        w, e = name_tokens(pname)
        words.update(w)
        emojis.update(e)
        if deleted is None:
            n_active += 1
            if month:
                growth_active[month] += 1
            holds = parse_moves(moves)
            if holds:
                raw_holds_of[pid] = holds
                positions.update((c, r) for c, r, _ in holds)

    # Hole grid: only positions actually referenced by a hold, there's no separate
    # reference table of every physical T-nut position (unlike Kilter's kilter_sync.db).
    hole_ids = sorted(positions)
    hole_index = {pos: i for i, pos in enumerate(hole_ids)}
    n_holes = len(hole_ids)
    hold_all = [[0] * n_holes for _ in ROLES]
    holds_of = {}  # id -> [(hole_idx, role), ...]
    for pid, holds in raw_holds_of.items():
        resolved = [(hole_index[(c, r)], role) for c, r, role in holds]
        holds_of[pid] = resolved
        for idx, role in resolved:
            hold_all[role][idx] += 1

    print(f"{name}: reading configurations")
    angle_idx = {a: i for i, a in enumerate(angles)}
    setter_asc = collections.Counter()
    by_grade_n, by_grade_asc = collections.Counter(), collections.Counter()
    by_angle_n, by_angle_asc = collections.Counter(), collections.Counter()
    matrix_n, matrix_asc = collections.Counter(), collections.Counter()
    hold_ga = {}  # (grade, angle_idx) -> [role][hole] counts
    n_configs = total_asc = 0
    for pid, grade, config, repeats in db.execute(
            'SELECT c."problemId", c.grade, c.configuration, c.repeats '
            'FROM problem_configurations c JOIN problems p ON p.id = c."problemId" '
            'WHERE p."boardName" = ?', (name,)):
        gi = GRADE_INDEX.get(grade)
        av = angle_value(config)
        ai = angle_idx.get(av)
        if gi is None or ai is None:
            continue
        repeats = repeats or 0
        n_configs += 1
        total_asc += repeats
        setter_asc[setter_of.get(pid, "(unknown)")] += repeats
        by_grade_n[gi] += 1
        by_grade_asc[gi] += repeats
        by_angle_n[av] += 1
        by_angle_asc[av] += repeats
        matrix_n[gi, av] += 1
        matrix_asc[gi, av] += repeats
        holds = holds_of.get(pid)
        if holds:
            key = (gi, ai)
            cell = hold_ga.get(key)
            if cell is None:
                cell = hold_ga[key] = [[0] * n_holes for _ in ROLES]
            for idx, role in holds:
                cell[role][idx] += 1

    grade_idx_present = sorted(by_grade_n) or []
    if grade_idx_present:
        grade_idx_present = list(range(grade_idx_present[0], grade_idx_present[-1] + 1))

    base = slug(name)
    write_csv(os.path.join(out_dir, f"setters-{base}.csv"), ["setter", "boulders"], setters)
    write_csv(os.path.join(out_dir, f"setters-by-ascents-{base}.csv"), ["setter", "ascents"], setter_asc)
    write_csv(os.path.join(out_dir, f"video-uploaders-{base}.csv"), ["user", "videos"], collections.Counter())
    write_csv(os.path.join(out_dir, f"name-words-{base}.csv"), ["word", "count"], words)
    write_csv(os.path.join(out_dir, f"name-emojis-{base}.csv"), ["emoji", "count"], emojis)

    months = sorted(set(growth) | set(growth_active))
    cum_all, cum_active, a, l = [], [], 0, 0
    for m in months:
        a += growth[m]
        l += growth_active[m]
        cum_all.append(a)
        cum_active.append(l)

    return {
        "name": name,
        "slug": base,
        "totals": {"climbs": n_problems, "listed": n_active, "climbAngles": n_configs, "ascents": total_asc},
        "growth": {"months": months, "all": cum_all, "listed": cum_active},
        "setters": ranked(setters),
        "settersByAscents": ranked(setter_asc),
        "uploaders": ranked(collections.Counter()),
        "words": ranked(words),
        "emojis": ranked(emojis, 50),
        "grades": [[g, FONT_ORDER[g]] for g in grade_idx_present],
        "byGrade": {"climbs": [by_grade_n[g] for g in grade_idx_present],
                    "ascents": [by_grade_asc[g] for g in grade_idx_present]},
        "byAngle": {"climbs": [by_angle_n[a] for a in angles], "ascents": [by_angle_asc[a] for a in angles]},
        "matrix": {"climbs": [[matrix_n[g, a] for a in angles] for g in grade_idx_present],
                   "ascents": [[matrix_asc[g, a] for a in angles] for g in grade_idx_present]},
        "board": {
            "holes": [[f"{chr(65 + c)}{r}", c * GRID_SCALE, r * GRID_SCALE] for c, r in hole_ids],
            "image": None,
            "all": hold_all,
            "ga": {f"{g}|{ai}": cell for (g, ai), cell in hold_ga.items()},
        },
    }
