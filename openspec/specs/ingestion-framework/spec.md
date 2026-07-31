# Ingestion Framework

**Status: Delivered**

## Requirements

- Each adapter MUST ingest one sync file at a time.
- The complete file operation MUST be transactional and all-or-nothing.
- Raw payload validation MUST happen before domain writes.
- A successful file MUST be identified by broker source and filename plus a
  SHA-256 checksum.
- Re-ingesting the same filename and checksum MUST be a no-op with
  `duplicate=True`.
- Reusing a filename with different content MUST fail.
- A file with a sync timestamp not later than the latest successful file for its
  source MUST fail as out of order.
- Source ingestion MUST serialize concurrent files for the same source.
- CLI adapters MUST accept a broker-source identifier and a JSON file path.
- Adapter failures MUST leave no partial domain records or successful ingestion
  marker.

## Scenarios

### Duplicate file

- **Given** a successful file already exists
- **When** the same source submits the same filename and bytes
- **Then** the adapter MUST report a duplicate and row counts MUST remain
  unchanged.

### Conflicting file

- **Given** a successful file already exists
- **When** the same filename is submitted with different bytes
- **Then** ingestion MUST fail with a conflicting-file error.

### Invalid later record

- **Given** a file contains multiple records
- **When** one record fails validation or normalization
- **Then** the entire file transaction MUST roll back.

## Limitations

- Default tests use SQLite; PostgreSQL is authoritative for row-lock behavior.
