# Production Readiness Report — API Health Monitor

- **Date:** 2026-10-13
- **Baseline commit:** `1a9690d` (main)
- **Scope:** FastAPI backend, monitoring worker, PostgreSQL/Alembic, React dashboard, Docker Compose + Caddy deployment, GitHub Actions CI.
- **Status of changes:** uncommitted in the working tree, pre-merge review done (§7). Worker heartbeat added afterwards (§8, design in `WORKER_HEARTBEAT.md`). Nothing has been committed, pushed or deployed.

Each finding is labeled **Confirmed** (reproduced in this audit) or **Hypothetical** (a risk identified by reading the code, not reproduced).

---

## 1. Initial findings and severity

| # | Severity | Status | Finding | Evidence |
|---|---|---|---|---|
| F1 | **High** | Confirmed | **The check timeout is not a total deadline.** httpx timeouts apply to each network operation, so a server that trickles response bytes can keep a check open indefinitely. The worker checks monitors one after another, so one slow or hostile endpoint delays checks for every other monitor. Each check can also follow up to 5 redirects, each with its own timeouts. | A local server sending one header line every 0.5s held an `httpx` request with `timeout=1.0` open for **4.0s**. |
| F2 | **Medium** | Confirmed | **Invalid input returns HTTP 500.** `POST /api/monitors` accepted names over 100 characters and URLs over 2048 characters (the column sizes), so the database raised and the API returned a 500. Empty and whitespace-only names were stored. | Probes: 101-char name → 500; 2070-char URL → 500; `""` and `"   "` → 201. A URL that is exactly 2048 chars as sent becomes 2049 after `HttpUrl` normalization (`.com?` → `.com/?`). |
| F3 | **Medium** | Confirmed | **SSRF filter gap.** `_is_unsafe_ip` did not block 100.64.0.0/10 (RFC 6598 shared/CGNAT space). This range is not "private" in Python's classification but is not publicly routable either. It can be used inside AWS VPCs (secondary CIDRs), and some cloud providers put metadata endpoints in it (e.g. `100.100.100.200`). | `_is_unsafe_ip("100.64.0.1") == False`. |
| F4 | **Medium** | Confirmed | **An alert failure was reported as a failed check.** `run_check` commits the check and status change, then calls Resend. If Resend raised, the exception escaped and the worker logged `Failed to check monitor`. The real failure was the email, not the check. The DOWN alert is lost with no retry. | Code path `services/monitoring.py`; regression test added. |
| F5 | **Medium** | Confirmed | **Deleting a monitor loaded all of its history into memory.** The ORM cascade ignored the database's `ON DELETE CASCADE`: it SELECTed every check and incident, then deleted checks by primary key. History grows by ~288 rows/day per monitor, so deletes keep getting slower and use more memory. | Statement trace of `DELETE /api/monitors/{id}` with 5,000 checks: `SELECT checks…`, `SELECT incidents…`, `DELETE FROM checks WHERE checks.id = …`. |
| F6 | **Medium** | Confirmed | **No readiness signal.** `/health` returns `ok` even when the database is unreachable. Containers had no healthcheck, so `docker compose ps` could not show a broken backend. | `main.py`; compose files. |
| F7 | **Medium** | Confirmed | **The backend container runs as root in production.** The worker was hardened (uid 10001, `cap_drop: ALL`, `no-new-privileges`) but the internet-facing API was not. | `docker-compose.prod.yml`. |
| F8 | Low | Confirmed | **`backend/requirements.txt` was UTF-16LE with CRLF line endings.** pip handles the BOM (verified), but git treats the file as binary. Diffs, code review, grep and dependency scanners (Dependabot etc.) can't read it. | `file` reports UTF-16; `git diff` shows `Bin`. |
| F9 | Low | Confirmed | No deployment, migration or rollback documentation exists. There is no root README, and nothing runs `alembic upgrade` on deploy. | Repository contents. |
| F10 | Low | Confirmed | One unused import (`ipaddress` in `app/core/safe_network.py`). CI has no backend lint step. | `ruff check --select E9,F`. |
| F11 | Medium | Confirmed (found in pre-merge review) | **The F1 deadline did not cover DNS.** `validate_public_url` calls `getaddrinfo` synchronously inside the async check. `asyncio.timeout` cannot interrupt blocking code, so a slow resolver (e.g. an attacker-controlled nameserver) blocked the worker's event loop and overran the deadline. | Simulated 1.5s DNS stall with a 0.2s deadline: took **1.51s** and reported **success**. |
| F12 | Medium | Confirmed (found in pre-merge review) | **Runbook defects** in the first version of §6: `DC="docker compose …"; $DC …` fails under zsh (`command not found`, since zsh does not word-split variables). The curl examples put the basic-auth password in shell history and the process list, and used variables that exist only in `.env`. Backups were written with the default umask. The SSRF pre-check was not concrete. | Reproduced the zsh failure. Reviewed each command against the compose files. |
| — | Info | Verified **not** an issue | **CSRF against basic-auth sessions.** Cross-site `text/plain` and form POSTs get 422 (FastAPI only parses JSON bodies with a JSON content type). Cross-origin `DELETE` preflights from foreign origins are rejected. | Probed with TestClient. |
| — | Info | Verified **not** an issue | **DNS rebinding.** `SafeNetworkBackend` re-resolves the host at connect time, rejects the request if any resolved address is unsafe, and connects to the validated IP. TLS SNI and certificate checks still use the hostname. | Code review + existing tests. |

