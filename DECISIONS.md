# Decisions

## Platform Hardening Contract

**Hardening is delivered as sequential, independently reviewed pull requests
on the fork, with medium-or-higher review findings fixed before merge.**

- The hardening sequence starts with the planning contract, then covers mock
  authentication and tenant authorization, deployment safety, PostgreSQL
  integration coverage, durable ingestion, observability, assignment
  concurrency, scale controls, property-based tests, CI/supply-chain controls,
  and production runbooks.
- Authentication is provider-neutral in this program. Tests use deterministic
  mock issuer and JWKS responses; no external identity provider is contacted.
- Production assumes managed PostgreSQL, a separate non-demo deployment
  profile, a filesystem-polling ingestion worker behind a storage abstraction,
  JSON logs, Prometheus metrics, and OpenTelemetry traces.
- The initial targets are Python 3.12, PostgreSQL 16, p95 under 500 ms for
  paginated load list/detail requests, p95 under 2 seconds for broker-scoped
  analytics at 100,000 loads per tenant, RPO 15 minutes, and RTO 1 hour.
- Lower-severity findings discovered during milestone reviews are filed as
  GitHub issues on the fork rather than silently expanding milestone scope.

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
- Broker-scoped `CarrierIdentity` records link source-specific carrier rows across TMSs using normalized MC/DOT evidence. MC/DOT values are independently unique per broker; complementary identities can merge, while contradictory evidence rejects the sync. A broker row lock serializes identity resolution across TMS sources. This does not cross broker boundaries or enable the shared carrier pool.

*Alternatives rejected:* Schema-per-tenant (operational complexity, no shared pool possible); single flat namespace with application-level filtering (data-leak risk).

---

## Data Model Design

**A fully normalized canonical schema that all TMS adapters map into, with raw payloads preserved alongside normalized snapshots.**

- Equipment type: TMS free-text fuzzy-matched to canonical `EquipmentType` enum. Ambiguous matches (e.g., "dry van reefer combo") return `UNKNOWN` rather than guessing.
- Stop type: Canonical `StopType` enum. Unknown stop types raise a validation error (surfaces missing coverage).
- Load status: TMS-specific strings mapped to a canonical lifecycle (`planned` → `active` → `covered` → `in_transit` → `delivered` → `completed`).
- `LoadVersion` stores both `raw_payload` (original TMS JSON) and `normalized_snapshot` (serialized canonical model fields). This supports point-in-time reconstruction and re-processing if mapping logic changes.
- `RateLineItem` is append-only. Database triggers on both PostgreSQL (PL/pgSQL) and SQLite block UPDATE/DELETE. Corrections are new rows, not mutations.
- Domain primary keys are UUID4 strings; the fixed demo broker/source rows are the deliberate stable-ID exception. `source_*_id` fields track TMS foreign identity for idempotent upserts.
- Demo broker IDs (`broker-a` through `broker-c`) and source IDs (`source-a` through `source-c`) are stable identities, separate from display names. Bootstrap creates the configured display names, reconciles only legacy ID-as-name placeholders, preserves custom names, and validates source ownership and TMS type before committing.

*Alternatives rejected:* TMS-specific tables (does not scale to multiple TMS types); mutable rate records (loses audit trail); auto-increment PKs (leaks entity count).

---

## Ingestion Pipeline

**Transactional, file-at-a-time, all-or-nothing semantics via an adapter pattern.**

- Pydantic v2 models validate the raw JSON before any database writes.
- The entire file ingestion runs inside a single transaction; any load failure rolls back the entire file, including the `IngestionFile` record.
- `BrokerSource` is locked with `SELECT ... FOR UPDATE` at transaction start, serializing ingestion per source. (PostgreSQL provides the row lock; SQLite accepts but ignores the clause.)
- Carrier identity resolution also locks the broker row, serializing identity creation and complementary merges across different TMS sources.
- Stop synchronization is diff-based: existing stops loaded by `sequence_number` are matched against desired stops. Existing stops are updated in place, new stops are added, removed stops are deleted. This preserves stop identity (same `id`) across syncs.
- Customer/carrier upsert is conditional: `updated_at` only changes when field values actually differ. HaulDesk rejects unexpected fields so source schema drift cannot be silently discarded.

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
- Migration 3 (`1b4c4f0a2d91`): adds broker-scoped carrier identities, deterministic backfills existing carrier evidence, and links source-specific carrier rows. Existing contradictory MC/DOT evidence fails the migration rather than being silently merged. Identity rows are derived from source carrier evidence and can be rebuilt on re-upgrade.
- Migration 4 (`2f7d1c9a4e30`): adds BrokerOS mutable-rate observations and BrokerOS stop metadata (`scheduled_date`, source location, and source sequence). Observation rows are append-only and preserve null-versus-zero semantics.
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
- The backend suite covers FreightFlow and HaulDesk ingestion, lifecycle corrections, rate-only and empty deltas, multi-load files, zero-sum corrections, cross-TMS carrier identity normalization and merging, idempotency, conflict detection, tenant isolation, unknown equipment, malformed and schema-drift payloads, fractional cents, out-of-range rates, CLI success/error paths, model constraint violations, currency validation, append-only enforcement, migration backfill and upgrade/downgrade/re-upgrade round-trips, real temporary SQLite bootstrap behavior, and environment-gated PostgreSQL locking coverage.
- Ruff for linting (line-length 100, Python 3.9 target, E/F/I rule sets).

