# Broker Operations UI

**Status: Delivered (demo mode)**

The broker operations backend and React/Vite console are implemented for a
development-only broker switcher workflow. Production authentication remains a
platform-hardening follow-up.

## Intended Outcome

Give a broker a clear view of active loads, expected carrier pay, ranked carrier
recommendations, and the reasons behind both answers.

## Requirements

- The UI MUST show a broker-scoped load list.
- An active-load view MUST show pickup, delivery, equipment, schedule, weight,
  and current financial context.
- The UI MUST show the estimated carrier rate with evidence and confidence.
- The UI MUST show ranked carriers with human-readable explanations.
- Empty, sparse-history, stale-data, and error states MUST be explicit.
- The UI MUST NOT expose data outside the selected broker scope. The current
  broker switcher is explicitly demo-only and MUST NOT be treated as production
  authorization.
- Desktop and mobile layouts MUST remain usable for the core workflow.

## Backend Contract

- `GET /brokers/{broker_id}/loads` returns all lifecycle statuses with
  `page`, `page_size`, and `total`; it supports `status`, `equipment`,
  `assignment_state`, and `search` filters. Results sort by pickup schedule,
  display number, and id. Currency, weight, and distance values are strings.
- `GET /brokers/{broker_id}/loads/{load_id}` returns ordered stops and the same
  canonical and effective-assignment context as the list response.
- `GET /brokers/{broker_id}/carrier-candidates/{candidate_id}` accepts
  `carrier:<id>` and `identity:<id>` candidate keys and is broker scoped.
- `GET /demo/brokers` and assignment creation are disabled unless `DEMO_MODE`
  is true. Assignment creation uses `expected_assignment_version` and returns
  `409` on stale versions or ineligible canonical targets.
- Platform assignments are current overlays. They never change canonical
  `Load.carrier_id` or `Load.status`; active overlays make recommendation and
  rate-estimation requests ineligible with `409`.
- `POST /brokers/{broker_id}/loads/{load_id}/assignments` is enabled only in
  `DEMO_MODE`, requires an expected assignment version, and appends an audit
  event for every assignment or replacement.

## Frontend Contract

- The console uses `/brokers` and `/brokers/{broker_id}/loads` plus
  `/brokers/{broker_id}/loads/{load_id}` routes.
- The queue shows all lifecycle statuses with server-side filters and
  pagination. Analytics are loaded independently on the detail view.
- Date-only schedules remain calendar dates; timestamps render in browser-local
  time. Data older than 24 hours is visibly stale.
- Carrier detail exposes broker-owned contact information and clearly labels
  assignment overlays as non-TMS demo writes.

## Open Decisions

- Authentication and broker session model.
- API shape and pagination strategy.
- Whether explanations are generated entirely by the backend.
- Which filters and sorting controls are essential for the first release.

## Scenarios

- A broker opens an active load and understands which carrier to call first and
  why within one screen.
- A sparse-history result explains its fallback instead of showing an empty
  score.
- A failed recommendation request preserves the load context and shows a
  recoverable error.

## Dependencies

- Depends on carrier recommendations and carrier-rate estimation APIs.

## Deferred

- Production authentication, authorized broker sessions, and non-demo writes.