---

## 2. Changes implemented

All changes are small and covered by tests. No new dependencies. The hardening changes in this table have no schema changes. **The worker heartbeat (§8) adds one migration, `229c4aa5a0ca`, which creates a new table.**

| Fixes | Change | Files |
|---|---|---|
| F1, F11 | `check_url` wraps the whole check, including redirects, in `asyncio.timeout(timeout_seconds)` (10s by default). An overrun returns `error_type="timeout"`. URL validation, which does the DNS lookup, now runs via `asyncio.to_thread` so the deadline covers it and the event loop is never blocked. (Connect-time DNS in `SafeNetworkBackend` already used a thread.) | `backend/app/services/checker.py` |
| F2 | `MonitorCreate.name` is stripped of surrounding whitespace and must be 1–100 chars. `url` must be ≤ 2048 chars **after** normalization. Invalid input gets 422 instead of 500. The dashboard form now sets `maxLength` to match. | `backend/app/schemas/monitor.py`, `frontend/src/App.tsx` |
| F3 | An address is unsafe if it is **not `is_global`**, in addition to the existing checks. This covers 100.64.0.0/10 and similar special-purpose ranges. Verified that public IPv4/IPv6 addresses (8.8.8.8, 1.1.1.1, 2606:4700::1111, 2001:4860:4860::8888) are still allowed. | `backend/app/core/url_safety.py` |
| F4 | Sending an alert after the commit is wrapped in `try/except`. A failure is logged as `Failed to send DOWN/recovery alert for monitor id=…` and the check result is still returned. | `backend/app/services/monitoring.py` |
| F5 | `passive_deletes=True` on `Monitor.checks` / `Monitor.incidents`, so PostgreSQL's existing `ON DELETE CASCADE` removes child rows. `alembic check` confirms the models still match the migrations. | `backend/app/models/monitor.py` |
| F6 | New `GET /health/ready` runs `SELECT 1`. Returns `200 {"status":"ok","database":"ok"}`, or `503 {"status":"unavailable","database":"unreachable"}`. `/health` is unchanged. | `backend/app/main.py` |
| F6, F7 | Prod backend runs as `10001:10001` with `cap_drop: ALL` and `no-new-privileges`, the same as the worker. Added a Docker healthcheck against `/health/ready` that uses the image's Python, since curl is not in `python:3.13-slim`. | `docker-compose.prod.yml` |
| F8 | `requirements.txt` re-encoded to UTF-8 with LF line endings. The package list is identical, line for line (37 pins). | `backend/requirements.txt` |
| F12 | §6 rewritten. Uses a `dc()` shell function (works in bash and zsh). curl prompts for the password instead of taking it as an argument. Backups are written under `umask 077`. Adds a concrete, read-only scan for monitors the new SSRF rule will fail. Notes that `docker compose config` without `--quiet` prints secrets. | this document |

### API behavior changes (intentional, review before merging)

