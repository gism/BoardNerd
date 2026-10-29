"""Build a static KilterNerd-style report page from the databases kilter_dump.py produces.

Usage:
    python kilter_report.py [--climbs kilter.db] [--sync kilter_sync.db] [--out docs]

Writes <out>/index.html (self-contained: data is embedded, charts render in the browser)
plus full-length CSV lists. Only the Python standard library is used.

Inputs:
    kilter.db       climbs + climb_stats   (python kilter_dump.py dump / stats)
    kilter_sync.db  holes, roles, grades, beta links   (python kilter_dump.py sync)
"""
import argparse
import base64
import collections
import csv
import datetime
import json
import os
import re
import sqlite3
import unicodedata

HOLD_RE = re.compile(r"h(\d+)p(\d+)")
ROLES = ["start", "hand", "finish", "foot"]
# placement_types.placement_type -> report role. Colour-only types (cyan, red, ...) are ignored.
ROLE_OF_TYPE = {"start": 0, "middle": 1, "finish": 2, "foot": 3}
ANGLES = list(range(0, 75, 5))
TOP_N = 100

# Board photos drawn under the hold-usage chart, with the hole-coordinate box the image covers
# (left, right, bottom, top). The Original image is KilterNerd's img.png: the 16x12 Super Wide
# board on a 4-unit hole grid, 47 x 38 cells (about x -22..166, y 2..154). The box below was
# fine-tuned by overlaying hole coordinates on the bolt holes in the photo, corner to corner.
BOARD_IMAGES = {
    "Kilter Board Original": ("boards/kilter-board-original.png", (-22.5, 166, 2, 155)),
}


def connect_ro(path):
    # immutable=1 lets us read while kilter_dump.py is still writing (no lock taken).
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def is_emoji(ch):
    cp = ord(ch)
    return (unicodedata.category(ch) == "So" and cp >= 0x2190) or 0x1F1E6 <= cp <= 0x1F1FF


def name_tokens(name):
    words, emojis = [], []
    buf = []
    join_next = False
    for ch in name or "":
        if ch == "‍":  # zero-width joiner: glue the next emoji onto the previous one (🧗 + ♀ = 🧗‍♀)
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


def load_reference(sync):
    # Only grades the app lists (4A/V0 and up); lower ids appear as placeholders on ungraded stats.
    grades = {gid: label for gid, label in sync.execute(
        "SELECT difficulty_grade_id, boulder_difficulty FROM difficulty_grades WHERE is_listed = 1")}
    role_of_code = {code: ROLE_OF_TYPE[t] for t, code in sync.execute(
        "SELECT placement_type, short_ref FROM placement_types") if t in ROLE_OF_TYPE}
    holes = collections.defaultdict(list)
    for hid, product, x, y in sync.execute("SELECT mounting_hole_uuid, product_name, x, y FROM mounting_holes"):
        holes[product].append((int(hid), x, y))
    beta = collections.defaultdict(list)
    for uuid, user in sync.execute("SELECT climb_uuid, foreign_username FROM climb_beta_links"):
        if uuid and user:
            beta[uuid.upper()].append(user)
    return grades, role_of_code, holes, beta


def board_image(product):
    entry = BOARD_IMAGES.get(product)
    if not entry:
        return None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), entry[0])
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        uri = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    left, right, bottom, top = entry[1]
    return {"src": uri, "left": left, "right": right, "bottom": bottom, "top": top}


