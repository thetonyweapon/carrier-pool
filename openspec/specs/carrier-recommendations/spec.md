# Carrier Recommendations

**Status: Delivered**

Carrier Recommendations returns deterministic, broker-scoped carrier rankings
for active, uncovered loads. Results are computed on demand from current
canonical rows using the versioned `tx-metro-v1` lane contract and
`carrier-recommendations-v1` scoring contract.

## Requirements

- Recommendations MUST be restricted to carriers owned by the requesting broker.
- A target load MUST be `ACTIVE`, have no assigned carrier, and have a derivable
  primary lane.
- Historical evidence MUST be restricted to broker-owned `DELIVERED` and
  `COMPLETED` loads with an assigned carrier.
- Results MUST be deterministic for unchanged canonical data and scoring versions.
- Each result MUST include explainable factors, evidence counts, and score
  contributions rather than only a numeric score.
- Linked source carrier rows MUST aggregate under their broker-scoped
  `CarrierIdentity`; carriers without identity evidence MUST remain separate.
- A canonical historical load MUST count at most once per logical carrier.
- Exact directional lane, same-metro directional lane, equipment, customer, and
  conservative operational recency factors MUST be reported explicitly.
- Known carriers without eligible history MUST remain visible in a separate
  unscored section and MUST NOT receive a fabricated score.
- Scoring and lane normalization versions MUST be returned and validated.
- Cross-broker carrier and load data MUST NOT influence results.

## HTTP Contract

```text
GET /brokers/{broker_id}/loads/{load_id}/carrier-recommendations
    ?scoring_version=carrier-recommendations-v1
    &normalization_version=tx-metro-v1
    &limit=20
```

- `404` MUST indicate that the load is not owned by the requesting broker or
  does not exist.
- `409` MUST indicate that the target is not active and uncovered.
- `422` MUST indicate unsupported versions, an invalid limit, or a non-derivable
  lane.
- The response MUST identify the target lane, eligible statuses, history window,
  score version, ranked recommendations, and unscored known carriers.
- `limit` MUST bound both ranked and unscored carrier entries; recommendation
  ranks MUST remain the positions from the complete deterministic ranking.

## Scoring Contract

The v1 score uses capped integer contributions:

| Factor | Contribution | Cap |
|---|---:|---:|
| Exact lane, same equipment | 10/load | 3 loads |
| Nearby lane, same equipment | 6/load | 3 loads |
| Exact lane, other equipment | 4/load | 3 loads |
| Nearby lane, other equipment | 2/load | 3 loads |
| Same equipment outside target lane | 3/load | 5 loads |
| Same customer | 2/load | 5 loads |
| Recent operational evidence | 5/3/1 | one factor |
| Overall eligible history | 1/load | 4 loads |

Sort order MUST use score, lane/equipment evidence counts, total evidence,
operational recency, normalized name, candidate kind, and stable candidate key
as deterministic tie-breakers.

## Scenarios

### Exact and nearby ranking

- **Given** an active DFW-to-Houston dry-van load
- **When** one carrier has exact dry-van history and another has only nearby
  same-metro history
- **Then** the exact-history carrier MUST rank first with factor explanations.

### Identity aggregation

- **Given** two source-specific carrier rows linked to one broker-scoped identity
- **When** each row has historical completed loads
- **Then** one logical recommendation MUST aggregate both rows and count each load
  once.

### Cold start

- **Given** a known broker carrier with no eligible completed history
- **When** recommendations are requested
- **Then** the carrier MUST appear in `unscored_carriers` with an explanation and
  MUST NOT be assigned a numeric rank.

### Tenant isolation

- **Given** a matching carrier and history owned by another broker
- **When** one broker requests recommendations
- **Then** the other broker's carrier and history MUST be absent and have no score
  contribution.

## Non-Goals and Limitations

- Availability, capacity, safety, insurance, claims, acceptance, and service
  quality are not represented in current canonical data.
- Historical equipment use is evidence of prior use, not verified fleet capacity.
- Deadhead and current truck location are not estimated; coordinates and routing
  data are not available from current adapters.
- Recommendation results are computed from current canonical state and are not a
  persisted replay of prior rankings.
- History uses the 500 most recently synced eligible loads per broker.
- Cross-broker shared-pool recommendations remain a separate planned capability.
