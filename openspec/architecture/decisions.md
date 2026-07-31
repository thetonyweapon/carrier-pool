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

## Current versus Planned Containers

The FastAPI service currently exposes health behavior only. Ingestion is not
represented as a background worker because the delivered workflow is a CLI
processing one file at a time. Recommendation, rate-estimation, and UI
containers are shown as planned in C2 rather than inferred as existing. The
shared pool is a data-sharing policy that cuts across those containers, not a
separate runtime container.

## Mermaid in Markdown

Architecture diagrams use Mermaid instead of generated image files so GitHub
renders the diagrams from source and changes remain reviewable in pull requests.

## Deferred Architecture

Lane normalization, recommendations, rate estimation, UI, shared pool, and
platform hardening remain separate capabilities. Separating them prevents the
current ingestion architecture from claiming product behavior that has not yet
been designed or implemented.
