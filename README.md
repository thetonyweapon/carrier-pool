# Carrier Pool

Carrier Pool is a demo-ready, multi-tenant freight analytics platform. It ingests
chronological exports from three fictional TMSs and provides broker-scoped lane
intelligence, explainable carrier recommendations, carrier-rate estimates, and a
React operations console.

The original product brief and evaluation constraints are preserved in
[`problem.md`](problem.md). This README documents the implementation in this
repository rather than repeating the parent assignment.

## Delivered Capabilities

- Transactional, chronological ingestion for FreightFlow, HaulDesk, and BrokerOS.
- Canonical broker-scoped records with preserved source snapshots and append-only
  financial history.
- On-demand lane intelligence, carrier recommendations, and rate estimation.
- Demo operations UI with broker-scoped queues, analytics, assignment overlays,
  and ephemeral local accounts.
- Guarded shared-carrier-pool recommendations and aggregate rate estimates in
  the authenticated demo path.
- Production deployment documentation and explicit boundaries around demo auth,
  external identity providers, and non-demo writes.

## Documentation

- [`problem.md`](problem.md): original product problem and constraints.
- [`DECISIONS.md`](DECISIONS.md): implementation decisions, trade-offs, and
  remaining work.
- [`PRODUCTION_RUNBOOK.md`](PRODUCTION_RUNBOOK.md): production Compose and
  recovery procedures.
- [`openspec/project.md`](openspec/project.md): capability map and status.
- [`openspec/architecture/README.md`](openspec/architecture/README.md): C4
  architecture diagrams.

## Repository Layout

```text
backend/       FastAPI application, adapters, migrations, and tests
frontend/      React/Vite operations console and browser tests
data/          Read-only synthetic TMS exports
openspec/      Capability specifications and architecture documentation
```

## Running the Backend

The initial backend foundation requires Docker Compose and exposes the API on
`http://localhost:8000`.

```bash
docker compose --profile demo up --build
curl http://localhost:8000/health
```

The Compose backend expects the repository's `data/` directory to exist because
it mounts that directory read-only at `/data`. Keep the provided TMS directories
and plain sync files under `data/`; without them, database health still works,
but ingestion commands cannot find their input files.

The health endpoint returns a successful response only when the API can reach
Postgres. Stop the services with `docker compose --profile demo down`; add `-v` if the local
development database volume should also be removed.

To run the backend checks locally:

```bash
cd backend
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

The default tests use isolated in-memory SQLite databases. To run the
PostgreSQL-specific HaulDesk row-lock test, set `HAULDESK_POSTGRES_TEST_URL`
to a reachable PostgreSQL URL and run:

```bash
HAULDESK_POSTGRES_TEST_URL=postgresql+psycopg://carrier_pool:carrier_pool@localhost:5432/carrier_pool pytest
```

That test creates and removes a temporary schema, so it does not modify the
normal application tables.

The health route is intentionally synchronous. FastAPI runs synchronous routes
and their database dependencies in a worker thread, keeping this SQLAlchemy
check off the async event loop without introducing async database machinery
before the application needs it. Docker automatically applies
`backend/.dockerignore` to the backend build context, so local environments,
tests, and caches are excluded from the image.

## Database Migrations

The backend uses Alembic to maintain the canonical multi-tenant schema. The
demo Compose profile runs `alembic upgrade head` before starting Uvicorn.
Production uses a separate, one-off migration job before rolling out API
instances; the long-running API process never changes the schema.

For local migration commands, run these from `backend/` with `.env` configured:

```bash
alembic current
alembic upgrade head
alembic downgrade base
```

The initial migration creates broker-scoped canonical records, audit versions,
append-only rate line items, and idempotent ingestion-file tracking. It
enforces cross-tenant relationships with composite foreign keys; shared carrier
identity across brokers is intentionally deferred to the opt-in pool design.

The BrokerOS migration adds append-only `load_rate_observations` for mutable
snapshot totals, plus date-only scheduling and source-location metadata on
stops. BrokerOS replacement totals are not converted into synthetic rate-line
adjustments: each changed value is recorded as a snapshot observation and the
current value remains materialized on the load.

Rate line items are a financial journal: they cannot be updated or deleted, and
loads or sources with rate history cannot be deleted through a cascade. Corrections
are represented as additional positive or negative adjustment rows.

## FreightFlow Ingestion

FreightFlow sync files are ingested one at a time and in chronological order.
The canonical broker source must already exist and must be configured as
`freightflow`. From the backend directory, ingest one plain JSON sync file with:

```bash
python -m app.ingestion.freightflow \
  --broker-source-id <freightflow-source-id> \
  ../data/tms_a_freightflow/2026-07-06T06-00_sync.json
