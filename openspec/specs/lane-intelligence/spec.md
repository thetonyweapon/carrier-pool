# Lane Intelligence

**Status: Planned**

This is a placeholder capability. No lane table, lane normalization service, or
lane-level aggregate is currently implemented.

## Intended Outcome

Represent and query meaningful freight lanes from pickup and delivery locations,
including nearby Texas Triangle suburbs and metro areas.

## Planned Requirements

- The system SHOULD normalize pickup and delivery locations into stable metro,
  region, and optionally geospatial buckets.
- A lane definition MUST avoid treating an entire state as one useful lane.
- Exact-lane history SHOULD be distinguishable from nearby-lane fallback history.
- Lane normalization MUST be deterministic and versionable.
- Lane derivation MUST remain broker-scoped unless an explicit shared-pool rule
  permits otherwise.
- Historical corrections MUST not silently corrupt previously computed lane
  aggregates.

## Open Decisions

- Which geospatial source and radius define nearby locations?
- Are lane keys directional and equipment-specific?
- How are multi-stop loads represented?
- Are aggregates materialized incrementally or rebuilt from canonical history?

## Planned Scenarios

- Dallas suburb to Houston suburb resolves to a useful directional lane.
- Exact history is preferred when sufficient; nearby history is used with an
  explicit fallback explanation when exact history is sparse.
- A corrected historical load updates derived aggregates without changing the
  raw audit record.

## Non-Goals

- This document does not implement recommendation ranking or pricing.
