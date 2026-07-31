# Broker Operations UI

**Status: Planned**

This is a placeholder capability. The repository contains only a Vite/React
stub; no working operations UI exists.

## Intended Outcome

Give a broker a clear view of active loads, expected carrier pay, ranked carrier
recommendations, and the reasons behind both answers.

## Planned Requirements

- The UI MUST show a broker-scoped load list.
- An active-load view MUST show pickup, delivery, equipment, schedule, weight,
  and current financial context.
- The UI MUST show the estimated carrier rate with evidence and confidence.
- The UI MUST show ranked carriers with human-readable explanations.
- Empty, sparse-history, stale-data, and error states MUST be explicit.
- The UI MUST NOT expose data outside the authenticated broker scope.
- Desktop and mobile layouts MUST remain usable for the core workflow.

## Open Decisions

- Authentication and broker session model.
- API shape and pagination strategy.
- Whether explanations are generated entirely by the backend.
- Which filters and sorting controls are essential for the first release.

## Planned Scenarios

- A broker opens an active load and understands which carrier to call first and
  why within one screen.
- A sparse-history result explains its fallback instead of showing an empty
  score.
- A failed recommendation request preserves the load context and shows a
  recoverable error.

## Dependencies

- Depends on carrier recommendations and carrier-rate estimation APIs.
