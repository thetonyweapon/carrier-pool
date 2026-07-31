# BrokerOS Ingestion

**Status: Delivered**

## Requirements

- The adapter MUST validate CRM-style records and reject unknown source fields.
- Customer, carrier, and location references MUST resolve through the same
  file's `referenced_records` object.
- Reference types and required fields MUST be validated before writes.
- BrokerOS timestamps MUST include offsets and MUST be stored in UTC.
- Date-only stop schedules MUST remain date-only; the adapter MUST NOT invent
  appointment timestamps.
- Stops MUST preserve source sequence and resolved location metadata.
- BrokerOS MUST support arbitrary ordered stop counts and pickup/dropoff flags.
- Pounds and kilograms MUST aggregate with Decimal conversion and half-up
  rounding to one decimal pound.
- Mutable customer and carrier totals MUST be stored as append-only rate
  observations, including null, zero, and restatement transitions.
- BrokerOS carrier records MUST NOT be guessed into MC/DOT identity matching
  without source evidence.

## Scenarios

### Reference failure

- **Given** a record references an unknown location or wrong reference type
- **When** the file is ingested
- **Then** the entire file MUST be rejected without partial writes.

### Mutable total

- **Given** a load's customer rate changes between snapshots
- **When** both files are ingested chronologically
- **Then** the current load rate MUST be updated and both observations MUST be
  retained in order.

### Date-only schedule

- **Given** a stop has only a calendar date
- **When** it is normalized
- **Then** `scheduled_date` MUST be populated and timestamp fields MUST remain
  unset.

## Limitations

- The source does not provide stable child-stop IDs.
- The source does not provide MC/DOT carrier evidence.
