# Shared Carrier Pool

**Status: Delivered (authenticated demo path)**

The authenticated path is implemented behind `SHARED_POOL_READ_ENABLED`.
Demo deployments use the signed mock issuer; production deployments use the
configured OIDC/JWKS identity provider.

## Intended Outcome

Allow a broker to opt into carefully bounded use of carrier knowledge from other
participating brokers without exposing confidential source data.

## Requirements

- Participation MUST be an explicit broker-level opt-in.
- Non-participating broker data MUST NOT influence shared-pool results.
- Shared results MUST expose only the minimum approved carrier facts and MUST
  NOT expose source broker identity, customer identity, rates, raw payloads, or
  confidential shipment history.
- A shared carrier result MUST be distinguishable from a broker-owned result.
- Broker-owned data MUST remain the default and MUST take precedence when
  applicable.
- Every shared-pool query MUST be auditable by policy version and participating
  scope.
- Opt-out MUST prevent future use and define treatment of previously derived
  materialized results.

## Delivered V1 Boundary

- Shared recommendations are returned from a separate endpoint and MUST NOT be
  merged into broker-owned rankings.
- The requesting broker's opted-in history MAY contribute to its shared result.
- A result MUST have evidence from at least three distinct opted-in brokers.
- Cross-broker matching uses normalized MC/DOT evidence without merging
  broker-scoped `CarrierIdentity` rows.
- Shared output MAY include an explicitly approved shared display name, but MUST omit MC/DOT values,
  source broker and carrier IDs, customer data, rates, raw payloads, exact
  source lanes, and precise operational timestamps.
- Evidence counts are bucketed and candidate IDs are opaque HMAC-derived values.
- Shared candidates are informational and MUST NOT resolve through the local
  assignment API.
- Shared rate estimates MAY return privacy-safe aggregate amounts only after the
  same three-broker threshold is met; source rates and dates MUST remain hidden.
- Shared reads and policy changes MUST carry a broker-scoped authenticated token.

## Remaining Decisions

- Whether sharing requires carrier consent or only broker contractual policy.
- Whether future versions may add other public carrier attributes.
- How revocation should invalidate any future cache or materialized result.

The initial policy decisions are explicitly approved shared display names,
requester contribution, a three-broker minimum, on-demand computation so
revocation takes effect on the next query, and rate aggregation without source
disclosure. Policy changes are
recorded as append-only events and every shared recommendation/rate query
records its participant-scope digest.

## Scenarios

- An opted-in broker receives an eligible shared carrier suggestion labeled as
  shared, without seeing the contributing broker.
- A non-opted-in broker receives no shared suggestions and its data contributes
  nothing to the pool.
- A carrier's shared result excludes customer names, source rates, raw loads,
  and other broker-confidential fields.

## Non-Goals

- This capability does not merge tenant rows or weaken canonical foreign-key
  isolation.