1. `POST /api/monitors` now returns **422** (was 500) for names over 100 chars and URLs over 2048 chars, and **422** (was 201) for empty or whitespace-only names. Names are now stored trimmed. The dashboard already trimmed names and required the field, so normal UI use is unaffected. Existing rows are not touched.
2. **Existing monitors whose hostname resolves into a non-global range such as 100.64.0.0/10 will now fail checks with `error_type="unsafe_url"`**, which opens an incident and sends a DOWN alert. Before deploying, run the scan in §6 step 6 to see if any exist.
3. A check stopped by the overall deadline is recorded as `error_type="timeout"` (same as before) with the message `Check exceeded 10s deadline`.
4. New endpoint `/health/ready`. Note: Caddy only proxies the exact path `/health`, so `/health/ready` is **not reachable from outside**. It is used by the container healthcheck. See remaining risks R9.

### Not changed (deliberately)

- **No auto-migration on container start.** That is a design decision (concurrent replicas, failure modes), so it is documented in the runbook instead.
- **Caddyfile unchanged.** Caddy isn't installed locally, so a change could not be validated.
- The pre-existing unused import (F10) was left alone to keep the diff focused.

---

## 3. Test results

Environment: macOS, Python 3.13.15, local PostgreSQL 17.10 (CI uses `postgres:17`). Tests ran against the `healthmonitor_test` database (`TEST_DATABASE_URL=postgresql+psycopg://mac@localhost:5432/healthmonitor_test`). Docker is **not** installed on this machine.

| Check | Result |
|---|---|
| Baseline backend suite (before changes) | 37 passed |
| New regression tests against the unchanged code | **12 failed**, as expected (each reproduces one finding) |
| Full backend suite after changes (first pass) | 50 passed, 3 consecutive runs |
| Pre-merge review: new slow-DNS test against the first-pass code | **1 failed**, as expected (F11) |
| **Full backend suite, final** | **57 passed**, 1 pre-existing warning (Starlette TestClient/httpx deprecation) |
| SSRF pre-deploy scan script (§6 step 6), run against the test DB | Reported the seeded `100.64.1.2` monitor, skipped the public one |
| `alembic check` | `No new upgrade operations detected.` |
| `alembic downgrade base` → `upgrade head` (test DB) | Succeeded; at head `76fda49ca121` |
| `ruff check --select E9,F` (run from a scratch venv, not added to the project) | Changed files clean. One pre-existing F401 (F10) |
| Frontend `npm run lint` / `npm run build` | Pass / pass (existing chunk-size warning only) |
| `pip install --dry-run -r requirements.txt` after re-encoding | Resolves |
| End-to-end deadline check (`check_url(timeout=1.0)` against a trickling server) | Returns after **1.0s** with `error_type='timeout'` (was 4.0s+) |
| Container healthcheck command, run against a local uvicorn | `{"status":"ok","database":"ok"}`, exit 0 |
| `docker-compose.prod.yml` | Parses as YAML with `!reset` tags. **`docker compose config` NOT run (Docker unavailable): run it before deploying.** |

New tests:

- `tests/test_checker.py::test_slow_response_is_bounded_by_total_deadline`, `test_slow_dns_validation_is_bounded_by_total_deadline`
- `tests/test_monitors.py::test_create_monitor_rejects_invalid_fields[5 cases]`, `test_create_monitor_strips_name_whitespace`, `test_create_monitor_accepts_values_at_column_limits`, `test_delete_monitor_relies_on_database_cascade`
- `tests/test_monitoring.py::test_alert_failure_does_not_fail_the_check`, `test_recovery_alert_failure_does_not_fail_the_check`
- `tests/test_url_safety.py::test_private_addresses_are_rejected[100.64.0.1, 100.100.100.200]`, `test_public_ipv4_and_ipv6_addresses_are_allowed[4 cases]` (guards against over-blocking)
- `tests/test_health.py::test_readiness_checks_database`, `test_readiness_reports_database_failure`

**Deployment health was not verified.** I did not access the EC2 host, production secrets, or the production database.

---

## 4. Remaining risks

