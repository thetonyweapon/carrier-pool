# Decisions

## Project Structure & Stack

**Python backend (FastAPI + SQLAlchemy 2.0 + Pydantic v2) with PostgreSQL 16, Docker Compose.**

- Synchronous routes initially. FastAPI runs synchronous endpoints in a worker thread, deferring async SQLAlchemy machinery until it's genuinely needed (WebSocket, long-polling).
- Environment-driven config via `pydantic-settings`. No hardcoded database URLs.
- Python 3.12-slim base image. Docker Compose mounts `./data:/data:ro` — the ingestion adapter must never modify source files.
- Migrations run at container startup (`alembic upgrade head` before Uvicorn) as a single-instance MVP convenience. Production would run migrations as a separate deployment step.

*Alternatives rejected:* Fully async SQLAlchemy from the start (premature complexity); hardcoded database URLs (security risk); modifying source files in place (destructive, unreplayable).

---

## Multi-Tenancy Model

**Row-level tenant isolation via composite foreign keys, with every domain entity scoped by `broker_id`.**

- Each broker has one `broker_source` per TMS type (enforced by `unique(broker_id, tms_type)`).
- Every downstream entity carries both `broker_id` and `broker_source_id`. Composite foreign keys make cross-tenant references structurally impossible at the database level.
- Tests prove that cross-tenant customer/carrier references are rejected with `IntegrityError`.
- Shared carrier identity across brokers (the "opt-in pool") is explicitly deferred.

*Alternatives rejected:* Schema-per-tenant (operational complexity, no shared pool possible); single flat namespace with application-level filtering (data-leak risk).

---

## Data Model Design

**A fully normalized canonical schema that all TMS adapters map into, with raw payloads preserved alongside normalized snapshots.**

- Equipment type: TMS free-text fuzzy-matched to canonical `EquipmentType` enum. Ambiguous matches (e.g., "dry van reefer combo") return `UNKNOWN` rather than guessing.
- Stop type: Canonical `StopType` enum. Unknown stop types raise a validation error (surfaces missing coverage).
- Load status: TMS-specific strings mapped to a canonical lifecycle (`planned` → `active` → `covered` → `in_transit` → `delivered` → `completed`).
- `LoadVersion` stores both `raw_payload` (original TMS JSON) and `normalized_snapshot` (serialized canonical model fields). This supports point-in-time reconstruction and re-processing if mapping logic changes.
- `RateLineItem` is append-only. Database triggers on both PostgreSQL (PL/pgSQL) and SQLite block UPDATE/DELETE. Corrections are new rows, not mutations.
- All primary keys are UUID4 strings. `source_*_id` fields track TMS foreign identity for idempotent upserts.

*Alternatives rejected:* TMS-specific tables (does not scale to multiple TMS types); mutable rate records (loses audit trail); auto-increment PKs (leaks entity count).

---

## Ingestion Pipeline

**Transactional, file-at-a-time, all-or-nothing semantics via an adapter pattern.**

- Pydantic v2 models validate the raw JSON before any database writes.
- The entire file ingestion runs inside a single transaction; any load failure rolls back the entire file, including the `IngestionFile` record.
- `BrokerSource` is locked with `SELECT ... FOR UPDATE` at transaction start, serializing ingestion per source. (PostgreSQL provides the row lock; SQLite accepts but ignores the clause.)
- Stop synchronization is diff-based: existing stops loaded by `sequence_number` are matched against desired stops. Existing stops are updated in place, new stops are added, removed stops are deleted. This preserves stop identity (same `id`) across syncs.
- Customer/carrier upsert is conditional: `updated_at` only changes when field values actually differ.

*Alternatives rejected:* Loading all historical data in one batch (violates chronological-syncs constraint); mutable stop replacement (breaks referential stability); unconditional timestamp updates (unnecessary churn).

---

## Idempotency & Ordering

**Files identified by `(broker_source_id, filename)`; content verified by SHA-256; chronological ordering enforced per source.**

- Same filename + same checksum + `status == SUCCEEDED` → immediately returns `duplicate=True`, no database writes.
- Same filename + different checksum → `ConflictingFileError`. Prevents silent overwriting.
- File's `synced_at` must be strictly greater than the latest successful sync → `OutOfOrderFileError`.
- All checks happen inside the `FOR UPDATE` transaction, ensuring serial consistency.

