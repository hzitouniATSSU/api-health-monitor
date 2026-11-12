# Worker Heartbeat and Staleness Detection

- **Date:** 2026-10-13
- **Status:** implemented in the working tree, uncommitted, not deployed.
- **Addresses:** remaining risk R5 in `PRODUCTION_READINESS_REPORT.md` ("No worker liveness signal").

Before this change, a crashed or hung worker was invisible: the dashboard kept showing the last statuses it had recorded, and nothing reported that monitoring had stopped. The worker now records a heartbeat in PostgreSQL, and the API exposes it at `GET /health/worker`. This lets operators tell these situations apart:

| Situation | `/health/worker` | `status` | `database` | `worker.status` |
|---|---|---|---|---|
| API, database and worker healthy | **200** | `ok` | `ok` | `healthy` |
| Worker running, no monitoring cycle finished since it started | **200** | `ok` | `ok` | `starting` |
| Worker crashed, hung or stopped | **503** | `unavailable` | `ok` | `stale` |
| No worker has ever run against this database | **503** | `unavailable` | `ok` | `missing` |
| Database unreachable | **503** | `unavailable` | `unreachable` | `unknown` |
| Code deployed but migration not applied | **503** | `unavailable` | `ok` | `unknown` (detail says to run `alembic upgrade head`) |

`/health` and `/health/ready` are **unchanged**, and so is the Docker healthcheck. A stale worker never marks the API container unhealthy.

---

## 1. Architecture

```
worker container                     PostgreSQL                         backend (API) container
-----------------                    ----------                         ----------------------
scheduler_loop()
  beat()  ── registration ──────►  worker_heartbeats                 GET /health/worker
  run_monitoring_cycle()             (one row per worker role,          SELECT now();
    load monitors                     all timestamps = DB now())        SELECT * FROM worker_heartbeats
    beat(cycle_started) ────────►                                       → evaluate_worker_health()
    for each due monitor:                                               → 200 / 503 + JSON
      run_check()
      beat() ───────────────────►
    beat(cycle_completed) ──────►
  sleep 10s
```

Code:

| Piece | Location |
|---|---|
| Table model | `backend/app/models/worker_heartbeat.py` |
| Writer (`HeartbeatWriter.beat`), reader (`read_worker_health`), pure classifier (`evaluate_worker_health`) | `backend/app/services/heartbeat.py` |
| Heartbeat calls in the scheduler | `backend/app/services/scheduler.py` |
| Endpoint `GET /health/worker` | `backend/app/main.py` |
| Response schema / status enum | `backend/app/schemas/health.py` |
| Threshold setting | `backend/app/config.py` (`worker_heartbeat_stale_seconds`) |

### Design decisions

1. **PostgreSQL rather than Redis or another service.** The worker and API already share the database, and it is the only state that survives restarts. No new dependency or container.
2. **The database clock is the only clock.** The worker writes timestamps with `now()`, and the API measures age against `now()` read in the same transaction as the row. Clock skew between containers, or between the host and the DB, cannot cause false results. Cycle *duration* uses the worker's monotonic clock, since it never has to be compared across processes.
3. **A heartbeat means progress, not just a running process.** There is no background "I'm alive" task. That kind of task keeps beating while an `await` inside the cycle hangs forever. Instead the worker beats at progress points: at registration, after the monitor list loads, after **each** check (including a failed one), and when the cycle completes. Each check has a hard 10s deadline (F1/F11), so:
   - a *long* cycle (many monitors) keeps producing fresh heartbeats and stays `healthy` (with `cycle_in_progress: true`);
   - a *hung* cycle (blocked event loop, stuck DB statement, an await that never returns) stops beating and becomes `stale`;
   - a cycle that fails before loading monitors (e.g. the DB is down) records no progress.
