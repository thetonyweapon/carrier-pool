# Canonical Data Model

**Status: Delivered**

## Requirements

### Tenant isolation

- Every broker-owned domain record MUST carry `broker_id`.
- Relationships between broker-owned records MUST enforce broker scope through
  composite foreign keys.
- A record from one broker MUST NOT reference a customer, carrier, load, stop,
  rate, or source belonging to another broker.
- Shared carrier identity MUST remain broker-scoped until the shared-carrier-pool
  capability is explicitly implemented.

### Canonical entities

- The model MUST represent brokers, broker sources, customers, carriers, loads,
  stops, load versions, rate line items, and ingestion files.
- Loads MUST use the canonical lifecycle: planned, active, covered, in transit,
  delivered, and completed.
- TMS equipment values MUST map to a canonical equipment enum; ambiguous values
  MUST map to `UNKNOWN` rather than being guessed.
- Load versions MUST preserve both the raw source payload and normalized fields.

### Financial history

- `RateLineItem` MUST be append-only.
- Rate corrections MUST be represented by additional journal rows rather than
  updates or deletes.
- Mutable replacement totals MUST use append-only observations when their
  source semantics require snapshots.
- Monetary values MUST use Decimal currency validation at the application and
  database-binding boundaries.

### Carrier identity

- MC/DOT evidence MAY link source-specific carrier rows within one broker.
- Complementary MC-only and DOT-only evidence MAY be merged.
- Contradictory identity evidence MUST reject the sync rather than overwrite
  existing evidence.
- Carrier identity matching MUST be serialized for concurrent source updates.

## Scenarios

### Cross-tenant reference

- **Given** a load owned by broker A
- **When** it is assigned a customer or carrier owned by broker B
- **Then** database constraints MUST reject the write.

### Rate correction

- **Given** an existing rate journal
- **When** a source reports a correction
- **Then** the original row MUST remain unchanged and a new row MUST record the
  correction.

## Limitations

- Lane intelligence is computed on demand; no persisted lane assignment or
  materialized analytics model exists yet.