| # | Severity | Risk | Notes / suggested fix |
|---|---|---|---|
| R1 | High | **Caddy basic auth is the only authentication.** The API itself has none. Anything that reaches `backend:8000` on the Docker network (another container, or a misconfigured port mapping) gets full read/write/delete access. | Fine for one operator. Add app-level auth (API token or session) before multiple users or any exposure beyond Caddy. |
| R2 | Medium | **Alerts are fire-and-forget.** A failed Resend call is now logged, but the DOWN alert is never retried, and no alert is sent if the worker crashes between commit and send. | Add an `alert_pending` / outbox column and retry from the scheduler (needs a migration). |
| R3 | Medium | **Checks run one at a time.** A cycle takes up to N × 10s. Above roughly 30 monitors, the 5-minute interval slips. | Run checks concurrently with a bounded semaphore and a short-lived session per check. |
| R4 | Medium | **Check history grows forever.** `checks` only has an index on `monitor_id`. `/stats` counts the whole history on every dashboard refresh, and `/checks` sorts all of a monitor's rows. | Add a migration for an index on `checks(monitor_id, checked_at DESC)`, plus a retention job (e.g. 90 days). |
| R5 | Medium → **Low** | ~~No worker liveness signal.~~ **Signal implemented (§8):** a DB-backed heartbeat and `GET /health/worker`. **Still open:** nothing polls the endpoint or alerts yet, and Caddy does not route it (R9). | Set up the host-side probe or an external monitor from `WORKER_HEARTBEAT.md` §4. Alert on 2+ consecutive failures. |
| R6 | Medium | **No automated backups confirmed.** The `postgres_data` volume is the only copy of the data, as far as the repo shows. | Nightly `pg_dump` to S3, or EBS snapshots. Test a restore. |
| R7 | Medium | **Running two workers would duplicate checks and incidents.** Nothing enforces a single worker. | Document the single-worker rule, or use `SELECT … FOR UPDATE SKIP LOCKED` / an advisory lock. |
| R8 | Low | **Floating base image tags** (`postgres:17`, `caddy:2`, `nginx:alpine`, `python:3.13-slim`). Rebuilds are not reproducible. | Pin by digest, plus Renovate/Dependabot. Dev/test tools (`pytest`, `watchfiles`, …) also ship in the prod image. |
| R9 | Low | `/health/ready` is not routed by Caddy, and Caddy's basic auth also covers `/health`, so an external uptime monitor needs credentials. | Add `@health path /health /health/*` and decide whether health endpoints sit behind auth. Validate with `caddy validate`. |
| R10 | Low | **No HTTP security headers** (HSTS, `X-Content-Type-Options`, CSP, `Referrer-Policy`). | Add a `header` block in the Caddyfile. |
| R11 | Low | **CI gaps:** no backend lint/type check, no Docker image build, no `docker compose config` validation, no migration drift check (`alembic check`). | Add these as CI steps. |
| R12 | Low | **Some tests need real DNS** (e.g. `test_successful_check` resolves `example.com`), so they fail offline. | Monkeypatch `validate_public_url` in those tests. |
| R13 | Low | **Resend calls block the event loop** for up to 30s, its default timeout. Harmless in the current sequential worker; matters once R3 is done. | Use `asyncio.to_thread` or Resend's async client. |
| R15 | Low | **`/health/ready` has no database connect timeout.** If the database host stops answering instead of refusing connections, the probe hangs until the OS TCP timeout. The Docker healthcheck still fails after 5s, but each probe holds a threadpool thread until then. | Add `connect_args={"connect_timeout": 5}` to `create_engine`. Affects every connection, so it is a separate, deliberate change. |
| R16 | Low | **"unhealthy" does not trigger a restart.** `restart: unless-stopped` only reacts to the process exiting, so the new healthcheck makes failures visible but doesn't fix them. | Alert on container health, or use an autoheal sidecar. |
| R17 | Low | **The non-root backend and worker depend on host file permissions.** Files are copied into the image with their build-context modes. A host checkout made under a restrictive umask (e.g. `027`) would be unreadable by uid 10001. All 47 tracked backend files are `100644`. §6 step 6 runs the app as uid 10001 before rollout, which catches this. | Add `RUN chmod -R a+rX /app` in the Dockerfile, or create the user in the image. |
| R14 | Hypothetical | **`$` in the bcrypt basic-auth hash.** Compose interpolates `.env` values, and bcrypt hashes contain `$`. | Keep `BASIC_AUTH_HASH` single-quoted in `.env`, or escape `$` as `$$`. Confirm with `docker compose config`. |