4. **Restart detection through `instance_id`.** Each worker process has an ID: `<hostname>:<pid>:<random>`, where the hostname is the container ID under Docker. The upsert only changes `started_at` when a *different* instance writes the row. Until that instance completes a cycle, the worker reports `starting`. A cycle the previous instance left unfinished is not reported as in progress.
5. **Heartbeat failures never stop monitoring.** Each beat runs in its own short transaction on its own connection. Any error is logged (`Failed to record heartbeat …`) and ignored. The missing heartbeat is itself the signal.
6. **No separate startup grace period.** The worker registers *before* doing any work, so a restarted worker shows `starting` within milliseconds, not `stale`. The staleness threshold itself absorbs the restart gap during a deploy. A `starting` worker returns **200**, so a long first cycle never alerts. If a starting worker stops beating, `stale` takes precedence over `starting`.
7. **A separate endpoint, not part of readiness.** Containers are restarted only when the process exits (`restart: unless-stopped`), and the backend healthcheck uses `/health/ready`. Putting worker state into readiness would mark the API unhealthy for a problem the API cannot fix. It would also hide the difference between "database down" and "worker down".
8. **One row per worker role** (`worker_name = 'monitoring'`), not one row per process. The table stays at one row with no clean-up job. The cost is covered in §6 (multiple workers).

---

## 2. Database changes

Migration **`229c4aa5a0ca`** (`create worker heartbeats table`), down-revision `76fda49ca121`. It is purely additive: it creates one new table and leaves the existing tables alone.

```sql
CREATE TABLE worker_heartbeats (
    worker_name              VARCHAR(50)  NOT NULL PRIMARY KEY,
    instance_id              VARCHAR(255) NOT NULL,
    started_at               TIMESTAMPTZ  NOT NULL,
    last_heartbeat_at        TIMESTAMPTZ  NOT NULL,
    last_cycle_started_at    TIMESTAMPTZ,
    last_cycle_completed_at  TIMESTAMPTZ,
    last_cycle_duration_ms   INTEGER,
    last_cycle_monitor_count INTEGER
);
```

- Downgrade: `DROP TABLE worker_heartbeats;`
- Write volume: one single-row `INSERT … ON CONFLICT DO UPDATE` per beat. That is about 2 per 10s idle tick plus 1 per check, or roughly 17k updates/day with no monitors due. They are updates of one tiny row, which autovacuum handles easily. No indexes beyond the primary key.
- Migration takes a brief lock only on the new table, so it is safe while the old code runs.

---

## 3. Heartbeat frequency and staleness thresholds

