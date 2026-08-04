# Production Runbook

This runbook covers the production Compose profile. Replace placeholder values
with managed secrets and provider-specific commands before deployment.

## Prerequisites

- Managed PostgreSQL 16 with backups enabled and a 15-minute recovery point objective.
- A secret manager supplying `DATABASE_URL`, `AUTH_ISSUER`, `AUTH_AUDIENCE`,
  `AUTH_JWKS_URL`, `AUTH_LOGIN_URL`, `AUTH_TOKEN_URL`, `AUTH_CLIENT_ID`,
  `AUTH_REDIRECT_URI`, `ALLOWED_HOSTS`, and the
  resource-control settings documented in `backend/.env.example`.
- A private filesystem or storage mount for source files under `/data`.
- `INGESTION_DATA_PATH` set to that private source-data mount for the worker.
- A deployment identity that can pull the repository and run Docker Compose.

Do not set `DEMO_MODE=true` or `ALLOW_MOCK_AUTH=true` in production. Do not reuse
the fallback secrets from the demo Compose file.

The in-memory demo accounts and `admin` / `admin` credential are not available
in the production profile. Production authentication uses the configured
external OIDC provider and must not use local demo account state.

## Deploy

1. Validate the environment and Compose configuration:

   ```bash
   docker compose -f docker-compose.production.yaml config --quiet
   ```

2. Build the images and run the one-off migration job:

   ```bash
   docker compose -f docker-compose.production.yaml build
   docker compose -f docker-compose.production.yaml run --rm migrate

3. Start the application stack after the migration succeeds:

   ```bash
   docker compose -f docker-compose.production.yaml up -d --no-deps backend ingestion-worker frontend
   ```

4. Verify service state and recent logs:

   ```bash
   docker compose -f docker-compose.production.yaml ps
   docker compose -f docker-compose.production.yaml logs --since=10m backend ingestion-worker frontend
   ```

The production edge must sit behind an HTTPS load balancer or reverse proxy that
redirects HTTP to HTTPS and forwards only the approved public host. The database
URL must use `postgresql+psycopg` with `sslmode=require` or stronger. Do not expose
the backend or database directly. The frontend production build contains no demo
login or local account flow and requires `AUTH_LOGIN_URL` for the provider login.

## Health And Observability

- `/live` verifies that the process is running.
- `/ready` verifies database readiness; application startup also rejects invalid
  production auth and database configuration.
- `/metrics` exposes Prometheus metrics and must remain on the private edge.
- Include the request ID from response headers when escalating an API error.
- Alert on ingestion failures, dead letters, source lag, database pool timeout,
  and elevated request latency.

## Ingestion Worker

The durable worker continuously polls for new files, leases jobs in source
chronological order, renews leases during long processing, retries transient
failures with bounded backoff, and records permanent failures as dead letters.
Start it as part of the production Compose stack:

```bash
   docker compose -f docker-compose.production.yaml up -d ingestion-worker
```

Keep source files immutable while they are being discovered. Failed jobs remain
retryable through the job table; dead-lettered jobs require operator review
before replay. The worker has no public network port.

## Database Recovery

1. Stop application writers while preserving the database volume or managed
   database endpoint.
2. Restore the latest verified backup into an isolated PostgreSQL instance.
3. Validate Alembic state and representative tenant counts before cutover.
4. Repoint `DATABASE_URL`, start the backend, and verify `/ready` plus ingestion
   idempotency before reopening traffic.
5. Record restore duration, recovered timestamp, and any replayed jobs.

Never use an unreviewed migration downgrade as a recovery mechanism. Restore a
backup and apply forward migrations instead.

## Incident Response

- Authentication or tenant-isolation concern: remove traffic, preserve logs,
  rotate affected secrets, and invalidate tokens.
- Database saturation: reduce worker concurrency, inspect pool timeout metrics,
  and stop expensive ad hoc queries before scaling the database.
- Ingestion backlog: inspect lease age and failure class, then replay only after
  confirming the source file checksum and idempotency key.
- Deployment failure: keep the previous image available, capture migration and
  health logs, and roll traffic back only after confirming schema compatibility.

Document the incident, affected broker IDs, request IDs, timestamps, recovery
actions, and follow-up issue links.