---

## 5. Recommended next milestones

1. **Ship this change set** (§6), then confirm one full monitoring cycle in the worker logs and `healthy` status on the backend container.
2. **Data durability:** automated, tested backups (R6).
3. **Observability:** wire alerting to `/health/worker` (R5, signal done in §8), external uptime monitoring of the monitor itself, and structured JSON logs.
4. **Database scaling:** `(monitor_id, checked_at)` index migration and a retention job (R4).
5. **Reliable alerting:** an outbox with retries (R2), then concurrent checks (R3) with R13.
6. **CI hardening** (R11), plus image pinning and dependency updates (R8). Split `requirements.txt` into runtime and dev files.
7. **Authentication** inside the app (R1), if the tool will be shared.

---

## 6. Deployment and rollback instructions

These steps assume the existing EC2 layout:

- the repository checked out on the host;
- a root-level `.env` (read by Compose, not by your shell) holding `POSTGRES_PASSWORD`, `DATABASE_URL`, `SITE_DOMAIN`, `BASIC_AUTH_USER`, `BASIC_AUTH_HASH`, and optionally `RESEND_*`/`ALERT_*`;
- deployment with both compose files.

Adjust paths if your host differs. Commands work in bash and zsh. Run them from the repository root on the EC2 host.

```bash
# Helper used below. A function, not a variable: zsh does not word-split "$VAR".
dc() { docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
```

**Credential hygiene:**

- Never put the basic-auth password on a command line. `curl -u <user>` prompts for it.
- Do not run `dc config` without `--quiet` in a shared terminal or CI log. It prints the interpolated secrets from `.env`.
- Database dumps contain all monitor data. Write them with `umask 077` and keep them off shared storage.

### Deploy

1. **Record the current revision** for rollback:
   ```bash
   git rev-parse HEAD | tee ~/pre-deploy-rev.txt
   ```
2. **Back up the database.** This release adds a table (migration `229c4aa5a0ca`, additive only). Always back up first:
   ```bash
   (umask 077; dc exec -T db pg_dump -U healthmonitor -d healthmonitor -Fc > ~/healthmonitor-$(date +%Y%m%d%H%M).dump)
   ls -l ~/healthmonitor-*.dump      # expect -rw------- and a non-trivial size
   ```
3. **Fetch the reviewed change**, once it is committed and merged. Use your usual method, e.g.:
   ```bash
   git fetch origin && git checkout <reviewed-commit-sha>
   ```
4. **Validate the merged configuration.** This could not be checked locally (no Docker), so do not skip it:
   ```bash
   dc config --quiet && echo "compose OK"
   ```
5. **Build images.** Running containers are not touched yet:
   ```bash
   dc build backend worker frontend
   ```
6. **Pre-flight with the new image** (read-only). This lists existing monitors that the stricter SSRF rule will mark DOWN (behavior change 2). It also confirms that uid 10001 can read the app files (R17), because `run` uses the prod `user:`:

```bash
dc run --rm -T backend python - <<'EOF'
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Monitor
from app.core.url_safety import UnsafeURLError, validate_public_url
with SessionLocal() as db:
    for m in db.scalars(select(Monitor).order_by(Monitor.id)):
        try:
            validate_public_url(m.url)
        except UnsafeURLError as exc:
            print(f"WILL FAIL id={m.id} name={m.name!r} url={m.url} reason={exc}")
print("scan complete")
EOF
```

   Expect `scan complete`. Each `WILL FAIL` line is a monitor that will report DOWN and send an alert after rollout: decide whether to delete it or accept that. A `PermissionError`/`ImportError` here means stop and see R17.
7. **Apply migrations.** This release adds `76fda49ca121 → 229c4aa5a0ca` (creates `worker_heartbeats`). Expect `alembic current` to print `229c4aa5a0ca (head)`. Running the old containers is safe while this runs. Keep this step in every deploy:
   ```bash
   dc run --rm backend python -m alembic upgrade head
   dc run --rm backend python -m alembic current
   ```
8. **Roll out.** This recreates the changed containers, with a brief interruption:
   ```bash
   dc up -d
   ```
