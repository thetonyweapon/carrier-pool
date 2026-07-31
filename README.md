# Take-Home: Carrier Recommendation for Freight Brokers

## Design Documentation

Start with the [OpenSpec project overview](openspec/project.md) for the
capability map and current implementation status. The [C4 architecture
overview](openspec/architecture/README.md) links to GitHub-rendered diagrams at
system context, container, component, and code levels.

- [C1: System context](openspec/architecture/context.md)
- [C2: Containers](openspec/architecture/containers.md)
- [C3: Backend components](openspec/architecture/components.md)
- [C4: Code responsibilities](openspec/architecture/code.md)
- [Architecture decisions](openspec/architecture/decisions.md)

- You may use AI coding tools (Claude Code, Codex, Cursor, etc) are strongly encouraged.
- With AI tools and the provided skeleton, a working baseline is roughly a **4-hour job — that's the floor, not the goal**. Strong submissions typically take one to two focused days on top.
- **Cutting scope deliberately is a valid strategy, not a failure** — a smaller thing done deeply beats a big thing done shallow. Say what you cut and why in `DECISIONS.md`.
- We want to see how you think, how deep you go, and which problems you notice on your own.
- In the review call you'll walk us through your decisions and defend them.

## The world

A **freight broker** is a middleman:

- **Customers (shippers)** — companies that have goods to move.
- **Carriers** — trucking companies that move the goods.
- The customer pays the broker one amount (**customer rate**). The broker (ideally) pays the carrier a smaller amount (**carrier rate**). The broker keeps the difference (**margin**).

Each shipment is called a **load**: a pickup place, a delivery place, the truck type needed (dry van, refrigerated, flatbed, etc.), dates, and weight.

A load goes through statuses as it moves through real life:

| Status | Plain meaning |
|---|---|
| `PLANNED` | The customer asked the broker to move this load; nothing has happened yet |
| `ACTIVE` | The broker is now searching for a carrier to take it |
| `COVERED` | A carrier said yes and is booked; the price the broker will pay them is now fixed |
| `IN_TRANSIT` | The truck is on the road |
| `DELIVERED` | The goods arrived |
| `COMPLETED` | All paperwork is done and the final money amounts are confirmed |

Loads can be updated or corrected at any point — freight data is messy.

Two more concepts:

- A **lane** is a from→to pair (for example "Dallas area → Houston area"). A carrier that has done many loads on or near a lane is likely a good fit for the next load on it.
- But what counts as "the same lane" is tricky. Think of New York City and Newark, NJ: they are ~10 miles apart, so for a trucker, Chicago → NYC and Chicago → Newark are practically the same lane — yet they have different city names *and* different states, so grouping history by city or by state would treat them as unrelated. Going the other way, "Texas → Texas" as one lane is useless: Dallas → Houston is 240 miles, El Paso → Houston is 750. You will face the same issue at smaller scale inside the Texas Triangle (suburbs of one metro vs another).
- **Deadhead** = empty miles a truck drives to reach a pickup. Carriers hate it. A truck that just delivered close to your new load's pickup is an easy yes.

## The problem

The platform you are building serves **multiple freight brokers**:

- Each broker runs a **different TMS** (Transportation Management System — the software where all their loads, carriers, and customers live). So each broker's data arrives in a different shape.
- Every day, each broker gets new loads (and sometimes new customers and carriers) *and* updates to existing ones.

For a broker's `ACTIVE` load, your platform must answer two questions:

1. **Which of my carriers should I call first, and why?**
2. **What should I expect to pay a carrier for this load?**

Both answers must come from the broker's own historical data. The broker must be able to see *why* — a bare score or price with no explanation is not useful.

**Bonus — the shared carrier pool.** If you have the appetite: let brokers opt in to a shared carrier pool, so a load can also be matched with carriers known by *other* opted-in brokers. Sharing between competitors is sensitive — so if you attempt this, clearly define and indicate what data crosses the broker boundary (and what never does), and design the sharing around that.

## Repository layout (your starting point)

This repo is an empty shell — placeholder Dockerfiles, compose file, and frontend/backend stubs. You fill it in (or restructure it). The only thing that matters out of the box is `data/`.

```
README.md                       # this file
docker-compose.yaml             # empty shell — yours to fill
backend/                        # empty Dockerfile + pyproject.toml stub
frontend/                       # empty Dockerfile + Vite-style stub
data/
  tms_a_freightflow/            # one directory per TMS
    example_sync.jsonc          # commented schema example — READ THIS FIRST
    example_sync_next.jsonc     # the following sync: same load, updated (how changes arrive)
    2026-07-06T06-00_sync.json  # empty placeholder — shows the filename convention
  tms_b_hauldesk/
    example_sync.jsonc
    2026-07-06T06-00_sync.json
  tms_c_brokeros/
    example_sync.jsonc
    2026-07-06T06-00_sync.json
```

