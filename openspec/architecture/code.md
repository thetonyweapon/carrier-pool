# C4: Code-Level Responsibilities

**Status: Delivered baseline with guarded shared-pool backend and demo auth**

This is a code-level map of the most important symbols and package groups. It
is intentionally selective; it documents architectural ownership rather than
every class and helper.

```mermaid
flowchart LR
    subgraph entry[Entry points]
        create[app.main.create_app]
        health[app.health.health]
        auth[app.auth / app.auth_api\ndemo auth and authorization]
        operations[app.broker_operations_api\nload and assignment API]
        ingest[ingest_file functions\nFreightFlow / HaulDesk / BrokerOS]
        generate[scripts.generate_synthetic_data.generate]
    end

    subgraph persistence[Persistence and schema]
        session[app.database.get_db / SessionLocal]
        base[app.models.Base]
        entities[Broker, BrokerSource, Customer, Carrier, Load]
        history[LoadVersion, RateLineItem, LoadRateObservation]
        stops[LoadStop]
        files[IngestionFile]
        migrations[backend/alembic/versions]
    end

    subgraph source[Source-specific code]
        shared[app.ingestion.common]
        freight[FreightFlowSync and mapping]
        haul[HaulDeskSync and mapping]
        broker[BrokerOSSync and mapping]
        geography[app.lane_geography\nversioned metro mapping]
        lanes[app.lane_intelligence\nprimary lane and history queries]
        recommendations[app.carrier_recommendations\nversioned carrier ranking]
        pool[app.shared_carrier_pool\nredacted opt-in ranking]
        accounts[app.demo_accounts\nephemeral local accounts]
        estimation[app.rate_estimation\nversioned pay estimation]
    end

    database[(Database)]
    raw[(data/tms_*/*.json)]

    create --> health
    create --> auth
    create --> operations
    auth --> accounts
    health --> session
    session --> database
    ingest --> freight
    ingest --> haul
    ingest --> broker
    freight --> shared
    haul --> shared
    broker --> shared
    lanes --> geography
    lanes --> entities
    lanes --> stops
    lanes --> database
    recommendations --> lanes
    recommendations --> entities
    recommendations --> stops
    recommendations --> database
    pool --> entities
    operations --> entities
    operations --> auth
    pool --> auth
    pool --> database
    estimation --> lanes
    estimation --> entities
    estimation --> history
    estimation --> stops
    estimation --> database
    freight --> base
    haul --> base
    broker --> base
    shared --> entities
    base --> entities
    base --> history
    base --> stops
    base --> files
    entities --> database
    history --> database
    stops --> database
    files --> database
    migrations --> database
    raw --> generate
    generate -.-> ingest

    classDef delivered fill:#d9ead3,stroke:#38761d,color:#000;
    classDef planned fill:#f3f3f3,stroke:#666,color:#000,stroke-dasharray: 5 5;
    classDef external fill:#fff2cc,stroke:#bf9000,color:#000;
    class create,health,auth,operations,accounts,session,base,entities,history,stops,files,migrations,shared,freight,haul,broker,geography,lanes,recommendations,pool,estimation,ingest,generate delivered;
    class database,raw external;
```

## Key Code Contracts

- `create_app()` returns the configured FastAPI application.
- `health()` checks database connectivity and returns an HTTP 503 when the
  database is unavailable.
- Each adapter's `ingest_file(session, broker_source_id, path)` is the
  file-oriented integration boundary.
- `Base` and its mapped classes define canonical persistence and tenant
  constraints.
- `LoadVersion` preserves source and normalized snapshots.
- `RateLineItem` and `LoadRateObservation` preserve distinct additive-journal
  and replacement-observation semantics.
- `generate()` creates deterministic source fixtures without changing
  unrelated files.

## Deferred Code Areas

- Production identity-provider integration in place of the demo token issuer and
  ephemeral local-account layer.
