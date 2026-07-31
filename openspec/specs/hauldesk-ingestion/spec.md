# HaulDesk Ingestion

**Status: Delivered**

## Requirements

- The adapter MUST validate flat-table loads, carriers, and rates.
- Naive HaulDesk timestamps MUST be interpreted as `America/Chicago` using DST
  rules, then stored as UTC.
- The source's single pickup and delivery MUST map to two canonical stops.
- Kilograms and kilometers MUST convert to pounds and miles using Decimal
  arithmetic and explicit half-up rounding to one decimal place.
- HaulDesk rate rows MUST be immutable additive journal events.
- Rate-only files MUST update the existing load without requiring a load row.
- Repeated immutable source rate IDs MUST be rejected.
- MC/DOT carrier evidence MUST normalize into the broker-scoped carrier
  identity model.
- Conflicting carrier identity evidence MUST reject the whole file.

## Scenarios

### Rate-only delta

- **Given** a covered load with an existing rate journal
- **When** a later file contains only a new rate row
- **Then** the rate row MUST be appended and the load totals MUST recalculate
  from the complete journal.

### Metric conversion

- **Given** a load with kilograms and kilometers
- **When** it is ingested
- **Then** canonical weight and distance MUST use the documented one-decimal
  rounding rules.

### DST transition

- **Given** an ambiguous or nonexistent Central timestamp
- **When** it is ingested
- **Then** the adapter MUST reject it rather than silently choosing an offset.

## Limitations

- The source schema supports exactly one pickup and one delivery.
- The adapter cannot represent additional HaulDesk stops without a source-schema
  revision.
