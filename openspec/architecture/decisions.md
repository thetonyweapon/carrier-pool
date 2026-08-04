# Architecture Decisions

## File-Based Source Boundary

TMS integrations begin at downloaded JSON files rather than external API
clients. This matches the assignment boundary, makes replay deterministic, and
keeps source systems outside the platform runtime.

## CLI Adapter Boundary

The delivered adapters are Python modules with CLI entry points. They process
one chronological file at a time and share transaction, idempotency, ordering,
and normalization behavior. A scheduler or ingestion API can be added later
without changing source-specific mapping contracts.

## Canonical Database as System of Record

PostgreSQL stores the current canonical state plus raw/normalized versions,
append-only financial history, mutable-rate observations, and file provenance.
The original files remain immutable inputs rather than mutable database blobs.

## Tenant Isolation at the Data Layer

Broker scope is carried through domain rows and composite foreign keys. This is
stronger than relying only on application filters and leaves the shared pool as
an explicit, reviewable exception rather than an accidental leak path.

## Current Container Boundaries

The FastAPI service exposes health, authentication, broker operations, lane
intelligence, recommendation, rate estimation, and shared-pool behavior.
Ingestion is not represented as a background worker because the delivered
workflow is a CLI processing one file at a time. The UI is a delivered demo
container. The shared pool is a data-sharing policy that cuts across these
containers, not a separate runtime container.

## Mermaid in Markdown

Architecture diagrams use Mermaid instead of generated image files so GitHub
renders the diagrams from source and changes remain reviewable in pull requests.

## Deferred Architecture

Durable account storage and parts of platform hardening remain deferred. OIDC
identity integration and the production deployment boundary are delivered.
Lane normalization, carrier recommendations, rate estimation, and shared-pool
results are delivered as on-demand services rather than persisted aggregates.

## Lane Normalization and Aggregation

Lane Intelligence uses a checked-in `tx-metro-v1` ZIP/city-to-metro mapping.
Runtime geocoding and radius matching were deferred because current source
adapters do not populate coordinates and reproducibility is a requirement.
Lanes are directional, equipment is a query dimension rather than part of the
geographic key, and a multi-stop load uses its first pickup-capable and final
delivery-capable stops for the primary lane.

History is computed from current broker-scoped canonical loads, restricted to
delivered and completed statuses. This intentionally avoids mutable counters or
materialized contributions: a corrected stop, status, or equipment value is
immediately reflected without reversing a stale aggregate. The tradeoff is
query work at read time, bounded in the MVP to the 500 most recently synced
eligible loads per broker; persistence or database aggregation can be added after
measuring volume.

## Carrier Recommendation Ranking

Carrier recommendations rank logical broker-owned candidates: linked source rows
aggregate under `CarrierIdentity`, while rows without identity evidence remain
separate. The v1 score uses capped integer contributions for directional lane,
equipment, customer, conservative operational recency, and overall history
evidence. Known carriers without eligible history remain visible separately
without fabricated scores. Availability, deadhead, and service-quality signals
are not inferred from fields that do not exist in the canonical model.

## Carrier Rate Estimation

Rate estimation uses one current effective all-in carrier total per completed
load. It prefers exact directional lane/equipment evidence, then same-metro and
broker-wide tiers over 180 days, retrying over 365 days when necessary. Median
rate-per-mile and observed quartiles are calculated with Decimal half-up rounding.
Insufficient evidence is a normal unavailable result; source audit rows are
explanatory history and are never treated as separate shipments.