*Alternatives rejected:* Testcontainers/Postgres for the default suite (slower, requires Docker); mocking SQLAlchemy (misses constraint enforcement). PostgreSQL-specific locking coverage is available when `HAULDESK_POSTGRES_TEST_URL` is set.

---

## Omissions & Future Work

- **Lane intelligence.** Delivered as an on-demand, broker-scoped service using a versioned `tx-metro-v1` ZIP/city-to-metro map. It keeps exact endpoint and directional metro keys separate, reports nearby fallback explicitly, and derives history from current canonical loads so corrections cannot double-count a load. Persisted lanes, coordinate radius matching, and segment-level multi-stop lanes remain deferred.
- **Carrier recommendations.** Delivered as a broker-scoped, on-demand ranking service using versioned integer scoring, logical carrier identity aggregation, explicit cold-start results, and explainable lane/equipment/customer/recency factors. Availability, deadhead, service quality, and persisted historical rankings remain unavailable or deferred.
- **Carrier rate estimation.** Delivered as an on-demand, broker-scoped service
  using one effective all-in carrier total per completed load, median rate per
  mile, explicit 180/365-day fallback tiers, Decimal half-up rounding, and
  qualitative sufficiency metadata. Source corrections and audit history do not
  double-count shipments. Currency decomposition, reverse lanes, market
  indexes, and persisted estimates remain deferred.
- **BrokerOS adapter.** BrokerOS is supported as a strict CRM-style adapter. It resolves same-file Account and Location references, supports arbitrary ordered stops, stores date-only schedules without inventing timestamps, aggregates pounds/kilograms, and records mutable totals as append-only rate observations. The source does not provide MC/DOT evidence or stable child-stop IDs, so carrier identity linking and physical stop identity remain unavailable.
- **HaulDesk adapter.** HaulDesk is supported as a flat-table delta adapter. It interprets naive timestamps as `America/Chicago`, maps its source-defined single pickup and single delivery to the two canonical stops, rounds metric conversions half-up to one decimal place, rejects repeated immutable rate IDs, and creates one load version for rate-only changes. HaulDesk cannot provide additional stops because its export has no multi-stop representation.
- **Booking timestamps.** HaulDesk has no booking event timestamp, so `Load.booked_at` records the first source `updated_at` observed with a carrier or covered-or-later status rather than the ingestion time.
- **Synthetic data generation.** The deterministic generator in `backend/scripts/generate_synthetic_data.py` creates 44 historical files per TMS for July 6-16, 2026 and 16 operational files per TMS for July 29-August 1, 2026. The checked-in 180-file dataset uses explicit Texas Triangle scenarios with full lifecycles, chronologically valid stop events, rate/detail corrections, rich/thin lanes, carrier experience contrast, stable uncovered Day 11 targets, recent operational loads, active August 1 demo targets, and planned September loads. Source semantics remain distinct: FreightFlow replacement snapshots, HaulDesk additive rate rows with adjustments, and BrokerOS replacement totals with append-only observations. Generation only removes expected dated files when `--clean` is explicit. `tests/test_synthetic_data.py` validates schemas, chronology, sequential ingestion, normalization, tenant ownership, idempotency, operational statuses, future schedules, and reproducibility against checked-in output.
- The dataset intentionally expands beyond the minimum requested examples so the demo exercises the shared carrier pool, cold-start/unscored carriers, assigned completed history, active uncovered recommendations, thin and sufficient lane history, recent operational loads, and planned future work. This is demo coverage, not a claim that these synthetic scenarios represent production market distributions.
- **Frontend.** The broker operations console is delivered in explicit demo mode
  with a broker switcher, lifecycle queue, analytics workspace, carrier drawer,
  and platform assignment overlays. Production authentication and non-demo writes
  remain deferred to platform hardening.
- **Shared carrier pool.** The first backend slice keeps broker-owned identities
  broker-scoped and matches only normalized MC/DOT evidence across opted-in
  brokers. It returns a separate redacted recommendation list with public
  carrier names, opaque HMAC candidate IDs, bucketed evidence, and a minimum of
  three contributing brokers. The requester's own opted-in history contributes.
  Policy changes and every query are audited; on-demand computation makes
  revocation effective immediately. Shared rates, assignment, UI presentation,
  and production identity-provider integration remain deferred to platform
  hardening; the demo path uses signed broker bearer tokens.

## What I'd Do Next With More Time

- Service-layer unit tests for recommendation logic decoupled from HTTP.
- Property-based tests (Hypothesis) for the ingestion adapter, generating random valid payloads and verifying invariants.
- A database-level integration test suite that runs against a real Postgres container to validate `FOR UPDATE` locking and trigger behavior (SQLite is not authoritative for these).
- Benchmark the migration backfill with 100k+ `load_versions` rows to validate the `uuid5` approach at scale (the current bounded retry loop is O(1) for normal cases but acceptable for any realistic dataset).
