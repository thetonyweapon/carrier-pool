# C3: Backend Components

**Status: Delivered baseline with planned service components**

This view describes the current backend package boundaries. Planned components
are shown only to establish future ownership and integration points.

```mermaid
flowchart TB
    subgraph backend[backend/app]
        main[main.py\ncreate_app]
        health[health.py\nhealth router]
        config[config.py\nsettings]
        database[database.py\nengine and sessions]
        models[models.py\ncanonical entities and constraints]
        common[ingestion/common.py\nshared normalization and identity]
        framework[Adapter transaction boundary\nfile tracking, checksum, ordering]
        ff[ingestion/freightflow.py\nFreightFlow adapter]
        hd[ingestion/hauldesk.py\nHaulDesk adapter]
        bos[ingestion/brokeros.py\nBrokerOS adapter]
        migrations[Alembic migrations\nschema evolution]
        geography[lane_geography.py\nversioned metro normalization]
        lanes[lane_intelligence.py\non-demand lane history]
        recommendation[carrier_recommendations.py\nexplainable ranking]
        estimation[Rate-estimation service\nPLANNED]
    end

    db[(PostgreSQL / SQLite)]
    files[(JSON sync files)]
    http[HTTP clients]
    cli[CLI callers]

    http --> main
    main --> health
    health --> database
    health --> db
    config --> database
    cli --> ff
    cli --> hd
    cli --> bos
    files --> ff
    files --> hd
    files --> bos
    ff --> framework
    hd --> framework
    bos --> framework
    ff --> common
    hd --> common
    bos --> common
    main --> lanes
    main --> recommendation
    lanes --> geography
    lanes --> database
    lanes --> models
    recommendation --> lanes
    recommendation --> models
    framework --> database
    framework --> models
    common --> models
    database --> db
    models --> db
    migrations --> db
    main -.-> estimation
    estimation -.-> models

    classDef delivered fill:#d9ead3,stroke:#38761d,color:#000;
    classDef planned fill:#f3f3f3,stroke:#666,color:#000,stroke-dasharray: 5 5;
    classDef external fill:#fff2cc,stroke:#bf9000,color:#000;
    class main,health,config,database,models,common,framework,ff,hd,bos,migrations,geography,lanes,recommendation delivered;
    class estimation planned;
    class db,files,http,cli external;
```

## Component Responsibilities

- `main.py` constructs the FastAPI application and registers routers.
- `health.py` exposes the synchronous database health check.
- `config.py` loads environment-backed settings.
- `database.py` owns the SQLAlchemy engine, session factory, and dependency.
- `models.py` defines canonical entities, enums, tenant constraints, and
  financial validation.
- The adapter transaction boundary records files, enforces checksums/order, and
  provides all-or-nothing persistence.
- `common.py` centralizes carrier identity normalization and shared upserts.
- Each TMS module owns source schema validation, source-specific mapping, and
  its CLI entry point.
- Alembic owns versioned schema changes and append-only database triggers.
- `lane_geography.py` owns the versioned bundled ZIP/city-to-metro mapping.
- `lane_intelligence.py` derives primary lanes and correction-safe history on
  demand from current broker-scoped canonical rows.
- `carrier_recommendations.py` aggregates logical broker-owned carriers, scores
  historical evidence, and returns deterministic explanations on demand.
- `recommendation_api.py` exposes the broker-scoped recommendation contract.

## Planned Integration Points

- Recommendation logic consumes canonical loads, stops, carriers, and the
  delivered lane-intelligence history contract.
- Rate estimation will consume canonical rate history and lane dimensions.
- Both services must be broker-scoped and expose explanation metadata.
