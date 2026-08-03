# Production Runbook

This runbook covers the production Compose profile. Replace placeholder values
with managed secrets and provider-specific commands before deployment.

## Prerequisites

- PostgreSQL 16 with backups enabled and a 15-minute recovery point objective.
- A secret manager supplying `DATABASE_URL`, `POSTGRES_*`, `AUTH_*`, and the
  resource-control settings documented in `backend/.env.example`.
- A private filesystem or storage mount for source files under `/data`.
- A deployment identity that can pull the repository and run Docker Compose.

Do not set `DEMO_MODE=true` or `ALLOW_MOCK_AUTH=true` in production. Do not reuse
the fallback secrets from the demo Compose file.

The in-memory demo accounts and `admin` / `admin` credential are not available
in the production profile. Production authentication remains an external
provider integration boundary and must not use local demo account state.

## Deploy

1. Validate the environment and Compose configuration:

   ```bash
   docker compose -f docker-compose.production.yaml config
   ```

2. Build and start the stack:

   ```bash
   docker compose -f docker-compose.production.yaml up --build -d
   ```

3. Verify service state and recent logs:

   ```bash
   docker compose -f docker-compose.production.yaml ps
   docker compose -f docker-compose.production.yaml logs --since=10m backend frontend
   ```

The backend container applies Alembic migrations before starting Uvicorn. Review
the migration output before directing traffic to the frontend.

## Health And Observability

- `/live` verifies that the process is running.
- `/ready` verifies database readiness.
- `/metrics` exposes Prometheus metrics and must remain on the private edge.
- Include the request ID from response headers when escalating an API error.
- Alert on ingestion failures, dead letters, source lag, database pool timeout,
  and elevated request latency.

## Ingestion Worker

The durable worker performs one discovery and processing pass:

```bash
docker compose -f docker-compose.production.yaml run --rm \
  -v /srv/carrier-pool/source-data:/data:ro backend \
  python -m scripts.ingestion_worker --root /data
```

Run it from a scheduler appropriate to the deployment. Keep source files
immutable while they are being discovered. Failed jobs remain retryable through
the job table; dead-lettered jobs require operator review before replay.

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
