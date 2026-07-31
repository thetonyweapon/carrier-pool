# Carrier Recommendations

**Status: Planned**

This is a placeholder capability. No recommendation service or ranking API is
currently implemented.

## Intended Outcome

For each broker's active load, return a ranked list of that broker's carriers
with transparent reasons for each ranking.

## Planned Requirements

- Recommendations MUST be restricted to the requesting broker's carriers.
- Results MUST be deterministic for the same canonical data and scoring version.
- Each result MUST include explainable factors rather than only a numeric score.
- Ranking SHOULD consider lane experience, equipment fit, historical outcomes,
  recency, and estimated deadhead where data exists.
- Sparse-history carriers MUST not be automatically excluded solely for lacking
  history.
- The response MUST identify data sufficiency and fallback behavior.
- Recommendation calculations MUST be versioned so historical explanations can
  be reproduced.

## Open Decisions

- Score weights and tie-breaking rules.
- How recent delivery location is represented and expires.
- Minimum evidence thresholds and cold-start treatment.
- Whether unavailable carriers are filtered or returned with an explanation.

## Planned Scenarios

- A carrier with strong exact-lane experience ranks above a carrier with only
  broad regional history, with reasons shown.
- A carrier with thin history remains eligible when equipment and geography fit.
- A broker cannot observe or be influenced by another broker's carriers.

## Dependencies

- Depends on lane intelligence and canonical historical data.
- The operations UI consumes this capability but does not define its scoring.
