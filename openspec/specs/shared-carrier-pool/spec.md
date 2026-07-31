# Shared Carrier Pool

**Status: Planned**

This is an explicitly deferred bonus capability. No cross-broker pool behavior
is currently implemented.

## Intended Outcome

Allow a broker to opt into carefully bounded use of carrier knowledge from other
participating brokers without exposing confidential source data.

## Planned Requirements

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

## Open Decisions

- Which carrier attributes may cross broker boundaries?
- Whether sharing requires carrier consent or contractual policy.
- How to aggregate and anonymize lane experience.
- How revocation propagates to caches and derived scores.

## Planned Scenarios

- An opted-in broker receives an eligible shared carrier suggestion labeled as
  shared, without seeing the contributing broker.
- A non-opted-in broker receives no shared suggestions and its data contributes
  nothing to the pool.
- A carrier's shared result excludes customer names, source rates, raw loads,
  and other broker-confidential fields.

## Non-Goals

- This capability does not merge tenant rows or weaken canonical foreign-key
  isolation.