```

Docker Compose mounts `data/` read-only at `/data`; use the same command through
the running backend container with a `/data/...` path. The adapter records a
checksum and synchronization time for idempotency, rejects altered content under
an existing filename, and rejects files that are not later than the last
successful sync for that broker source.

## HaulDesk Ingestion

HaulDesk exports are flat table deltas containing loads, carriers, and append-only
rate rows. The adapter processes carriers first, then load rows, then rates. It
also supports rate-only files that update a previously ingested load.

From the backend directory, ingest one plain JSON sync file with:

```bash
python -m app.ingestion.hauldesk \
  --broker-source-id <hauldesk-source-id> \
  ../data/tms_b_hauldesk/2026-07-06T06-00_sync.json
```

HaulDesk timestamps are naive US Central time and are converted with
`America/Chicago` timezone rules before storage. Pickup and delivery dates are
stored as Central midnight values because the source provides dates rather than
appointment windows. Kilograms and kilometers are converted to pounds and miles
with Decimal arithmetic and explicit half-up rounding to one decimal place.

Rate rows are immutable source events. Bill and pay totals are recalculated from
the complete rate journal, so positive surcharges and negative adjustments are
preserved in history. Repeated rate IDs are rejected even when the amount is
unchanged; a new source rate ID is a new journal event. Contradictory status and
carrier values are retained as provided by the source.

HaulDesk's published export has exactly one pickup and one delivery, so the
adapter creates those two stops and rejects unexpected schema fields rather than
silently dropping them. A future HaulDesk multi-stop export requires an adapter
revision because the current source has no multi-stop representation.

MC/DOT evidence is normalized into a broker-scoped carrier identity shared by
source-specific carrier rows. Matching is serialized by the broker row across
TMS sources. Complementary MC-only and DOT-only identities are merged and their
carrier rows are repointed. Conflicting evidence rejects the whole sync; it is
never silently overwritten.

## BrokerOS Ingestion

BrokerOS is a CRM-style export. Each load record contains opaque customer,
carrier, and stop-location IDs resolved through the file's
`referenced_records` object. The adapter validates reference types and required
fields, rejects unknown source fields, and rolls back the entire file if any
reference or record is invalid.

From the backend directory, ingest one plain JSON sync file with:

```bash
python -m app.ingestion.brokeros \
  --broker-source-id <brokeros-source-id> \
  ../data/tms_c_brokeros/2026-07-06T06-00_sync.json