9. **Verify:**
   ```bash
   dc ps        # backend should show "(healthy)"; the first probe runs ~30s after start
   dc exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read())"
   dc exec backend id -u                     # expect 10001
   curl -fsS -u <basic-auth-user> https://<your-domain>/health          # prompts for the password
   curl -fsS -u <basic-auth-user> https://<your-domain>/api/monitors | head -c 300
   dc logs --since 5m worker | grep -E "Monitoring cycle|Checked monitor|Failed"
   dc exec backend python -c "import urllib.request, json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/worker', timeout=5))['worker'])"
   ```
   Expected: backend `healthy`; readiness `{"status":"ok","database":"ok"}`; `id -u` prints `10001`; `/health` returns `{"status":"ok"}`; worker logs show `Monitoring cycle: N monitor(s)` about every 10s with no repeated `Failed to check monitor`; worker health shows `'status': 'healthy'` (or `starting` during the first cycle), and the worker log has one `registering heartbeat` line and no `Failed to record heartbeat`. `Failed to send … alert` means Resend configuration or delivery is broken, not that the check failed.

### Rollback

This release ships one additive migration (`229c4aa5a0ca`). **Roll back the code only and leave the `worker_heartbeats` table in place.** The previous code ignores it. Downgrading the schema is optional; see `WORKER_HEARTBEAT.md` §8. If you do it, roll back the code first, then run `dc run --rm backend python -m alembic downgrade 76fda49ca121`.

```bash
git checkout "$(cat ~/pre-deploy-rev.txt)"   # detached HEAD; return to your branch after the incident
dc build backend worker frontend
dc up -d
dc ps
dc logs --since 5m worker | tail -20
```

After rollback, the backend runs as root again and has no healthcheck, as before. `/health` is unchanged throughout. Monitor names saved trimmed by the new code stay trimmed, which is harmless.

**Restoring data** is needed only if data was corrupted, which this change should not cause. `--clean` drops and recreates objects, so confirm you have the right dump first:
```bash
dc stop backend worker
dc exec -T db pg_restore -U healthmonitor -d healthmonitor --clean --if-exists < ~/healthmonitor-<timestamp>.dump
dc start backend worker
```

### Running the test suite locally

```bash
cd backend
export TEST_DATABASE_URL=postgresql+psycopg://<user>@localhost:5432/healthmonitor_test   # the DB name must be healthmonitor_test
DATABASE_URL=$TEST_DATABASE_URL python -m alembic upgrade head
python -m pytest -q
```

---

## 7. Pre-merge review (2026-10-13)

I reviewed the full working-tree diff for regressions, container hardening, runbook accuracy and credential handling.

- **Fixed:** F11 (DNS escaped the deadline) and F12 (runbook defects). Added the missing tests: values accepted at each limit, public IPv4/IPv6 not over-blocked, recovery-alert failure. The deadline test no longer needs real DNS.
- **Checked and found sound:**
  - non-root backend: port 8000 needs no capabilities, `PYTHONDONTWRITEBYTECODE=1` means no writes under `/app`, and the worker already runs this way in production;
  - healthcheck: exec form; Python's `urlopen` raises on 503, so the probe exits non-zero;
  - `passive_deletes`: unchanged schema, cascade covered by a test;
  - alert logging doesn't include credentials;
  - no shell scripts in the repo; CI credentials are only for its throwaway Postgres service;
  - `.env` files are git- and docker-ignored.
- **Not verifiable here:** anything that needs Docker or Caddy: `docker compose config`, image builds, running containers as uid 10001.

### Release blockers

The code has no blockers. These must happen at deploy time:

1. **`dc config --quiet` must pass on the host** (§6 step 4). The compose changes have only been checked as YAML.
2. **Run the pre-flight scan** (§6 step 6). Act on any `WILL FAIL` monitors before rollout, so the stricter SSRF rule doesn't trigger unexpected DOWN alerts.
3. **A verified backup must exist** before rollout (§6 step 2).

---

## 8. Worker heartbeat and staleness detection (2026-10-13, addresses R5)

Full design, thresholds, failure scenarios and runbook: **`docs/WORKER_HEARTBEAT.md`**. Uncommitted, not deployed.

### Summary

