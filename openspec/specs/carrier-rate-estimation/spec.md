# Carrier Rate Estimation

**Status: Planned**

This is a placeholder capability. No carrier-rate estimation service or API is
currently implemented.

## Intended Outcome

Estimate what a broker should expect to pay a carrier for an active load using
that broker's historical data and explain the evidence behind the estimate.

## Planned Requirements

- Estimates MUST use only the requesting broker's permitted historical data.
- An estimate MUST identify the source population, lane scope, equipment scope,
  and time window used.
- Exact-lane history SHOULD be preferred when sufficient.
- Thin exact-lane history MUST fall back to an explicitly disclosed broader
  population rather than silently presenting false precision.
- The response MUST include a confidence or data-sufficiency indicator.
- Currency and rounding rules MUST be explicit and consistent with canonical
  financial precision.
- Corrections and append-only rate history MUST be handled without double
  counting replacement snapshots.

## Open Decisions

- Statistical method: median, trimmed mean, quantile, or model-based estimate.
- Minimum sample sizes and outlier treatment.
- How to incorporate fuel, accessorials, and equipment premiums.
- Whether estimates are computed on demand or materialized.

## Planned Scenarios

- A rich exact lane produces a narrow, explainable estimate.
- A thin lane falls back to nearby or equipment-compatible history and discloses
  the fallback.
- A corrected or restated source rate changes future estimates without mutating
  the audit history.

## Dependencies

- Depends on lane intelligence and canonical rate history.
