# C1: System Context

**Status: Delivered baseline with demo operations UI and planned shared-pool/hardening capabilities**

Carrier Pool ingests broker-owned TMS exports into a canonical, tenant-scoped
data model. The current implementation provides ingestion, lane intelligence,
carrier recommendations, carrier rate estimates, and a demo-mode broker
operations workflow; shared-pool behavior and production hardening remain planned.

```mermaid
flowchart LR
    operator[Broker operator]
    ff[FreightFlow TMS]
    hd[HaulDesk TMS]
    bos[BrokerOS TMS]
    files[(Downloaded sync files)]
    postgres[(PostgreSQL)]
    platform[Carrier Pool platform]
    recommendations[Carrier recommendations\ndelivered]
    estimates[Carrier-rate estimates\ndelivered]
    pool[Opt-in shared carrier pool\nplanned]

    operator -->|Demo operations workflow| platform
    ff -->|Exports sync files| files
    hd -->|Exports sync files| files
    bos -->|Exports sync files| files
    files -->|Read-only chronological input| platform
    platform -->|Canonical records and audit history| postgres
    platform --> recommendations
    platform --> estimates
    pool -.-> recommendations
    pool -.-> estimates

    subgraph boundary[Carrier Pool system]
        platform
        recommendations
        estimates
        pool
    end

    classDef delivered fill:#d9ead3,stroke:#38761d,color:#000;
    classDef planned fill:#f3f3f3,stroke:#666,color:#000,stroke-dasharray: 5 5;
    classDef external fill:#fff2cc,stroke:#bf9000,color:#000;
    class platform,files,postgres,recommendations,estimates delivered;
    class pool planned;
    class operator,ff,hd,bos external;
```

## Relationships

- TMSs export files; Carrier Pool does not call TMS APIs.
- Sync files are read-only inputs and are processed one file at a time.
- PostgreSQL stores canonical broker-scoped records and ingestion history.
- Recommendations and future estimates must use broker-owned history by default.
- The shared pool is the only planned cross-broker exception and requires
  explicit opt-in and data-minimization rules.
