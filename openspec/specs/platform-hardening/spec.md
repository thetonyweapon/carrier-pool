# Platform Hardening

**Status: Partially delivered**

The production authentication and deployment boundary, plus the PostgreSQL
integration gate, are delivered. Remaining reliability and scale work continues
after the core product workflow.

## Execution Contract

The hardening program covers the production boundary around the delivered
domain workflow. It MUST preserve broker tenant isolation, append-only financial
history, chronological ingestion, and the existing source-file semantics.

The implementation sequence is:

1. Planning and hardening contract
2. Mock authentication and tenant authorization
3. Production deployment hardening
4. PostgreSQL-authoritative integration tests
5. Durable ingestion control plane
6. Observability and operational health
7. Assignment and write concurrency
8. Scale, resource, and performance controls
9. Property-based adapter testing
10. CI and supply-chain hardening
11. Production runbooks and documentation

Each milestone MUST be delivered in its own pull request. Before merge, the
milestone MUST receive a code review, all critical/high/medium findings MUST be
fixed, all lower-severity findings MUST be filed as GitHub issues on the fork
unless an existing issue already covers them, and required CI MUST be green.

The hardening implementation uses a provider-neutral authentication boundary
with deterministic mock issuer/JWKS responses for tests and a configured
OIDC/JWKS verifier for the production deployment.

Production defaults are managed PostgreSQL, a separate production deployment
profile from demo Compose, a filesystem-polling ingestion worker behind a
storage abstraction, structured JSON logs, Prometheus metrics, and
OpenTelemetry traces.

Initial engineering targets are Python 3.12 and PostgreSQL 16 in production,
with the existing Python 3.9 package compatibility contract tested where
practical. The initial service targets are p95 under 500 ms for paginated load
list/detail requests and p95 under 2 seconds for broker-scoped analytics on a
representative 100,000-load tenant. Initial recovery targets are RPO 15 minutes
and RTO 1 hour; these are engineering targets, not infrastructure guarantees.

## Intended Outcome

Increase confidence in production behavior, performance, and operational safety
without changing source semantics or tenant boundaries.

## Planned Requirements

- Real PostgreSQL integration tests MUST cover row locks, triggers, migrations,
  and transaction rollback behavior.
- Property-based tests SHOULD exercise valid and invalid adapter payloads.
- Recommendation and estimation logic SHOULD have service-layer tests separate
  from HTTP tests.
- Migration backfills MUST be benchmarked with representative large datasets.
- Observability SHOULD expose ingestion duration, failure class, source lag, and
  transaction outcomes without logging sensitive raw payloads.
- Operational failures MUST be retryable only when idempotency guarantees make
  retries safe.

## Open Decisions

- CI matrix for Python, PostgreSQL, and migration versions.
- Load-test dataset size and performance targets.
- Metrics, tracing, and alerting stack.
- Retry and dead-letter policy for scheduled ingestion.

## Planned Scenarios

- Concurrent PostgreSQL ingestions for one source serialize without duplicate
  or out-of-order state.
- A migration upgrade and downgrade round trip preserves required data.
- A failed file can be retried safely without duplicate financial events.

## Non-Goals

- This document does not claim production availability, capacity, or SLO
  compliance; the targets above are engineering verification targets.
- This program does not implement TMS API clients or a hosted queue service.
