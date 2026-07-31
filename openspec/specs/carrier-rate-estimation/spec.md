# Carrier Rate Estimation

**Status: Delivered**

Carrier Rate Estimation returns a deterministic, broker-scoped estimate of
all-in carrier pay for active, uncovered loads. The service computes from
current canonical rows and returns an explicit unavailable result when no
configured evidence population is sufficient.

## Requirements

- Estimates MUST be restricted to the requesting broker.
- The target MUST be `ACTIVE`, uncovered, and have a derivable primary lane.
- Historical evidence MUST use `COMPLETED` loads only.
- Each historical load MUST contribute at most one effective carrier-pay total.
- Null and nonpositive effective pay totals MUST be excluded and reported.
- Results MUST identify the lane scope, equipment scope, lookback, sample size,
  exclusions, calculation method, confidence, and version metadata.
- `missing_distance_from_rpm` MUST count positive-rate observations that are
  unavailable to RPM calculations; exact-lane raw-total calculations MAY still
  use those observations.
- Estimates MUST use Decimal arithmetic and round half-up to cents.
- Thin populations MUST fall back through an explicit deterministic hierarchy.
- Insufficient history MUST return HTTP 200 with `status: unavailable` rather
  than fabricate a price or return a transport error.
- Results MUST be deterministic for unchanged canonical data and versions.

## HTTP Contract

```text
GET /brokers/{broker_id}/loads/{load_id}/carrier-rate-estimate
    ?estimation_version=carrier-rate-estimation-v1
    &normalization_version=tx-metro-v1
```

- `404` indicates a missing or foreign load.
- `409` indicates a target that is not active and uncovered.
- `422` indicates an unsupported version or non-derivable target lane.
- `200` returns either `status: estimated` or `status: unavailable`.
- Money and distance values are serialized as strings to preserve precision.

## Estimation Contract

The estimator uses one current `Load.carrier_rate` per completed historical
load. This avoids double-counting FreightFlow replacement snapshots, BrokerOS
replacement observations, and HaulDesk pay line items.

The rate date is selected as `booked_at`, then `source_updated_at`, then
`last_synced_at`. The primary lookback is 180 days; the same hierarchy is
retried over 365 days.

Within a selected population, the central estimate is the median carrier-pay
rate per mile multiplied by the target distance. The low and high values are
the observed 25th and 75th percentiles. Exact-lane populations may use median
all-in totals when the target distance is missing; broad populations require
positive distance.

All money calculations use Decimal and `ROUND_HALF_UP` to cents. Currency is
reported as USD under the current canonical data contract.

## Fallback Hierarchy

Tiers are attempted in order for each lookback window:

| Tier | Population | Minimum |
|---|---|---:|
| `exact_lane_equipment` | Exact directional ZIP lane + equipment | 3 |
| `metro_lane_equipment` | Same directional metro lane + equipment | 3 |
| `exact_lane_any_equipment` | Exact directional lane + known equipment | 3 |
| `metro_lane_any_equipment` | Same directional metro lane + known equipment | 3 |
| `broker_equipment` | Broker-wide target equipment | 3 |
| `broker_any_equipment` | Broker-wide known equipment | 5 |

Unknown target equipment skips equipment-specific tiers. Reverse lanes are not
used as fallbacks. Estimates use the delivered `tx-metro-v1` normalization
contract.

## Scenarios

### Rich exact history

- **Given** at least three completed loads on the target directional lane and
  equipment
- **When** an active uncovered target requests an estimate
- **Then** the exact lane/equipment tier MUST be selected with median RPM and
  explainable evidence metadata.

### Thin history

- **Given** fewer than three exact lane/equipment observations
- **When** a broader population meets its threshold
- **Then** the broader tier MUST be selected and disclosed in the response.

### Unavailable estimate

- **Given** no configured population meets its minimum
- **When** a valid active target requests an estimate
- **Then** the service MUST return `status: unavailable` with attempted tiers.

### Correction safety

- **Given** a source correction or restatement
- **When** current canonical rows are queried
- **Then** the corrected effective total MUST affect future estimates without
  counting historical audit rows as separate shipments.

### Tenant isolation

- **Given** matching evidence owned by another broker
- **When** a broker requests an estimate
- **Then** the other broker's data MUST not contribute.

## Non-Goals and Limitations

- Current availability, capacity, fuel decomposition, safety, claims, and
  service quality are not estimated.
- The estimator does not use reverse lanes, market indexes, or machine learning.
- Cross-broker shared-pool pricing and multi-currency support remain deferred.
- Estimates are computed on demand and are not persisted historical replays.
- Confidence is qualitative data sufficiency, not a calibrated probability.
- History is bounded to the 500 most recently synced completed loads.
