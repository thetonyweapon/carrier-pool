# C2: Containers

**Status: Delivered baseline with authenticated shared-pool workflow**

Containers are logical runtime or deployment units. The current system has a
FastAPI foundation, a React/Vite operations console, and CLI ingestion modules
rather than a background ingestion service.

```mermaid
flowchart TB
    operator[Broker operator]
    tms[FreightFlow / HaulDesk / BrokerOS]
    files[(Host data directory\nread-only in Compose)]

    subgraph system[Carrier Pool platform]
        ui[Broker operations UI\nReact/Vite\ndemo mode delivered]
        api[Backend API\nFastAPI\noperations and analytics endpoints delivered]
        cli[Ingestion adapters\nPython CLI modules\nDelivered]
        rec[Recommendation service\nDelivered]
        pool[Shared-pool service\nAuthenticated and redacted]
        rate[Rate-estimation service\nDelivered]
        db[(Canonical database\nPostgreSQL 16\nDelivered)]
    end

    tms -->|Plain JSON sync exports| files
    files -->|Chronological file path| cli
    cli -->|Normalized records\ntransactions and audit history| db
    operator -->|Demo browser workflow| ui
    ui -.-> api
    api --> db
    api --> rec
    api --> rate
    rec --> db
    pool --> db
    rate --> db

    classDef delivered fill:#d9ead3,stroke:#38761d,color:#000;
    classDef planned fill:#f3f3f3,stroke:#666,color:#000,stroke-dasharray: 5 5;
    classDef external fill:#fff2cc,stroke:#bf9000,color:#000;
    class api,cli,db,files,rec,rate,ui delivered;
    class operator,tms external;
```

## Container Responsibilities

| Container | Responsibility | Status |
|---|---|---|
| Backend API | FastAPI health, lane intelligence, recommendation, and rate-estimation endpoints | Delivered |
| Ingestion adapters | Validate, normalize, and transactionally ingest one file | Delivered |
| Canonical database | Tenant-scoped state, versions, journals, and observations | Delivered |
| Sync-file directory | Immutable input boundary for downloaded exports | Delivered |
| Operations UI | Lifecycle load queue, detail workspace, analytics, and demo assignment overlay | Delivered (demo mode) |
| Recommendation service | Explainable broker-scoped carrier ranking | Delivered |
| Shared-pool service | Opt-in, redacted cross-broker carrier ranking/rates and query audit | Delivered (demo auth) |
| Rate-estimation service | Explainable broker-scoped expected carrier pay | Delivered |

## Deployment Notes

- Docker Compose runs PostgreSQL, the backend, and the React/Vite console.
- The demo backend container runs Alembic migrations and bootstraps sync files
  before Uvicorn. Production runs migrations in a separate one-off job and the
  API process only starts after that job succeeds.
- The `data/` directory is mounted read-only at `/data`.
- The default test suite uses SQLite; PostgreSQL is the deployment database.
- Shared-pool reads are disabled by default. Enabling them requires an opaque-ID
  secret and broker bearer authentication. Demo Compose uses a signed mock token
  issuer; production uses the configured OIDC/JWKS identity provider and
  verified tenant claim.
