# Synthetic Dataset

**Status: Delivered**

## Requirements

- The repository MUST contain the 44 historical sync files per TMS for July
  6-16, 2026 at 00:00, 06:00, 12:00, and 18:00, plus 16 operational sync files
  per TMS for July 29-August 1, 2026 at the same intervals.
- Each sync file MUST contain 1-3 records and conform to its TMS schema.
- The dataset MUST include full load lifecycles, amounts appearing as known,
  corrections, rich and thin lane history, and carrier experience contrast.
- Day 11 loads MUST use stable IDs across their four syncs and remain active and
  uncovered for recommendation testing.
- The operational window MUST include recent lifecycle/correction examples,
  active uncovered examples for exact-lane, nearby-lane, and thin-history
  workflows, and planned uncovered loads with September 2026 pickup dates.
- Files MUST be generated deterministically from fixed scenarios.
- Regeneration MUST overwrite only expected dated filenames.
- `--clean` MUST remove only expected dated filenames and MUST preserve unrelated
  JSON files.
- Validation MUST cover chronological ingestion, normalized values, tenant
  ownership, duplicate idempotency, and reproducibility against checked-in
  output.

## Scenarios

### Reproducible generation

- **Given** two empty output roots
- **When** the generator runs for both roots
- **Then** every relative path and file hash MUST match.

### Non-destructive regeneration

- **Given** an unrelated JSON file in an output directory
- **When** the generator runs with or without `--clean`
- **Then** the unrelated file MUST remain.

### Day 11 target

- **Given** all syncs are ingested in chronological order
- **When** the Day 11 loads are queried
- **Then** their IDs MUST be stable, status MUST be active, and carrier MUST be
  absent.

### Operational demo window

- **Given** the operational syncs are ingested after the historical files
- **When** the August 1 loads are queried
- **Then** active demo targets MUST remain uncovered and planned September loads
  MUST remain unassigned and have future pickup dates.

## Limitations

- The dataset is synthetic and intentionally focused on the Texas Triangle.
- It does not claim to validate recommendation quality; recommendation logic is
  delivered separately and the dataset provides deterministic scenarios for its
  integration tests.