- The worker upserts one row in the new `worker_heartbeats` table at registration, at cycle start, after **each** check, and at cycle end. All timestamps come from the database clock.
- New `GET /health/worker` returns 200 for `healthy` / `starting` and 503 for `stale` / `missing` / `unknown`, and keeps `database` and `worker` state separate. The threshold is `WORKER_HEARTBEAT_STALE_SECONDS` (default 120, minimum 30).
- **Unchanged:** `/health`, `/health/ready`, the Docker healthcheck, restart policies, Caddy, dependencies. A test confirms that a stale worker leaves liveness and readiness at 200.

### Findings from this work

| # | Severity | Status | Finding | Resolution |
|---|---|---|---|---|
| F13 | Medium | Confirmed | **A background "alive" heartbeat would hide hangs.** The worker's checks are `await`s. A timer task keeps beating while a cycle awaits something that never returns. | Heartbeats are written only at progress points (per check). A hung cycle goes quiet and is reported `stale`. A long but progressing cycle stays `healthy`. Tested both. |
| F14 | Low | Confirmed | **A small threshold makes healthy workers flap.** End-to-end with a 5s threshold, an idle healthy worker read `stale` between its 10s ticks. | The setting is validated `≥ 30`. The default of 120s is about 3× the worst-case normal gap (10s check deadline + Resend's 30s blocking timeout). |
| F15 | Low | Confirmed | **Deploy order risk: code before migration.** Without handling, the missing table would make `/health/worker` claim the database was unreachable. | The API detects SQLSTATE `42P01` and reports `database: ok`, worker `unknown`, with an `alembic upgrade head` hint. Heartbeat write errors are logged, and the worker **keeps checking monitors** (verified with the real worker process). |
| F16 | Low | Confirmed (local environment) | The local test instructions in §6 assume a `healthmonitor_test` DB reachable on `localhost:5432`. On this machine that Homebrew cluster has no `healthmonitor` role, so the suite errors (17 errors, 5 failures). | Not a code issue. Tests ran against a throwaway PostgreSQL 17.10 cluster in a scratch directory (port 55432). The existing cluster was not modified. |

### Validation

| Check | Result |
|---|---|
| Baseline suite before changes (scratch test DB) | 57 passed |
| **Full backend suite after changes** | **95 passed** (38 new), 3 consecutive runs, 1 pre-existing warning |
| `alembic upgrade head` / `alembic check` | Head `229c4aa5a0ca`; `No new upgrade operations detected.` |
| Round trip `downgrade -1` → `upgrade head` → `downgrade base` → `upgrade head` | Succeeded |
| Offline SQL (`upgrade --sql`) | One `CREATE TABLE worker_heartbeats`; no changes to existing tables |
| End-to-end, real `python -m app.worker` against a scratch DB | Before migration: 503 `unknown`, worker kept cycling. Migrated, no worker: 503 `missing`. Running: 200 `healthy`. `kill -9`: 503 `stale`. Restart: new `instance_id`, 200 `healthy` |
| `ruff check --select E9,F` on changed/new files | Clean |

### New remaining risks

| # | Severity | Risk | Notes / suggested fix |
|---|---|---|---|
| R18 | Medium | **The heartbeat isn't watched yet.** The endpoint reports staleness, but nothing alerts on it, and Caddy doesn't route `/health/worker`. | Host-side cron probe (command in `WORKER_HEARTBEAT.md` §4), or extend the Caddy health route (R9). Alert on 2+ consecutive failures. |
| R19 | Low | **Two workers share one heartbeat row** (relates to R7). `instance_id` keeps swapping, so the worker mostly reads `starting`, with no explicit duplicate-worker error. | Keep a single worker. A future advisory lock (R7) would fix both. |
| R20 | Low | **`/health/worker` has no DB connect timeout** (same as R15). | Probe with a client-side timeout. Fix together with R15. |

### Deployment prerequisites (in addition to §7)

1. Apply migration `229c4aa5a0ca` (§6 step 7) and confirm `alembic current` → `229c4aa5a0ca (head)`.
2. After rollout, `/health/worker` must report `healthy`, and the worker log must contain `registering heartbeat` and no `Failed to record heartbeat` (§6 step 9).
3. Enable alerting on `/health/worker` only **after** rollout. It returns `missing` between the migration and the new worker's first beat.