def build_product(product, climbs_db, grades, role_of_code, product_holes, beta, out_dir):
    print(f"{product}: reading climbs")
    hole_ids = sorted(h for h, _, _ in product_holes)
    hole_index = {h: i for i, h in enumerate(hole_ids)}
    n_holes = len(hole_ids)

    growth = collections.Counter()
    growth_listed = collections.Counter()
    setters = collections.Counter()
    uploaders = collections.Counter()
    words = collections.Counter()
    emojis = collections.Counter()
    holds_of = {}  # listed climbs only: uuid -> [(hole_idx, role)]
    hold_all = [[0] * n_holes for _ in ROLES]
    n_climbs = n_listed = 0

    for uuid, concat, name, user, listed, draft, created in climbs_db.execute(
            'SELECT climbUuid, climbConcat, name, username, isListed, isDraft, createdAt '
            'FROM climbs WHERE productName = ?', (product,)):
        n_climbs += 1
        month = (created or "")[:7]
        if month:
            growth[month] += 1
        setters[user or "(unknown)"] += 1
        for u in beta.get(uuid, ()):
            uploaders[u] += 1
        w, e = name_tokens(name)
        words.update(w)
        emojis.update(e)
        if listed and not draft:
            n_listed += 1
            if month:
                growth_listed[month] += 1
            holds = []
            for h, p in HOLD_RE.findall(concat or ""):
                idx, role = hole_index.get(int(h)), role_of_code.get(int(p))
                if idx is not None and role is not None:
                    holds.append((idx, role))
                    hold_all[role][idx] += 1
            holds_of[uuid] = holds

    print(f"{product}: reading stats")
    angle_idx = {a: i for i, a in enumerate(ANGLES)}
    by_grade_n, by_grade_asc = collections.Counter(), collections.Counter()
    by_angle_n, by_angle_asc = collections.Counter(), collections.Counter()
    matrix_n, matrix_asc = collections.Counter(), collections.Counter()
    hold_ga = {}  # (grade, angle_idx) -> [role][hole] counts
    n_stats = total_asc = 0
    for uuid, angle, grade, asc in climbs_db.execute(
            'SELECT s.climbUuid, s.angle, s.currentDifficultyId, s.ascentCount '
            'FROM climb_stats s JOIN climbs c ON c.climbUuid = s.climbUuid '
            'WHERE c.productName = ?', (product,)):
        # Rows with no ascents are placeholders (grade 1, quality 1), not real gradings.
        if not asc or grade not in grades or angle not in angle_idx:
            continue
        n_stats += 1
        total_asc += asc
        by_grade_n[grade] += 1
        by_grade_asc[grade] += asc
        by_angle_n[angle] += 1
        by_angle_asc[angle] += asc
        matrix_n[grade, angle] += 1
        matrix_asc[grade, angle] += asc
        holds = holds_of.get(uuid)
        if holds:
            key = (grade, angle_idx[angle])
            cell = hold_ga.get(key)
            if cell is None:
                cell = hold_ga[key] = [[0] * n_holes for _ in ROLES]
            for idx, role in holds:
                cell[role][idx] += 1

    grade_ids = sorted(by_grade_n) or []
    if grade_ids:
        grade_ids = list(range(grade_ids[0], grade_ids[-1] + 1))

    base = slug(product)
    write_csv(os.path.join(out_dir, f"setters-{base}.csv"), ["setter", "climbs"], setters)
    write_csv(os.path.join(out_dir, f"video-uploaders-{base}.csv"), ["user", "videos"], uploaders)
    write_csv(os.path.join(out_dir, f"name-words-{base}.csv"), ["word", "count"], words)
    write_csv(os.path.join(out_dir, f"name-emojis-{base}.csv"), ["emoji", "count"], emojis)

    months = sorted(set(growth) | set(growth_listed))
    cum_all, cum_listed, a, l = [], [], 0, 0
    for m in months:
        a += growth[m]
        l += growth_listed[m]
        cum_all.append(a)
        cum_listed.append(l)

    return {
        "name": product,
        "slug": base,
        "totals": {"climbs": n_climbs, "listed": n_listed, "climbAngles": n_stats, "ascents": total_asc},
        "growth": {"months": months, "all": cum_all, "listed": cum_listed},
        "setters": ranked(setters),
        "uploaders": ranked(uploaders),
        "words": ranked(words),
        "emojis": ranked(emojis, 50),
        "grades": [[g, grades.get(g, str(g))] for g in grade_ids],
        "byGrade": {"climbs": [by_grade_n[g] for g in grade_ids], "ascents": [by_grade_asc[g] for g in grade_ids]},
        "byAngle": {"climbs": [by_angle_n[a] for a in ANGLES], "ascents": [by_angle_asc[a] for a in ANGLES]},
        "matrix": {"climbs": [[matrix_n[g, a] for a in ANGLES] for g in grade_ids],
                   "ascents": [[matrix_asc[g, a] for a in ANGLES] for g in grade_ids]},
        "board": {
            "holes": [[h, x, y] for h, x, y in sorted(product_holes)],
            "image": board_image(product),
            "all": hold_all,
            # sparse: "grade|angleIdx" -> [role][hole]; empty combos omitted
            "ga": {f"{g}|{ai}": cell for (g, ai), cell in hold_ga.items()},
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--climbs", default="kilter.db")
    ap.add_argument("--sync", default="kilter_sync.db")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    climbs_db, sync = connect_ro(args.climbs), connect_ro(args.sync)
    grades, role_of_code, holes, beta = load_reference(sync)

    products = [p for (p,) in climbs_db.execute(
        "SELECT productName FROM climbs GROUP BY productName ORDER BY COUNT(*) DESC")]
    data = {
        "generated": datetime.date.today().isoformat(),
        "snapshot": datetime.date.fromtimestamp(os.path.getmtime(args.climbs)).isoformat(),
        "angles": ANGLES,
        "roles": ROLES,
        "products": [build_product(p, climbs_db, grades, role_of_code, holes.get(p, []), beta, args.out)
                     for p in products],
    }

    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html")
    with open(template_path, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload)
    out = os.path.join(args.out, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB) and CSV lists in {args.out}/")


if __name__ == "__main__":
    main()
