# Lane Intelligence

**Status: Delivered**

Lane Intelligence derives directional lane keys and broker-scoped history from
the current canonical `Load` and `LoadStop` rows. Results are computed on demand;
no derived lane tables or materialized aggregates are maintained.

## Requirements

- Location normalization MUST use the deterministic, bundled `tx-metro-v1`
  geography map.
- ZIP+4 values MUST normalize to their five-digit ZIP; city/state fallback MUST
  be used when a ZIP is not mapped.
- Unknown locations MUST receive a stable local key and MUST NOT fall back to a
  whole-state lane.
- Lanes MUST be directional. `DFW>HOUSTON` and `HOUSTON>DFW` are distinct.
- The exact endpoint key MUST remain distinct from the metro fallback key.
- The first pickup-capable stop and final delivery-capable stop MUST define the
  primary lane. Intermediate stops are retained in canonical data but do not
  create segment lanes in this version.
- Equipment MUST be an aggregate filter and MUST NOT change the geographic lane
  key.
- History MUST be restricted to the requesting broker and to `DELIVERED` and
  `COMPLETED` loads.
- Each canonical load MUST count at most once, regardless of how many source
  versions or sync files mention it.
- Exact history and same-metro history MUST be reported separately.
- A result MUST include the normalization version, eligible statuses, sample
  counts, selected scope, and data sufficiency.
- Corrections to current canonical stop, status, or equipment values MUST affect
  future results without duplicating the load.

## HTTP Contract

```text
GET /brokers/{broker_id}/loads/{load_id}/lane-intelligence
    ?normalization_version=tx-metro-v1
```

The endpoint returns the target lane, exact and same-metro history counts,
equipment-compatible counts, and an explicit fallback reason. The first
implementation uses a sufficiency threshold of three unique loads: sufficient
exact history is preferred, then sufficient same-metro history, then thin exact
or same-metro history. Reverse-direction history is never silently included.

## Scenarios

### Suburb normalization

- **Given** Plano 75024 to Katy 77494
- **When** lane intelligence is requested
- **Then** the result MUST identify the directional metro lane `DFW>HOUSTON`
  while preserving distinct ZIP endpoint keys.

### Exact versus nearby history

- **Given** a Dallas 75201 to Houston 77002 active load with no exact history
- **When** two same-direction DFW-to-Houston historical loads exist
- **Then** exact count MUST be zero, nearby count MUST be two, and the selected
  scope MUST explicitly identify the nearby fallback.

### Tenant isolation and directionality

- **Given** matching loads owned by two brokers or by the reverse direction
- **When** one broker requests lane intelligence
- **Then** the other broker's and reverse-direction loads MUST not affect the
  result.

### Correction safety

- **Given** a historical load whose destination changes from Houston to Sugar
  Land
- **When** lane intelligence is recalculated
- **Then** the load MUST contribute once to its corrected exact lane and MUST no
  longer contribute to the old exact lane.

## Non-Goals and Limitations

- Recommendation ranking and carrier-rate estimation remain separate capabilities.
- Nearby means the same mapped directional metro pair; radius/geospatial matching
  is not implemented because current adapters do not populate coordinates.
- There is no persisted lane assignment or aggregate table in this version.
- History considers the 500 most recently synced eligible loads per broker; a
  database-backed aggregate or pagination is needed for larger history windows.
- The demo workflow authenticates broker access with signed bearer tokens, while
  production uses the configured OIDC/JWKS provider; the broker path remains
  request context and is never trusted by itself.
