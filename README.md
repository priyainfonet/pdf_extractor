# PDFKit Backend — Phase 6: Admin, Docker, Postgres/Redis

The final phase from the original roadmap. Two ways to use this:
**(A)** keep running locally exactly as before (SQLite, in-process jobs)
and just add the admin features, or **(B)** switch to the full Docker
stack (Postgres + Redis + Celery). Both work — nothing forces the switch.

## What's new

### Scanned PDF conversions

PDF-to-Word, PDF-to-PowerPoint, and PDF-to-Excel now run local OCR on pages
without an embedded text layer. OCR results flow through the same extraction
path as regular PDF text, so scanned pages are included in the generated files
without sending document content to an external service. Word and PowerPoint
preserve each PDF page as a full-page image, retaining its original appearance;
their page contents are not editable as text. Excel places detected table cells
in rows and columns; surrounding non-table text is retained on its Notes sheet.

### 1. Admin API + dashboard page
- `GET/PATCH/DELETE /api/admin/users`, `GET /api/admin/conversions`,
  `GET /api/admin/stats` — all require an admin account (403 if you're
  logged in but not an admin, 401 if not logged in at all)
- Admins can activate/deactivate accounts and grant/revoke admin rights
  for **other** users — deliberately blocked from doing either to their
  own account, so you can't accidentally lock yourself out
- Deleting a user also cleans up their files from storage, not just the
  DB rows
- `frontend-phase6/admin.html` + `admin.js` — a working page listing
  stats, every user (with action buttons), and recent conversions across
  everyone. Copy these + `admin-extras.css` into your frontend project
  like the previous phases' files.

### 2. Creating your first admin
There's no API for this (an admin-only endpoint can't be the way to
create the *first* admin — nothing would be able to call it). Use the
CLI script instead:

```powershell
python -m app.scripts.make_admin you@example.com
```

Run this after that user has already registered normally through the
app. After this, they can promote/demote others through the admin UI.

### 3. Real Celery + Redis (not just the interface)
Phase 2 built the `JobQueue` interface with only an in-process
implementation. This phase adds `CeleryJobQueue`
(`app/workers/celery_app.py`, `celery_tasks.py`) as a **real, working**
second option — same conversion logic, different mechanism for running
it. Set `JOB_QUEUE_TYPE=celery` in `.env` (plus a reachable `REDIS_URL`
and an actual running Celery worker) to use it. Still defaults to
`inprocess`, so this changes nothing unless you opt in.

### 4. Fixed from Phase 5's test-run warnings
- Migrated all `class Config: from_attributes = True` → Pydantic v2's
  `ConfigDict` (removes the `PydanticDeprecatedSince20` warnings)
- Migrated `@app.on_event("startup")` → FastAPI's current `lifespan`
  pattern (removes the `on_event is deprecated` warnings)
- Removed `Base.metadata.create_all()` from `app/main.py` entirely —
  this was the root cause of the "table already exists" error you hit
  during Phase 4's migration. Alembic is now the single source of truth
  for schema; **tests were updated too** (they call `create_all()`
  themselves against their own throwaway DB, so this doesn't affect
  `pytest`, only real app startup).

**Because of that last change: run `alembic upgrade head` before
starting the server from now on** — the app itself no longer creates
missing tables automatically. (You've already been doing this since
Phase 4, so this is really just making that the *only* path instead of
an accidental second one.)

## 5. Sticking with local SQLite + in-process (no Docker)

Nothing to do beyond the usual:
```powershell
alembic upgrade head
py -m uvicorn app.main:app --reload --port 8000
python -m app.scripts.make_admin you@example.com   # once, to get your first admin
```

## 6. Switching to the full Docker stack

Requires Docker Desktop. This runs Postgres, Redis, the API, and a
Celery worker as four containers:

```powershell
docker compose up -d --build
```

- The `backend` container runs `alembic upgrade head` automatically
  before starting uvicorn (see `docker-compose.yml`'s command) — so
  migrations apply themselves on every deploy.
- The `worker` container runs `celery -A app.workers.celery_app worker`
  — this is what actually processes conversion jobs in this mode.
- Both share the same Docker image (`Dockerfile`) and the same
  `storage_data` volume, so uploaded/converted files are visible to
  whichever container needs them.
- Check it's up: `http://localhost:8000/health`
- Create your first admin the same way, but run it inside the container:
  ```powershell
  docker compose exec backend python -m app.scripts.make_admin you@example.com
  ```
- Logs: `docker compose logs -f backend` / `docker compose logs -f worker`
- Stop everything: `docker compose down` (add `-v` to also wipe the
  Postgres/storage volumes and start completely fresh next time)

**Change the default `SECRET_KEY`** before this touches anything real —
`docker-compose.yml` reads it from an environment variable with a
placeholder fallback (`change-me-in-a-real-deployment`). Set a real one
in a `.env` file next to `docker-compose.yml` (Docker Compose reads
`.env` automatically for variable substitution):
```
SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_hex(32))">
```

## 7. Switching to Postgres without full Docker

If you want Postgres specifically but not the whole container stack:
```powershell
pip install psycopg2-binary
```
Then in `.env`:
```
DATABASE_URL=postgresql://user:password@localhost:5432/pdfkit
```
`alembic upgrade head` works unchanged — same migrations, different
database engine, because SQLAlchemy abstracts the dialect.

## 8. What's still not done (genuinely out of scope now, not deferred)

- **Frontend admin nav link** — I didn't touch `dashboard.html`/
  `profile.html` to add an "Admin" nav link (only regular users see
  those pages normally; you'll want to either always show the link and
  let the page's own access-denied check handle non-admins, which is
  what `admin.html` already does, or conditionally show it based on
  `session.user.is_admin` once your frontend tracks that field).
- **Celery Beat** for scheduled tasks (the cleanup worker still runs as
  an in-process thread inside the API container even in Celery mode —
  fine for one API replica, would double-run if you ever scale to
  multiple API replicas; moving cleanup to a proper Celery Beat schedule
  is the fix for that, not done here)
- **Production TLS/HTTPS, a reverse proxy (nginx/Caddy), non-root
  container user, resource limits** — this Docker setup is
  "deploy-shaped" for learning/staging, not hardened for public
  production traffic
- **Multi-replica considerations generally** — several pieces here
  (in-memory rate limiter, in-process cleanup scheduler, in-memory
  download registry from Phase 2) assume one process. Running several
  API replicas behind a load balancer would need Redis-backed versions
  of each — flagged at the point they were built, still true here
