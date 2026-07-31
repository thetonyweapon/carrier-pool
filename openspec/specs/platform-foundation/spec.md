# Platform Foundation

**Status: Delivered**

## Requirements

### Health and runtime

- The backend MUST expose `GET /health`.
- The health endpoint MUST report failure when the configured database cannot be
  reached.
- The service MUST read configuration from environment-backed settings and MUST
  NOT hardcode deployment database credentials.
- Docker Compose MUST provide the backend and PostgreSQL services for local
  operation.
- The backend container MUST run database migrations before starting the API.

### Source-file boundary

- The Compose deployment MUST mount `data/` read-only at `/data`.
- Ingestion commands MUST read source files without modifying them.

### Verification

- CI MUST run the backend tests, migration checks, Ruff lint, and Ruff format
  checks.
- The default test suite MUST run without an external PostgreSQL instance.
- PostgreSQL-specific lock behavior MUST remain opt-in through
  `HAULDESK_POSTGRES_TEST_URL`.

## Scenarios

### Healthy database

- **Given** the API and PostgreSQL are running
- **When** a client requests `GET /health`
- **Then** the response is successful.

### Unavailable database

- **Given** the API cannot connect to PostgreSQL
- **When** a client requests `GET /health`
- **Then** the response indicates an unhealthy dependency.

## Limitations

- Authentication, authorization, background scheduling, and production-scale
  deployment orchestration are not implemented.
