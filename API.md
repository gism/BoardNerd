# Kilter Board API (new app) — field notes

Reverse-engineered from the Android app `com.kiltergrips.kilter_board_app` v2.10.1
(Flutter, with PowerSync and SQLite) and checked against the live API on 2026-10-29.

This is not an official API. It can change without notice.

**Legend:** ✅ confirmed with a real call · ❌ tried and rejected · 🔍 seen in the app binary, not tested

---

## Overview

| Host | Purpose |
|---|---|
| `https://idp.kiltergrips.com/realms/kilter` | Keycloak (OpenID Connect) login |
| `https://portal.kiltergrips.com/api` | REST API: climbs, stats, logs, users |
| `https://sync1.kiltergrips.com` | PowerSync server: reference data (holds, layouts, gyms, walls) |

The old Aurora API (`kilterboardapp.com`, `api.kilterboardapp.com`) was shut down in March 2026.
Kilter data on it is frozen at January 2026.

---

## Authentication ✅

```
POST https://idp.kiltergrips.com/realms/kilter/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=password
client_id=kilter
scope=openid offline_access
username=<account email>
password=<password>
```

- `username` must be the account **email**. Usernames from the old Aurora app don't work.
- The response is a standard OIDC token set: `access_token`, `refresh_token`, `expires_in`.
- Bad credentials return `401 {"error":"invalid_grant","error_description":"Invalid user credentials"}`.
- To refresh, send the same request with `grant_type=refresh_token` and `refresh_token=<token>`.

Send the token to the REST API as:

```
Authorization: Bearer <access_token>
```

Send the token to PowerSync as `Authorization: Token <access_token>`. It's the same token with a different scheme.

---

## Climb catalogue

### Count climbs ✅

```
POST /api/climbs/climbdetails/productName/edges/count
Content-Type: application/json

{"productName": "Kilter Board Original",
 "edgeLeft": -1000, "edgeRight": 1000, "edgeBottom": -1000, "edgeTop": 1000}
```

The response is a bare integer, for example `585272`.

- `productName` in the path is a **literal** path segment. Putting the product name there returns 404.
- `GET` returns 405.
- An empty body `{}` returns `0`.
- The four edges define a bounding box. Only climbs fully inside it are counted, so the wide box above returns everything.

### List climbs ✅

```
POST /api/climbs/climbdetails/productName/edges
Content-Type: application/json

{"productName": "Kilter Board Original",
 "edgeLeft": -1000, "edgeRight": 1000, "edgeBottom": -1000, "edgeTop": 1000,
 "offset": 0, "limit": 5000}
```

