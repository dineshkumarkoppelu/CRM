# DealGraph: a CRM built on a graph database

A proof-of-concept CRM whose data lives in Neo4j, with KPI analytics, a per-client monthly
conversion forecast (with back-test) and a recommendation engine that routes every new deal
to the best available sales person, using their own domain track record or that of similar
reps, and explains why. React UI served by FastAPI.

There are two ways to run it:
- **Docker (recommended):** one command starts Neo4j (with APOC and GDS) and the app, on any OS.
- **Native Windows:** Neo4j as a local server process and the API with `uvicorn`, no Docker.

```
.
├── api/                  FastAPI backend (Python): app/ (app/sync = Postgres live sync), tests/, scripts/, config.yaml, .env.example
├── ui/                   React + TypeScript web UI (built into ui/dist, served by the API)
├── scripts/              PowerShell helpers for the native setup: start.ps1, reset.ps1, test.ps1
├── Dockerfile            Builds the UI, then the API image that serves it
├── docker-compose.yaml   Neo4j 5.26 (APOC + GDS) + the app
└── .env.example          Settings for docker compose (copy to .env)
```

> Proof of concept: there is no authentication. Anyone who can reach the API can reset the
> data (`POST /api/admin/seed`). Run it on your own machine only.

## Quick start with Docker
Needs Docker (Docker Desktop or Docker Engine with Compose v2) and internet on the first run
(images, the GDS plugin and, when you add a domain, the embedding model).

```bash
git clone <this repo> && cd <this repo>
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# edit .env and set NEO4J_PASSWORD (at least 8 characters) BEFORE the first start
docker compose up -d --build
```

Neo4j takes about 30 s to become healthy and the app starts after it. When
`docker compose ps` shows both services `healthy`, load the demo data (the database starts
empty) and open http://localhost:8000:

```bash
curl -X POST http://localhost:8000/api/admin/seed
# PowerShell: Invoke-RestMethod -Method Post http://localhost:8000/api/admin/seed
```

This loads 15 sales people, ~366 clients, 695 deals and ~2.9k activities. Set
`AS_OF_DATE=2026-10-06` in `.env` (before seeding) to get exactly the data the tests and demo
numbers are based on.

| What | Where |
|---|---|
| Web UI | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/api/health |
| Neo4j Browser | http://localhost:7474 (user `neo4j`, password from `.env`) |

Useful commands:
```bash
docker compose logs -f app          # API logs
docker compose down                 # stop, keep the data
docker compose down -v              # stop and DELETE the data and the cached embedding model
docker compose exec app sh -c "cd /app/api && pip install -r requirements-dev.txt && TEST_NEO4J_URI=bolt://neo4j:7687 python -m pytest -q"
```
The last command runs the test suite inside the container. The integration tests **wipe the
database they point at**, so run it only on a throwaway stack (or, after installing the dev
requirements, run only the database-free unit tests with
`docker compose exec -w /app/api app python -m pytest -q tests/unit`).

Notes:
- The password is stored in the Neo4j data volume on the first start. To change it later, run
  `docker compose down -v` first (this deletes the data), or change it with `ALTER USER`.
- Data lives in the named volumes `neo4j-data` / `neo4j-logs`; the embedding model in `app-models`.
- Ports 7474, 7687 and 8000 must be free. The containers are named `dealgraph-neo4j` and
  `dealgraph-app`; if you get "container name already in use" or "port is already allocated",
  another stack with the same names or ports is still around: stop it or change them in
  `docker-compose.yaml`.
- The business tunables in `api/config.yaml` are baked into the image: rebuild with
  `docker compose up -d --build` after editing it.
- Everything below this section describes the native Windows setup, except the sections that
  explain how the app works, which apply to both.

## Prerequisites for the native setup (Windows 11, PowerShell)
- **Java 21** (Neo4j 5.26 runs on Java 17 or 21): `winget install EclipseAdoptium.Temurin.21.JDK`,
  then open a new terminal and check `java -version`.