The `example_sync.jsonc` files are the schema documentation (comments included). The real sync files you generate are plain `.json`, named `{YYYY-MM-DD}T{HH-MM}_sync.json` (ISO-8601-style, so filenames sort chronologically).

## Constraints (the few we do impose)

**Starting point**

- Assume the data has already been downloaded from each TMS — the raw data sits in the `data/` directories, exactly as the TMS produced it. Don't build or fake the TMS APIs themselves.
- **We provide the 3 fictional TMS schemas** — see `data/tms_a_freightflow/`, `data/tms_b_hauldesk/`, `data/tms_c_brokeros/`. How you get from their raw shapes to answers is yours to design.
- Each TMS is synced **every 6 hours** (00:00, 06:00, 12:00, 18:00). Every sync produces one self-contained file in that TMS's directory, with the sync datetime in the filename. A sync contains **1–3 loads**: everything created or changed since the last sync.

**Data (synthetic — you generate it; AI is good at this, but you own its sanity)**

- Geography: loads move within the **Texas Triangle** (Dallas–Fort Worth, Houston, San Antonio areas). Spread stops across nearby towns and suburbs, not just the three city centers.
- Create the sync files for **10 simulated days** (4 syncs per TMS per day, following the provided schemas and examples). Use AI to write the files, but *direct* it — **design the data like test cases for your own system**, not random noise. Every behavior you want to show off should have data that demonstrates it.
- At minimum, the data must contain these scenarios (how many and when is up to you):
  1. Loads progressing through the **full lifecycle across syncs**, with money amounts appearing as they become known (e.g. the carrier rate gets fixed when a carrier is booked; final amounts confirmed at completion).
  2. **Corrections** — loads whose *already-recorded* amount or detail changes to a new value in a later sync.
  3. **Contrast**: lanes with rich history next to lanes with thin history; carriers with lots of experience next to carriers with almost none.
- **Day 11** brings fresh loads that are still looking for a carrier — the ones your system must answer for, using days 1–10 as history. We should be able to look at your data and trace *why* your system gave each day-11 answer.
- **Ingestion processes one sync file at a time, in chronological order** — like the real scheduled syncs would have. No loading everything in one shot.

**Platform**

- **Multi-tenant**: one broker's data must never leak into or influence another broker's answers — the bonus pool, if you build it, is the single deliberate opt-in exception.
- **Stack**: use whatever you want. We recommend Python/TypeScript backend + TypeScript/React (and Postgres via docker compose) because that's what the shell hints at — but the stubs are optional, not a mandate.
- **Frontend**: any working UI that shows a load list, and per load the price estimate plus the ranked carriers with their reasoning. Correctness and clarity count; visual polish counts for nothing.
- **How to run**: document it. We will run your project ourselves — a short doc (README section or similar) with the command sequence to bring everything up and reproduce your results. An end-to-end check that exercises that path is a plus — we care that you thought about it, not which tool you picked.

## What we're looking for

Not feature count. We read for the problems you noticed and how you resolved them, for example:

- What happens to your analytics when yesterday's load is corrected today? Do you patch the derived numbers, or rebuild them from scratch — and what would break at millions of loads?
- What is a "lane", exactly, when pickups are scattered across suburbs?
- How does a scoring formula stay fair to a carrier with little history?
- Where should a price estimate come from when the exact lane has little data?
- (If you attempt the pool) what exactly is shared, and how do you prove nothing else leaks?

Some of these have no single right answer — your reasoning is the deliverable as much as the code.

Include a short `DECISIONS.md`:

- The judgment calls you made and the alternatives you rejected.
- What you'd do next with more time.
- Honest limitations score better than hidden ones.

## Running the Backend

The initial backend foundation requires Docker Compose and exposes the API on
`http://localhost:8000`.

```bash
docker compose up --build
curl http://localhost:8000/health
```

The Compose backend expects the repository's `data/` directory to exist because
it mounts that directory read-only at `/data`. Keep the provided TMS directories
and plain sync files under `data/`; without them, database health still works,
but ingestion commands cannot find their input files.

The health endpoint returns a successful response only when the API can reach
Postgres. Stop the services with `docker compose down`; add `-v` if the local
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
backend container runs `alembic upgrade head` before starting Uvicorn, which is
appropriate for this single-instance MVP. A production deployment would run
migrations as a separate, one-off job before rolling out API instances.

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
