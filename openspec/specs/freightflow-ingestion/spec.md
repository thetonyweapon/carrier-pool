# FreightFlow Ingestion

**Status: Delivered**

## Requirements

- The adapter MUST validate FreightFlow sync payloads with the documented
  schema.
- FreightFlow replacement snapshots MUST update the current load state rather
  than creating additive rate journal rows for every snapshot.
- FreightFlow statuses MUST map to the canonical lifecycle.
- Carrier, customer, equipment, weight, mileage, rates, and ordered stops MUST
  be normalized into canonical records.
- Source timestamps MUST include timezone information and be stored in UTC.
- A load's first covered-or-later state MUST establish its booking timestamp.
- FreightFlow corrections to mutable snapshot details MUST update the current
  normalized state while preserving the raw/load-version history.

## Scenarios

### Lifecycle snapshot

- **Given** snapshots for one shipment progress from quoting through completed
- **When** files are ingested chronologically
- **Then** the canonical load MUST end in `COMPLETED`, with the latest normalized
  values and preserved versions.

### Corrected snapshot

- **Given** a prior shipment mileage or customer-rate value
- **When** a later snapshot reports a correction
- **Then** the canonical current value MUST reflect the correction and the
  earlier payload MUST remain reconstructable.

## Limitations

- The adapter supports the source's represented stop fields and does not invent
  physical stop identity beyond the source payload.