```

BrokerOS timestamps must include an offset and are stored as UTC. Its scheduled
stop values are calendar dates and are stored in `LoadStop.scheduled_date`, not
as invented midnight timestamps. Stops are sorted by their source sequence,
which is also preserved alongside resolved location IDs and names. BrokerOS
supports more than two stops, pickup/dropoff combinations, and actual arrival
timestamps. The source does not expose stable child-stop IDs, so canonical stop
IDs represent sequence slots rather than guaranteed physical-stop identity when
an intermediate stop is inserted.

BrokerOS customer and carrier accounts are source-specific. The documented
schema does not provide MC/DOT evidence for carriers, so BrokerOS carriers are
not guessed into the shared broker-scoped carrier identity model. Cargo weights
support pounds and kilograms, use Decimal conversion and half-up rounding to
one decimal pound, and reject unsupported units. Empty cargo line items produce
an unknown aggregate weight.

BrokerOS customer and carrier rates are mutable replacement totals. Changes are
recorded in the append-only `load_rate_observations` table, including null-to-
value, value-to-null, zero, and restatement transitions. They are not inserted
into HaulDesk's additive `RateLineItem` journal.

## Synthetic Dataset

The checked-in synthetic dataset covers July 6-16, 2026 at the required
six-hour cadence: 44 files per TMS, or 132 files total. It includes complete
lifecycles, corrections, rich and thin Texas Triangle lanes, experienced and
sparse carriers, and fresh Day 11 loads that remain uncovered.

The files are generated deterministically from fixed scenarios. From the
repository root, regenerate them with:

```bash
python3 backend/scripts/generate_synthetic_data.py
```

Generation overwrites only the expected dated sync filenames. To remove stale
files from an older generated run, explicitly use `--clean`; unrelated JSON
files are never removed.

Validate every source schema and ingest all files in chronological order with:

```bash
cd backend
python3 -m pytest tests/test_synthetic_data.py -q
```

The test also verifies duplicate-file idempotency and generator
reproducibility against the checked-in files. Day 11 reuses stable active load
IDs across its four syncs. HaulDesk uses unique additive rate IDs and
adjustment rows.
FreightFlow uses replacement snapshots, while BrokerOS uses
replacement totals with append-only observations.

## Lane Intelligence

Lane Intelligence is available for an active or historical load through the
broker-scoped endpoint below:

```bash
curl 'http://localhost:8000/brokers/<broker-id>/loads/<load-id>/lane-intelligence'
```

The response derives a directional lane using the first pickup-capable and final
delivery-capable stops, then reports exact endpoint history separately from
same-metro fallback history. History is restricted to the requesting broker's
`DELIVERED` and `COMPLETED` loads, counts each canonical load once, and includes
equipment-compatible counts and data sufficiency metadata. The MVP considers the
500 most recently synced eligible loads for predictable response cost.

Normalization uses the deterministic `tx-metro-v1` Texas geography map. The
service is computed on demand from current canonical rows, so corrected stop,
status, and equipment values are reflected without stale materialized counters.
Coordinate-radius matching and persisted lane aggregates remain deferred.
Production OIDC authentication and demo authentication are separate deployment
boundaries for the broker-scoped path.

Run the focused tests with:

```bash
cd backend
python3 -m pytest tests/test_lane_intelligence.py -q
```

## Carrier Rate Estimation

Carrier rate estimates are available for active, uncovered loads:

```bash
curl 'http://localhost:8000/brokers/<broker-id>/loads/<load-id>/carrier-rate-estimate'
```

The response estimates all-in USD carrier pay using one effective current total
per completed historical load. It prefers exact directional lane and equipment
history, then explicitly falls back through same-metro and broker-wide tiers.
The estimate uses median rate-per-mile with an observed interquartile range,
Decimal half-up cent rounding, confidence metadata, exclusion counts, and a
`status: unavailable` result when evidence is insufficient.

Run the focused tests with:

```bash
cd backend
python3 -m pytest tests/test_rate_estimation.py -q
```

## Carrier Recommendations

Carrier recommendations are available for active, uncovered loads:

```bash
curl 'http://localhost:8000/brokers/<broker-id>/loads/<load-id>/carrier-recommendations'
```

The response ranks broker-owned logical carriers using deterministic
`carrier-recommendations-v1` scoring. Exact and same-metro directional lane
experience, equipment history, customer familiarity, conservative operational
recency, and capped completed-load volume are returned as explainable factors.
Source-specific carrier rows linked by broker-scoped MC/DOT identity aggregate
into one candidate; carriers without eligible history appear separately as
unscored cold starts.

Recommendations do not claim current availability, capacity, deadhead, safety,
or service quality. History uses the 500 most recently synced eligible loads and
is computed from current canonical rows.

## Broker Operations Backend

The broker operations API is broker scoped and exposes the complete lifecycle:

```bash
curl 'http://localhost:8000/brokers/<broker-id>/loads?page=1&page_size=25'
curl 'http://localhost:8000/brokers/<broker-id>/loads/<load-id>'
curl 'http://localhost:8000/brokers/<broker-id>/carrier-candidates/carrier:<carrier-id>'
```

List filters are `status`, `equipment`, `assignment_state` (`assigned` or
`unassigned`), and `search`. Currency, weight, and distance values are
serialized as strings. Pickup schedule, display number, and id provide stable
ordering. `DEMO_MODE=true` enables broker discovery and assignment creation;
it is false by default. Assignments are platform overlays with optimistic
`expected_assignment_version`, do not mutate canonical ingestion fields, and
make the load ineligible for recommendations and rate estimation.

## Broker Operations UI

The operations console provides authenticated read and analytics access in both
demo and production OIDC deployments. `DEMO_MODE=true` additionally enables
demo broker discovery (`GET /demo/brokers`) and platform assignment creation;
it is `false` by default. Demo assignments are auditable platform overlays that
never write back to a TMS, and switching brokers in the UI is not authentication.

### Guarded shared carrier pool

The shared-pool workflow is disabled by default. Compose enables its
demo-authenticated path with `SHARED_POOL_READ_ENABLED=true`, `AUTH_SECRET`, and
`SHARED_POOL_ID_SECRET`:

```text
GET /brokers/<broker-id>/loads/<load-id>/shared-carrier-recommendations
GET /brokers/<broker-id>/loads/<load-id>/shared-carrier-rate-estimate
```

Opted-in brokers contribute only normalized MC/DOT-linked history. Results need
evidence from at least three distinct opted-in brokers and expose only a public
carrier name, coarse match/evidence buckets, and an opaque candidate ID. They
omit MC/DOT values, source broker identity, customers, rates, raw payloads,
exact source lanes, and precise timestamps. Shared candidates are informational
only and cannot be assigned through the local assignment endpoint. Policy
changes require the current broker's signed bearer token. Shared rate estimates
use the same three-broker threshold and expose only an aggregate amount/range,
never source rates or dates. The demo token issuer is not a production identity
provider.

### Authentication boundary

The local evaluation profile uses the signed mock issuer only when
`DEMO_MODE=true`, `AUTH_MODE=mock`, and `ALLOW_MOCK_AUTH=true`. The `/demo/auth`
endpoint is hidden otherwise, and mock bearer verification rejects tokens
outside demo mode. Non-demo deployments use the configured OIDC/JWKS provider.

Non-demo settings reject mock authentication, require HTTPS OIDC issuer/JWKS
and login URLs, require PostgreSQL and explicit allowed hosts, and reject the
documented Compose fallback secrets. The OIDC verifier derives `broker_id` from
the configured verified tenant claim, uses `sub` as the actor subject, and
enforces issuer, audience, expiry, and JWKS signature validation.

### Local demo accounts

The login page supports ephemeral local accounts. `admin` / `admin` is the
intentional sysadmin demo exception and can select any broker. Existing TMS
brokers are demo-locked; `Local Sandbox Brokerage` is the editable local
broker fixture. Local accounts are kept only in backend memory, use salted
hashes while the process is running, and disappear when the backend container
restarts. Normal accounts are restricted to their assigned broker, while the
admin account can switch broker context. Password reset is deliberately a UI
notice only; no email or third-party service is contacted.

### Option A: Docker Compose (recommended)

Compose sets `DEMO_MODE=true` automatically, runs migrations, creates the three
demo brokers with stable IDs and display names (`broker-a` / `Ithaca Freight
Partners`, `broker-b` / `Aegean Route Logistics`, and `broker-c` / `Olive Harbor
Transport`), creates `broker-local` for local accounts, and ingests the
checked-in 180-file dataset before the API starts:

```bash
docker compose --profile demo up --build
```

The Compose secrets use demo-only fallback values so the sample stack starts
without extra setup. Set `AUTH_SECRET` and `SHARED_POOL_ID_SECRET` from a secret
manager or deployment environment before using the stack outside local
evaluation; never reuse the documented fallback values.

Open <http://localhost:3000>. The frontend nginx container proxies `/api/` to
the backend on port 8000.

Production deployment and recovery procedures are documented in
`PRODUCTION_RUNBOOK.md`.

### Resource controls

The backend uses bounded PostgreSQL connection pools and applies statement and
idle-transaction timeouts to each PostgreSQL connection. Ingestion rejects files
larger than `INGESTION_MAX_FILE_BYTES` or payloads with more than
`INGESTION_MAX_RECORDS`; these default to 10 MiB and 1,000 records. Tune the
`DB_*` and `INGESTION_*` settings for workload capacity while keeping the p95
targets documented in `openspec/specs/platform-hardening/spec.md` as acceptance
criteria.

### Option B: Standalone backend + frontend

Start a Postgres instance and point `DATABASE_URL` at it, then run the backend
with `DEMO_MODE` enabled:

```bash
cd backend
cp .env.example .env
# Set these demo-only values in .env:
# DEMO_MODE=true
# AUTH_MODE=mock
# ALLOW_MOCK_AUTH=true
# AUTH_SECRET=local-development-secret
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
python -m scripts.bootstrap_demo --root ../data
uvicorn app.main:app --reload
```

`bootstrap_demo` creates the demo brokers and sources and ingests the `data/` TMS
sync directories. Broker IDs (`broker-a` through `broker-c` and `broker-local`)
and source IDs (`source-a` through `source-c`) are stable identities. Their
display names are `Ithaca Freight Partners`, `Aegean Route Logistics`, `Olive
Harbor Transport`, `Local Sandbox Brokerage`, `FreightFlow`, `HaulDesk`, and
`BrokerOS`. Compose runs it on every backend startup; standalone users can rerun
it safely because it is idempotent, only replaces legacy ID-as-name placeholders,
and preserves custom names.

In a second terminal, start the frontend dev server:

```bash
cd frontend
npm install
VITE_DEMO_MODE=true npm run dev
```

Open the URL printed by Vite (default <http://localhost:5173>); the dev server
proxies `/api/` to `localhost:8000`. Set `VITE_API_BASE_URL` if the backend
lives elsewhere.

### What the UI shows

The console provides an all-lifecycle load queue with server-side filters and
pagination, ordered stop details with browser-local timestamps, 24-hour stale
warnings, independent lane/rate/recommendation panels, and a carrier contact
drawer with demo assignment. Analytics for an actively assigned load return
`ineligible` (409) until the assignment overlay changes.

### Frontend verification

Run the component and integration suite from `frontend/`:

```bash
npm ci
npm run typecheck
npm test
npm run test:coverage
npm run build
```

With the Docker Compose demo stack running, install the Playwright browsers and
run the real Chromium flow:

```bash
npx playwright install chromium
npm run test:e2e -- --project=chromium
```

The scheduled browser workflow also runs WebKit and a mobile viewport. The UI
tests assert that cleared enum filters are omitted from requests, preventing
the empty-filter 422 regression.