- **Neo4j Community 5.26.31, Windows ZIP** (`neo4j-community-5.26.31-windows.zip`) from the
  [Neo4j Deployment Center](https://neo4j.com/deployment-center/) (Community → 5.26 LTS → Windows).
  Not the `.rpm`/`.deb` files and not the 2026.x line.
- **Python 3.12**, **Git**, and **Node.js 22+** (built and tested with Node 24 LTS) for the UI.

## Neo4j setup (once)
You run **two** Neo4j instances from two copies of the same ZIP:

| Instance | Folder | Bolt | Browser | Used by |
|---|---|---|---|---|
| dev | `C:\neo4j\dev` | 7687 | http://localhost:7474 | the API |
| test | `C:\neo4j\test` | 7688 | http://localhost:7475 | `pytest` only (tests wipe it) |

1. Extract the ZIP twice, so that `C:\neo4j\dev\bin\neo4j.bat` and `C:\neo4j\test\bin\neo4j.bat` exist.
2. In **each** folder, install the plugins:
   - APOC: copy `labs\apoc-5.26.31-core.jar` to `plugins\`.
   - GDS: the Windows ZIP does **not** include it. Download **GDS 2.13.13** (the version matched
     to Neo4j 5.26.31) once and copy it into `plugins\`:
     ```powershell
     $ProgressPreference = 'SilentlyContinue'
     Invoke-WebRequest https://graphdatascience.ninja/neo4j-graph-data-science-2.13.13.jar -OutFile "$env:USERPROFILE\Downloads\neo4j-graph-data-science-2.13.13.jar"
     ```
3. In **each** folder, append to `conf\neo4j.conf`:
   ```
   dbms.security.procedures.unrestricted=apoc.*,gds.*
   dbms.security.procedures.allowlist=apoc.*,gds.*
   server.memory.heap.initial_size=1G
   server.memory.heap.max_size=1G
   server.memory.pagecache.size=512M
   ```
   And in the **test** folder only, also append:
   ```
   server.bolt.listen_address=:7688
   server.http.listen_address=:7475
   ```
4. Create the API config and set the same password (at least 8 characters) on both instances
   **before their first start**:
   ```powershell
   Copy-Item api\.env.example api\.env     # then edit NEO4J_PASSWORD in api\.env
   $pw = ((Get-Content api\.env | Where-Object { $_ -like 'NEO4J_PASSWORD=*' }) -split '=',2)[1]
   & C:\neo4j\dev\bin\neo4j-admin.bat dbms set-initial-password $pw
   & C:\neo4j\test\bin\neo4j-admin.bat dbms set-initial-password $pw
   ```

## Run locally
```powershell
# Terminal 1 - dev Neo4j (leave running; Ctrl+C stops it). Ready when it logs "Started."
C:\neo4j\dev\bin\neo4j.bat console

# Terminal 2 - API
cd api
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn app.main:app --port 8000 --no-access-log
```

If Neo4j is not up yet, the API waits up to 30 s, then starts anyway. `/api/health` reports
`degraded` until Neo4j is reachable and recovers by itself (no API restart needed).

## Web UI
Build it once (and after UI changes); the API then serves it at http://localhost:8000:
```powershell
cd ui; npm ci; npm run build; cd ..
```
If `ui\dist` does not exist the API still runs; UI pages return a JSON message telling you to build.

Developing the UI with hot reload (API must be running on :8000):
```powershell
cd ui; npm run dev        # http://localhost:5173, /api is proxied to :8000
npm run lint              # ESLint, zero warnings allowed
```
Pages: Dashboard, Clients & Deals (table, board, new client + deal with live assignment and
override), Deal detail, Rep profile, Heatmap (plus rule vs GDS similarity), Graph explorer.

## URLs
- API docs (Swagger): http://localhost:8000/docs
- Health: http://localhost:8000/api/health
- Neo4j Browser (dev): http://localhost:7474 (user `neo4j`, password from `api\.env`)

```powershell
Invoke-RestMethod http://localhost:8000/api/health | ConvertTo-Json -Depth 5
```

## Configuration
- `api/.env`: connection settings and secrets (see `api/.env.example`).
- `api/config.yaml`: business tunables (thresholds, weights, capacity, windows). Every key is
  required; an invalid value stops the API at startup with a message naming the key. Use a
  different file with the env var `APP_CONFIG_PATH`. View the loaded values at
  http://localhost:8000/api/meta/config.
- On every start the API applies `api/app/schema/init.cypher` (5 uniqueness constraints,
  6 range indexes, the 5 built-in Domain nodes). It is idempotent; `/api/health` shows `schema_ok`.

## Live data source (Postgres)
By default the app is standalone: Neo4j holds a synthetic dataset. Set `SOURCE_API_URL` and
`SOURCE_API_KEY` (and ideally `SOURCE_PG_DSN`) in `api/.env` and **Postgres becomes the source of
truth**: Neo4j mirrors it in real time and everything else (KPIs, forecast, recommendations,
graph explorer) keeps working on Neo4j as before.

```
Postgres tables ──(crm_changes NOTIFY)──▶ sync ──▶ Neo4j ──▶ analytics / recommendations
      ▲                                      └──▶ SSE /api/events ──▶ browser refetches
      └── any API client, and this app's own writes (UI → source API → same sync path)
```
- **Real time:** the backend `LISTEN`s on `crm_changes` (needs `SOURCE_PG_DSN`, a direct Postgres
  connection; the ngrok URL carries HTTP only). Each notification re-reads that row from the API
  and upserts (or deletes) it in Neo4j, typically within ~0.2 s. Without `SOURCE_PG_DSN` the app
  polls the API every `SYNC_POLL_SECONDS` instead. If the connection drops it reconnects with
  backoff and falls back to polling meanwhile.
- **Safety net:** `NOTIFY` is not durable, so a full sync (rows new, changed or gone) runs at
  startup, after every reconnect, every `SYNC_RECONCILE_SECONDS` and on `POST /api/admin/resync`.
  It is idempotent and writes nothing when nothing changed.
- **First run:** the first sync against a source *replaces* the people, clients, deals and
  activities already in Neo4j (the old demo data); `Domain` nodes and added domains are kept.
  It is remembered by a marker node, so later restarts only apply differences. It refuses to do
  this if the source is empty. `POST /api/admin/resync?hard=true` repeats it; so does
  `POST /api/admin/seed` ("Re-sync from source" in the Admin menu): in this mode nothing is
  generated.
- **Derived data:** `EXPERTISE_IN` / `SIMILAR_TO` are rebuilt a few seconds after the last deal or
  sales person change (`SYNC_RECOMPUTE_DEBOUNCE_SECONDS`), then the UI refreshes.
- **Writes from the UI** (new client/deal, stage moves, edits, activities, sales people, manual
  override, auto-assignment) go to Postgres first through the source API, then through the same
  upsert into Neo4j. A client + first deal is two inserts: if the deal fails the client is removed.
- **Unassigned deals:** a deal with no `owner_id` (or one that does not exist) is loaded without an
  owner and shows as "Unassigned"; the app does not auto-assign deals created outside it. Open the
  deal and press "Run assignment" (or override) to give it an owner.
- **Rows that cannot be loaded** (deal whose client is missing, unknown/invalid domain, activity
  whose deal is missing) are skipped and listed in `GET /api/admin/sync/status` (and counted next
  to the "Live" badge in the header); they are retried on every full sync. An unknown but valid
  domain name is added automatically like `POST /api/domains` does (needs the embedding model).
- **Live UI:** `GET /api/events` is a Server-Sent Events stream; the browser refetches when it
  sees a change. The header badge shows Live / Connecting / Not live.
- Deleting a deal in Postgres also removes its activities from Neo4j.

```powershell
# api/.env
SOURCE_API_URL=http://127.0.0.1:8010
SOURCE_API_KEY=<API_KEY from the Host db .env>
SOURCE_PG_DSN=postgresql://crm:<password>@127.0.0.1:5433/crm
```
In Docker, point these at `host.docker.internal` instead of `127.0.0.1` (compose already maps it).
If the source moves, change these values and restart the app. The integration tests never use a
real source: they run standalone, and `tests/integration/test_source_sync.py` uses an in-memory
fake of the API.

## How the forecast works
`GET /api/analytics/forecast` estimates how many clients each sales person will convert this
month. It looks at every open, owned deal expected to close this month. Each deal gets a win
probability: of the deals that reached the same stage in the last 12 months, the share that
were won, first using the rep's own deals in that domain, else the whole team's in that domain,
else the whole team's at that stage (at least 3 deals needed for the first two). A client
converts if at least one of its deals is won: P = 1 - (1 - p1)(1 - p2)... Clients at 70 % or more
count as "commit", 30 % or more as "best case". `/forecast/backtest` replays the same method on
last month as of its first day and compares it with what actually happened.

## How recommendations work
When a deal is created without an owner, the engine ranks every **available** sales person
(active, fewer open deals than capacity). Fit is the rep's own win rate in the deal's domain
(DIRECT, needs 3+ closed deals), or else the win rate of similar reps, discounted by 20 % (PEER;
"similar" = win rates within 10 points in 3+ shared domains), or, if nobody fits, overall win rate
(COLD_START; for domains with no history at all, RELATED comes first, see below).
Score = 70 % fit + 30 % availability. The top 5 are stored with a plain-language
reason and #1 becomes the owner; the manager can override. Expertise and similarity are rebuilt
nightly (02:00), after every seed, and on `POST /api/admin/recompute`.

## Adding domains
Besides the 5 built-ins, a manager can add a domain from the "New client and deal" drawer
(Domain → "+ New domain…") or with `POST /api/domains {name, description}`. The name and
description are turned into a vector by a small local embedding model
(`BAAI/bge-small-en-v1.5` via fastembed; nothing leaves the machine), and its cosine similarity
to every other domain is stored on `RELATED_TO` edges. `GET /api/domains` lists them.

Nobody has history in a new domain, so DIRECT and PEER cannot apply. Reps are then ranked on
their **own** win rates in the up to 3 most similar domains above 0.65 similarity, weighted by
how far above 0.65 each one is, and discounted by 30 % (RELATED fit). Only if nobody has
related experience does COLD_START apply. Adding a domain also reruns the recompute, because
the rep-similarity score divides by the number of domains. Tunables: the `domains` group in
`config.yaml`. Seeding removes added domains.

- The model (~64 MB) is downloaded to `api\.models` (in Docker: the `app-models` volume) the first time a domain is added (needs
  internet once; about 30–40 s). After that it loads from disk in a few seconds.
- It needs the **Microsoft Visual C++ 2015+ Redistributable (x64)**. With an outdated one,
  onnxruntime crashes the API on import:
  `winget install Microsoft.VCRedist.2015+.x64`.
- If the model cannot be loaded, `POST /api/domains` returns 503 `EMBEDDINGS_UNAVAILABLE` and
  nothing is written; everything else keeps working.

## Analytics cross-check
With the API running against the dev database, recompute the main KPIs independently with
pandas and compare them with the API (exit code 0 = all match):
```powershell
cd api; .\.venv\Scripts\Activate.ps1
python scripts\crosscheck_kpis.py            # --api <url> to target another API
```

## Stop / reset
- Stop the API or Neo4j: press `Ctrl+C` in its terminal.
- Wipe the dev database (deletes all data): stop dev Neo4j, then
  `Remove-Item -Recurse -Force C:\neo4j\dev\data\databases\neo4j, C:\neo4j\dev\data\transactions\neo4j`
  and start it again. The password is kept.
- Reset to the demo dataset (**wipes everything** in the dev database, no confirmation, no auth):
  ```powershell
  Invoke-RestMethod -Method Post http://localhost:8000/api/admin/seed | ConvertTo-Json -Depth 5
  ```
  Loads 15 sales people, ~366 clients, 695 deals and ~2.9k activities, deterministic for a
  given `AS_OF_DATE` and `seed.seed_random_seed`. Set `AS_OF_DATE=2026-10-06` in `api\.env`
  to get exactly the data the tests and demo numbers are based on.

## Running tests
Unit tests need no database. Integration tests need the **test** instance and are skipped
with a clear message if it is not running.
```powershell
# Terminal 3 - test Neo4j
C:\neo4j\test\bin\neo4j.bat console

# In api\ with the venv active
pytest -q
ruff check .; ruff format --check .
```

## Troubleshooting
- `Activate.ps1 cannot be loaded`: run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
- `java` not found / Neo4j will not start: install Java 21 and open a new terminal.
- Port 7687/7474 (or 7688/7475) already in use: another Neo4j is running; stop it first.
- Health shows `apoc_version` or `gds_version` null: the jar is missing from `plugins\` or the
  `dbms.security.procedures.*` lines are missing; fix and restart that Neo4j instance.
