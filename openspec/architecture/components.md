# C3: Backend Components

**Status: Delivered backend components for the API, demo auth, operations, and shared pool**

This view describes the current backend package boundaries. Production identity
provider integration remains a future boundary rather than a runtime component.

```mermaid
flowchart TB
    subgraph backend[backend/app]
        main[main.py\ncreate_app]
        health[health.py\nhealth router]
        auth[auth.py / auth_api.py\ndemo auth and authorization]
        accounts[demo_accounts.py\nephemeral local accounts]
        operations[broker_operations_api.py\nloads and assignments]
        sharedpool[shared_carrier_pool.py / shared_carrier_pool_api.py\nredacted shared pool]
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
        estimation[rate_estimation.py\nexplainable pay estimate]
    end

    db[(PostgreSQL / SQLite)]
    files[(JSON sync files)]
    http[HTTP clients]
    cli[CLI callers]

    http --> main
    main --> health
    main --> auth
    main --> operations
    main --> sharedpool
    auth --> accounts
    auth --> models
    operations --> auth
    operations --> models
    sharedpool --> auth
    sharedpool --> models
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
    main --> estimation
    lanes --> geography
    lanes --> database
    lanes --> models
    recommendation --> lanes
    recommendation --> models
    estimation --> lanes
    estimation --> models
    framework --> database
    framework --> models
    common --> models
    database --> db
    models --> db
    migrations --> db

    classDef delivered fill:#d9ead3,stroke:#38761d,color:#000;
    classDef planned fill:#f3f3f3,stroke:#666,color:#000,stroke-dasharray: 5 5;
    classDef external fill:#fff2cc,stroke:#bf9000,color:#000;
    class main,health,auth,accounts,operations,sharedpool,config,database,models,common,framework,ff,hd,bos,migrations,geography,lanes,recommendation,estimation delivered;
    class db,files,http,cli external;
```

## Component Responsibilities

- `main.py` constructs the FastAPI application and registers routers.
- `health.py` exposes the synchronous database health check.
- `auth.py` verifies demo bearer tokens and enforces broker/admin scope.
- `auth_api.py` exposes demo broker discovery, login, account, and profile
  endpoints; `demo_accounts.py` keeps local account state in process memory.
- `broker_operations_api.py` exposes broker-scoped load, carrier, and assignment
  contracts.
- `shared_carrier_pool.py` and `shared_carrier_pool_api.py` compute and expose
  authenticated, redacted cross-broker recommendations and aggregate rates.
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
- `rate_estimation.py` computes versioned, explainable all-in carrier-pay
  estimates from canonical completed-load history.
- `rate_estimation_api.py` exposes the broker-scoped rate-estimation contract.

## Integration Points

- Recommendation logic consumes canonical loads, stops, carriers, and the
  delivered lane-intelligence history contract.
- Rate estimation consumes canonical rate history and lane dimensions.
- Both services must be broker-scoped and expose explanation metadata.
- The operations and shared-pool routers use the same authenticated principal
  boundary; production identity-provider integration replaces only the demo
  issuer and account layer.