| Parameter | Value | Where |
|---|---|---|
| Scheduler tick (idle sleep between cycles) | 10s | `SCHEDULER_TICK_SECONDS` |
| Beats per cycle | 2 + one per due monitor | scheduler |
| Max gap between beats, idle | ≈ 10s | tick |
| Max gap between beats, during a check | ≈ 10s check deadline + DB commit + alert send (Resend's synchronous call, up to its 30s default timeout, R13) ≈ **40–45s** | `checker.py`, `alerts.py` |
| **Staleness threshold** | **120s** by default, configurable, **minimum 30s** | env `WORKER_HEARTBEAT_STALE_SECONDS`, read by the **backend** (API) container |

Rules:

- Status is `stale` when `heartbeat_age_seconds > threshold`. An age **exactly at** the threshold still counts as healthy (covered by boundary tests).
- 120s is about 3× the worst-case normal gap, and long enough to cover a `docker compose up -d` worker restart. Lower it only if you also lower the check and alert timeouts. The 30s floor is enforced when settings load: any process given a smaller value refuses to start, and that includes the worker if the variable is set there too. The floor exists because anything near the 10s tick makes a healthy idle worker flap to `stale`.
- The threshold is read only by the API. The worker doesn't need it. Changing it requires restarting the backend container only.
- A heartbeat committed just after the reader's transaction began can look a few milliseconds in the future. Its age is clamped to 0.

---

## 4. Operational monitoring

### Response

```json
{
  "status": "ok",
  "database": "ok",
  "worker": {
    "status": "healthy",
    "detail": "Worker heartbeat is fresh.",
    "stale_after_seconds": 120,
    "checked_at": "2026-10-13T19:45:35.120Z",
    "heartbeat_age_seconds": 3.475,
    "instance_id": "3f2a9c1b7d4e:1:3579ef8c",
    "started_at": "…",
    "last_heartbeat_at": "…",
    "last_cycle_started_at": "…",
    "last_cycle_completed_at": "…",
    "last_cycle_duration_ms": 42,
    "last_cycle_monitor_count": 7,
    "cycle_in_progress": false
  }
}
```

Every field is always present (`null` when unknown), so clients can parse the 200 and 503 bodies the same way.

### How to watch it

`/health/worker` is **not reachable from outside yet.** Caddy proxies only the exact path `/health` (see R9). Options, roughly in order of effort:

1. **On the host** (works today). Run from cron or a systemd timer, and alert when the exit code is non-zero:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
     python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/worker', timeout=5)"
   ```
2. **External uptime monitor.** Add `/health/worker` (or `/health/*`) to the Caddyfile's health route and decide whether it sits behind basic auth (R9). Validate with `caddy validate` before deploying.
3. Use `instance_id` changes as a crash-loop signal. Several different IDs within a few minutes mean the worker keeps restarting.

**Alert on 2+ consecutive failures**, not a single probe. That avoids paging on a transient DB blip or a host reboot during which the worker hasn't reconnected yet.

### Logs

| Log line | Container | Meaning |
|---|---|---|
| `Worker instance <id> registering heartbeat` | worker | Process started; one per start |
| `Failed to record heartbeat for worker=monitoring instance=…` (WARNING, with traceback) | worker | Heartbeat write failed (DB down, or table missing). Checks continue |
| `Worker health check: status=stale detail=…` (WARNING) | backend | A probe saw a stale/missing worker |
| `Worker health check failed: worker_heartbeats table is missing…` (ERROR) | backend | Migration `229c4aa5a0ca` not applied |
| `Worker health check failed: database unreachable` (ERROR) | backend | DB connection or query failed |

### Ad-hoc SQL

```sql
SELECT worker_name, instance_id, started_at,
       now() - last_heartbeat_at AS heartbeat_age,
       last_cycle_completed_at, last_cycle_duration_ms, last_cycle_monitor_count
FROM worker_heartbeats;
```

---

## 5. Failure scenarios

| Scenario | What happens | Reported as |
|---|---|---|
| Normal operation, any number of monitors (including **zero**) | Every 10s tick writes cycle-start and cycle-complete beats, even if nothing is due | `healthy` |
| Long cycle (many monitors, slow endpoints) | One beat per check keeps the age at ≤ ~45s | `healthy`, `cycle_in_progress: true` |
| Long *first* cycle after a restart | Beats continue; no cycle completed yet | `starting` (200) |
| Worker process crashes / OOM-killed / `docker stop` | Beats stop | `stale` after the threshold |
| Worker crash loop | Each start re-registers; it may briefly look `starting`, then `stale` if it never stays up | `starting` ↔ `stale`; `instance_id` keeps changing |
| Worker hung: blocked event loop, stuck DB statement, an await that never returns | Beats stop (no background beat task to hide it) | `stale` |
| Check raises an exception | Logged as before; a beat is still written after it | `healthy` |
| DB unreachable from the worker | Cycle fails before loading monitors; no progress beats; heartbeat writes log warnings | API side: `database: unreachable` if the API can't reach it either, otherwise `stale` |
| DB unreachable from the API | Readiness and worker health both 503; worker health says `unknown` | `database: unreachable` |
| Heartbeat table missing (code before migration) | Worker logs heartbeat failures but **keeps checking monitors**; API returns a clear "apply migrations" message | `unknown`, `database: ok` |
| Worker started before the table exists, migration applied later | The next beat creates the row. No restart needed | `healthy` after the next cycle |
| Container clock skew | Irrelevant: only the DB clock is used | — |
| Deploy (`dc up -d` recreates the worker) | The old instance stops; the new one registers within seconds; the gap is far below 120s | `starting` → `healthy`, no 503 |
| Host reboot | The DB comes up first; until the worker reconnects, the old row looks stale | possibly `stale` for one probe, hence "alert on 2+ failures" |

Verified end-to-end against a local PostgreSQL 17 with the real worker process. Outcomes: code before migration (`unknown`, worker kept cycling); migrated but worker never started (`missing`); running (`healthy`); `kill -9` (`stale`); restart (new `instance_id`, `healthy`).

---

## 6. Known limitations

- **Single worker assumed (R7).** Two workers would overwrite the same row and keep swapping `instance_id`, so the worker would mostly look `starting`. That is a visible symptom, but not an explicit "duplicate worker" error. Keep exactly one worker.
- **Heartbeat ≠ correct results.** A worker that beats but records wrong outcomes (bad DNS, all checks timing out) still looks `healthy`. The dashboard's per-monitor `last_checked_at` and incidents cover that.
- **No alerting is wired up.** This change provides the signal. Polling and paging still need to be set up (§4).
- **`/health/worker` has no DB connect timeout** (same as R15 for readiness). If the database host stops answering instead of refusing connections, a probe can hang until the OS TCP timeout. Use a client-side timeout (the command in §4 uses 5s).

---

## 7. Deployment requirements

1. **Apply migration `229c4aa5a0ca`.** The deploy runbook's migration step (`dc run --rm backend python -m alembic upgrade head`) now has work to do. Expect `alembic current` to print `229c4aa5a0ca (head)`.
2. **Order is flexible.** Migration-then-code is the normal path. The old code ignores the new table. Code-then-migration is also safe: the worker keeps checking, and `/health/worker` explains what's missing.
3. **Optional config:** set `WORKER_HEARTBEAT_STALE_SECONDS` on the **backend** service only if you need a value other than 120 (minimum 30). The compose files don't need to change.
4. **No change** to Docker healthchecks, restart policies, Caddy, the frontend or dependencies.
5. **Expect a short `missing` period** between the migration and the new worker's first beat. Don't enable alerting on `/health/worker` until after rollout.
6. **Post-deploy verification:**
   ```bash
   dc exec backend python -c "import urllib.request, json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/worker', timeout=5))['worker']['status'])"
   # expect: healthy (or starting for the first cycle)
   dc logs --since 5m worker | grep -E "registering heartbeat|Failed to record heartbeat"
   # expect: one "registering" line and no "Failed to record heartbeat"
   ```

---

## 8. Rollback considerations

- **Code-only rollback is the recommended path.** The previous code doesn't know the table exists. Leave the table in place: it is a single row and does no harm. If you roll forward again later, the heartbeat keeps working without another migration.
- **Schema rollback** is only needed if the table itself causes a problem:
  ```bash
  dc run --rm backend python -m alembic downgrade 76fda49ca121
  ```
  This drops `worker_heartbeats` and loses only heartbeat history, no monitoring data. Roll back the **code first**, then downgrade. Otherwise the running new code logs a heartbeat failure every few seconds and `/health/worker` returns `unknown`. Monitoring itself keeps working.
- Remove any external alerting on `/health/worker` before rolling back the code, because the endpoint will return 404.
- A downgrade and upgrade round trip was verified on the local test database (`downgrade -1`, `upgrade head`, `downgrade base`, `upgrade head`, `alembic check` clean).

---

## 9. Tests

38 new tests (95 total, up from 57):

- `tests/test_heartbeat.py`
  - Pure classification: fresh, stale, missing; threshold boundary just below / at / just above; configured threshold; starting (never completed); restart with an older completed cycle; the previous instance's unfinished cycle not counted as in progress; stale beats starting; long cycle healthy; long first cycle starting; a future timestamp clamped; threshold validation (≥ 30).
  - Against the test DB: missing row; registration → starting; full cycle → healthy with cycle details; same-instance beats keep `started_at`; aged timestamps → stale; worker restart (new instance → starting → healthy); long cycle in the DB; heartbeat write failure logged, not raised.
  - Scheduler: zero monitors still beat and complete; one beat per check, including a failing check; a failed cycle records no progress; the loop registers before the first cycle.
- `tests/test_health.py`: `/health/worker` fresh (200), stale (503), configured threshold, missing (503), starting (200), database unavailable (exact body), unapplied migration (503 with an `alembic upgrade head` hint), and a stale worker leaving `/health` and `/health/ready` unaffected.
