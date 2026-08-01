# C2: Containers

**Status: Delivered baseline with demo operations UI and planned containers**

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
| Rate-estimation service | Explainable broker-scoped expected carrier pay | Delivered |

## Deployment Notes

- Docker Compose runs PostgreSQL, the backend, and the React/Vite console.
- The backend container runs Alembic migrations, reconciles legacy demo display
  names without changing stable broker/source IDs, bootstraps sync files, and
  starts Uvicorn.
- The `data/` directory is mounted read-only at `/data`.
- The default test suite uses SQLite; PostgreSQL is the deployment database.