*Alternatives rejected:* Allowing overwrites (data loss); relying on filenames alone (undetected corruption); allowing out-of-order ingestion (wrong load state).

---

## Migration Strategy

**Alembic with nullable-first → backfill → NOT NULL pattern for zero-downtime additions.**

- Migration 1 (`3cd64c705778`): creates all 8 tables with constraints, indexes, and triggers.
- Migration 2 (`8b3e1e01e7a2`): adds provenance columns as nullable, backfills legacy rows via deterministic `uuid5` IDs, then constrains to NOT NULL.
- Backfill retries on collision with a bounded loop (max 1000 attempts), checking both ID and `(broker_source_id, filename)` collisions.
- Fails fast with `RuntimeError` if any `load_versions` row references a nonexistent load (prevents silent data loss).
- Downgrade deletes synthetic ingestion files by `error_message` marker and restores original foreign keys.
- `native_enum=False` for all enums — stored as plain strings for database portability (critical for SQLite in tests).

*Alternatives rejected:* Raw SQL scripts without versioning (no rollback); random synthetic IDs (non-deterministic, duplicates on re-run); skipping NOT NULL (loses schema integrity).

---

## Financial Precision

**All monetary values as `Decimal(12, 2)` with strict enforcement at three layers.**

1. `@validates` on `Load` and `RateLineItem` — catches Python-level construction errors.
2. Custom `Currency` `TypeDecorator` via `process_bind_param` — safety net at database binding.
3. Adapter-level catch (`InvalidOperation`, `TypeError`, `ValueError`) — translates to user-facing error.

Validation: must be `Decimal`, finite, `≤ ±9999999999.99`, and exactly representable to cents.
Weight is `Numeric(12, 1)`, distance is `Numeric(10, 1)` — these are not financial values.

*Alternatives rejected:* Floats (rounding errors); `Numeric` without application validation (misses Python-level errors); storing fractions of a cent (not a real-world freight requirement).

---

## Test Strategy

**SQLite in-memory database for all tests with `PRAGMA foreign_keys=ON`.**

- Fast, isolated, no external dependencies. Every test gets a fresh database.
- `make_sync()` builder produces realistic FreightFlow payloads with sensible defaults and override parameters.
- 30 tests covering: basic ingestion, lifecycle across 3 syncs, multi-load files, idempotency, conflict detection, tenant isolation, unknown equipment, malformed payloads, fractional cents, out-of-range rates, CLI success/error paths, model constraint violations, currency validation, append-only enforcement, and migration upgrade/downgrade/re-upgrade round-trips.
- Ruff for linting (line-length 100, Python 3.9 target, E/F/I rule sets).

*Alternatives rejected:* Testcontainers/Postgres (slower, requires Docker); mocking SQLAlchemy (misses constraint enforcement).

---

## Omissions & Future Work

- **Lane model.** The problem mentions lanes (from→to pairs) as a key analytical concept, but there is no `lanes` table or lane-level aggregation yet. Deferred to the analytics/estimation phase.
- **Carrier scoring and price estimation.** The core deliverables ("which carrier to call first" and "what to pay") are not yet implemented. The codebase covers only ingestion and modeling.
- **HaulDesk and BrokerOS adapters.** Only the FreightFlow (TMS A) adapter is implemented. The remaining two TMS adapters follow the same pattern but with different schemas.
- **Synthetic data generation.** The project requires 10 days of sync files (4/day × 3 TMS) with lifecycle progressions, corrections, and lane diversity. Not yet created.
- **Frontend.** Only Vite/React stubs exist; no UI work has started.
- **Shared carrier pool.** The opt-in cross-broker carrier pool is the bonus feature and is explicitly deferred.

## What I'd Do Next With More Time

- Service-layer unit tests for recommendation logic decoupled from HTTP.
- Property-based tests (Hypothesis) for the ingestion adapter, generating random valid payloads and verifying invariants.
- A database-level integration test suite that runs against a real Postgres container to validate `FOR UPDATE` locking and trigger behavior (SQLite is not authoritative for these).
- Benchmark the migration backfill with 100k+ `load_versions` rows to validate the `uuid5` approach at scale (the current bounded retry loop is O(1) for normal cases but acceptable for any realistic dataset).
