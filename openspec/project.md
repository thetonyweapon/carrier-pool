# Carrier Pool OpenSpec

## Purpose

Carrier Pool serves freight brokers who ingest load data from different TMSs and
need explainable carrier recommendations and carrier-rate estimates for active
loads.

## Current Baseline

The delivered baseline covers the backend foundation, canonical multi-tenant
model, three chronological file-ingestion adapters, deterministic synthetic
data, on-demand broker-scoped lane intelligence, explainable carrier
recommendations, carrier rate estimation, a demo operations UI, and an
   authenticated shared-carrier-pool path. Production OIDC/JWKS deployment
   boundary, PostgreSQL integration gate, durable worker, observability, resource
   controls, property tests, CI hardening, and production runbooks are delivered;
   durable local accounts remain planned.

## System Boundaries

- Raw TMS exports already exist under `data/`; the platform does not implement
  TMS APIs.
- Each broker owns its source data and canonical records.
- Cross-broker data sharing is prohibited unless the shared-carrier-pool
  capability is explicitly enabled and its sharing rules are satisfied.
- Source files are read-only inputs and must remain reproducible.

## Technology Baseline

- Python FastAPI backend.
- SQLAlchemy 2.0 and Alembic.
- PostgreSQL in deployment; SQLite is used for the default isolated tests.
- Pydantic v2 for source validation.
- React/Vite broker operations console with a documented demo-mode workflow.

## OpenSpec Conventions

- A requirement marked `MUST` is normative.
- A requirement marked `MUST NOT` is a prohibited behavior.
- Scenarios describe observable acceptance behavior.
- `Status: Delivered` means the repository currently implements and tests the
  capability.
- `Status: Planned` means this document is a placeholder and does not claim
  implementation.
- Known limitations are recorded rather than silently generalized.

## Capability Map

| Capability | Status |
|---|---|
| Platform foundation | Delivered |
| Canonical data model | Delivered |
| Ingestion framework | Delivered |
| FreightFlow ingestion | Delivered |
| HaulDesk ingestion | Delivered |
| BrokerOS ingestion | Delivered |
| Synthetic dataset | Delivered |
| Lane intelligence | Delivered |
| Carrier recommendations | Delivered |
| Carrier rate estimation | Delivered |
| Broker operations UI | Delivered (demo mode) |
| Shared carrier pool | Delivered (authenticated demo path) |
| Platform hardening | Delivered (milestones 1-11) |

## Architecture

The system architecture is documented with C4 models:

- [C4 architecture overview](architecture/README.md)
- [C1 system context](architecture/context.md)
- [C2 containers](architecture/containers.md)
- [C3 backend components](architecture/components.md)
- [C4 code responsibilities](architecture/code.md)
- [Architecture decisions](architecture/decisions.md)
