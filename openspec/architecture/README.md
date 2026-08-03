# C4 Architecture

These documents describe Carrier Pool using the C4 model. Mermaid diagrams are
used so the architecture renders directly in GitHub without generated image
artifacts.

## Model Levels

| Level | Document | Scope |
|---|---|---|
| C1 | [System Context](context.md) | People, external systems, and Carrier Pool |
| C2 | [Containers](containers.md) | Runtime and deployment boundaries |
| C3 | [Components](components.md) | Backend component responsibilities |
| C4 | [Code](code.md) | Important packages, entry points, and model groups |

## Status Conventions

- Solid nodes and edges represent delivered behavior.
- Dashed nodes and edges represent planned capabilities.
- The platform boundary excludes source TMS systems and external operators.

The diagrams distinguish delivered carrier recommendations, rate estimation,
demo-mode operations, and the authenticated shared-carrier-pool path from
production hardening work that remains planned.

## Related Documents

- [Architecture decisions](decisions.md)
- [OpenSpec project overview](../project.md)
- [Platform foundation](../specs/platform-foundation/spec.md)
- [Ingestion framework](../specs/ingestion-framework/spec.md)
- [Canonical data model](../specs/canonical-data-model/spec.md)
- [Lane intelligence](../specs/lane-intelligence/spec.md)
- [Carrier recommendations](../specs/carrier-recommendations/spec.md)
- [Carrier rate estimation](../specs/carrier-rate-estimation/spec.md)
- [Broker operations UI](../specs/broker-operations-ui/spec.md)
- [Shared carrier pool](../specs/shared-carrier-pool/spec.md)
- [Platform hardening](../specs/platform-hardening/spec.md)
