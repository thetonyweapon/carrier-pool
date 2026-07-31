# Platform Hardening

**Status: Planned**

This is a placeholder engineering capability for reliability and scale work
after the core product workflow exists.

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

- This document does not claim production SLOs or infrastructure changes.