The response is a JSON array of [climb objects](#climb-object).

- **Paging:** `offset` and `limit` go in the **JSON body**. A full download of 585k climbs at `limit` 5000 works.
- **Without `offset`/`limit` it returns every climb in one response** (585k for the Original board, in under 30 s).
- These are ignored, and the server returns everything: `page`/`pageSize` and `page`/`size`, in either the body or the query string.
- These body fields are ignored: `angle`, `includeStats`, `withStats`. Climbs never include stats.

### Products ✅

Counts as of 2026-10-29:

| `productName` | Climbs |
|---|---|
| `Kilter Board Original` | 585,272 |
| `Kilter Board Homewall` | 66,727 |
| `Spire` | 627 |
| `UP Board` | 543 |
| `JUUL` | 164 |

### Curated climbs ✅

```
GET /api/climbs/curated
```

The response is `{"climbs": [...], "climbStats": [...]}`: 5,165 climbs across all products, **with stats included**.
It ignores `page`, `pageSize` and `angle`.

### Logged climbs ✅

```
GET /api/climbs/logged
```

The response is `{"climbs": [...], "climbStats": [...]}` for climbs the signed-in user has logged.
Both lists were empty for the test account.

### Climb object

```json
{
  "climbUuid": "DCAFA2369E404B2A90B01C257C171294",
  "climbConcat": "h1404p12h1408p12h1417p13h1428p14h1145p15h1459p15h1450p15h1364p15",
  "name": "Middle Route",
  "description": "",
  "edgeLeft": 60, "edgeRight": 92, "edgeBottom": 4, "edgeTop": 152,
  "frameCount": 1,
  "framesPace": 0,
  "userUuid": "1049",
  "username": "petermichaux",
  "productName": "Kilter Board Original",
  "productLayoutUuid": "8",
  "allowMatch": true,
  "isDraft": false,
  "isListed": false,
  "accumulatedHoldSetValue": 3,
  "createdAt": "2018-02-24T03:34:10.161212Z",
  "updatedAt": "2018-02-24T03:34:10.161212Z"
}
```

- Curated climbs also carry `isDeleted`, `angle` (the setter's angle) and `origin` (for example `"NATIVE"`).
- `climbConcat` is a sequence of `h<holdId>p<role>`. By analogy with the Aurora format (*inferred, not verified*), role 12 is start, 13 is hand, 14 is finish and 15 is foot. Hold ids match `holds` and `mounting_holes` in the [PowerSync data](#powersync-reference-data).
- Climbs carry no grade or quality. Those come from [climb stats](#climb-stats).

---

## Climb stats

### Stats for one climb ✅

```
GET /api/climb-stat/{climbUuid}
```

The response is an array with one entry per angle:

```json
[{"climbUuid": "0007051C73F64E1F889F0C79F23A9D68", "angle": 60,
  "ascentCount": 116, "currentDifficultyId": 27, "officialKilterDifficulty": 28,
  "difficultyAverage": 27.06, "qualityAverage": 4.33,
  "faUsername": "fyfee", "faAt": "2023-05-28T18:26:43Z"}]
```

- `currentDifficultyId` and `officialKilterDifficulty` map to `difficultyGradeId` in [`/api/grades`](#grades).
- `officialKilterDifficulty` is only present when Kilter has set an official grade.
- An unknown climb, or one with no ascents, returns `[]`.

**There is no bulk stats endpoint.** These all failed:

| Tried | Result |
|---|---|
| `GET /api/climb-stat/{a},{b},{c}` | `200 []` |
| `GET /api/climb-stat/uuids?uuids=a,b,c` | `200 []` |
| `GET /api/climb-stat/all`, `/climb-stat/stats`, `/climbs/stats` | `200 []` (the path is read as a uuid) |
| `GET /api/climb-stat`, `/api/climb-stat/` (any query) | 405 |
| `POST /api/climb-stat/`, `/climb-stat/uuids`, `/climb-stat/by-uuids`, `/climb-stat/bulk`, `/climbs/climb-stats` | 405 |
| `POST /api/climb-stat/climbdetails/productName/edges`, `/climb-stat/productName/edges`, `.../edges/stats` | 404 |
| `GET /api/stats` | 404 |

The only routes to full stats are one request per climb, or the curated set.

### Climb ratings

| Call | Result |
|---|---|
| `GET /api/climb-rating/{climbUuid}` | ✅ `200 []` for the climb tested |
| `GET /api/v2/climb-rating` | ❌ 405, probably POST-only (creates a rating) |
| `GET /api/v2/climb-rating/{climbUuid}` | ❌ 404 |

In the app, the local `climb_ratings` table holds one user's own rating of a climb: `rating`, `difficulty_grade_id`, `comment`.

---

## Grades ✅

```
GET /api/grades
```

```json
[{"difficultyGradeId": 1, "boulderDifficulty": "1A/V0", "routeDifficulty": "2b/5.1",
  "isListed": false, "fontScale": "1A", "vScale": "V0", "frenchScale": "2b", "ydsScale": "5.1"}]
```

The response has 39 grades. The same table arrives through PowerSync as `difficulty_grades`.

---

## PowerSync reference data ✅

The app syncs reference data with [PowerSync](https://docs.powersync.com/). Its protocol is open:

```
POST https://sync1.kiltergrips.com/sync/stream
Authorization: Token <keycloak access_token>
Content-Type: application/json
Accept: application/x-ndjson

{"buckets": [], "include_checksum": true, "raw_data": true,
 "client_id": "<random uuid>", "parameters": {}}
```

The response is NDJSON, one message per line:

- `{"checkpoint": {"buckets": [...]}}` lists the buckets to sync.
- `{"data": {"bucket": "...", "data": [{"op": "PUT", "object_type": "<table>", "object_id": "...", "data": "<json string>"}]}}`
- `{"checkpoint_complete": {...}}` means the initial sync is done. The stream then stays open for live updates.
- `{"token_expires_in": N}`

Buckets the test account received: `global[]`, `global_gyms[]`, `global_climbs[]`, `user_buckets["<user uuid>"]`.

Tables and row counts as of 2026-10-29:

| Table | Rows | Table | Rows |
|---|---|---|---|
| `climb_beta_links` | 24,224 | `products` | 10 |
| `hold_placements` | 10,406 | `placement_types` | 10 |
| `holds` | 4,311 | `hold_sets` | 11 |
| `mounting_holes` | 4,311 | `videos` | 3 |
| `walls` | 1,269 | `grade_systems` | 2 |
| `gyms` | 1,159 | `app_configs` | 1 |
| `difficulty_grades` | 39 | `climb_filter_configs` | 1 |
| `product_layouts` | 28 | `users` | 1 (yourself) |

**Climbs and climb stats are not synced.** The app loads those over REST.

---

## Endpoints seen in the app but not tested 🔍

Found as strings in `libapp.so`. Methods and payloads are unknown.

**Climbs**
- `/api/climbs/` and `/api/climbs/climbdetails/user`
- `/api/climbs/customactions`
- `/api/climbs/create-climb/transaction` and `/api/climbs/update-climb/transaction`
- `/api/climb-mounting-holes/`
- `/api/report-climb`
- `/api/recently-displayed-climbs/add`, `/climbs` and `/report`

**Circuits (playlists)**
- `/api/circuits`, `/api/circuits/get-circuit/` and `/api/circuit-climbs`

**Logs**
- `/api/v2/logs`, `/api/v2/logs/` and `/api/v2/logs/bulk`
- `/api/logs` is what BoardLib uses: `GET` returns the user's logbook.

**Users and social**
- `/api/users/`, `/api/users/find`, `/api/users/register`
- `/api/users/user-settings` and `/api/users/user-settings/notifications-last-seen`
- `/api/users/user-analytics`
- `/api/users/block-climb` and `/api/users/unblock-climb/`
- `/api/users/email/verification`, `/api/users/email/verify/` and `/api/users/resend/id/`
- `/api/followers/user`, `/api/followers/user/following` and `/api/followers/gym/`
- `/api/v2/followers/users/` and `/api/v2/followers/gyms/`
- `/api/notifications/`
- `/api/image`, `/api/image/user`

**Walls and app**
- `/api/walls`, `/api/walls/climbcount` and `/api/walls/custom-wall`
- `/api/app/versions/`

Endpoints that **don't exist**:

| Call | Result |
|---|---|
| `/api/climbs/climbdetails/{product name}/edges` | 404 (any method) |
| `/api/climbs/single/{uuid}` | 404 (GET) |

---

## Practical notes

- **Full catalogue:** one `/edges/count` call and about 130 paged `/edges` calls per full download.
- **Stats:** one `/climb-stat/{uuid}` call per climb. Restrict it to `isListed && !isDraft` to cut the volume, and keep concurrency low.
- **Older stats:** the bundled database in the old Aurora app (`assets/db.sqlite3` in `com.auroraclimbing.kilterboard`) has `climb_stats` for climbs up to 2026-01-31. Climb UUIDs carry over (checked: the new API's `climbUuid` matches the old `climbs.uuid` with the same name and setter), so it can be joined to the new data.
- `kilter_dump.py` in this repo implements all of the ✅ calls above.
