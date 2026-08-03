# Carrier Pool Problem Statement

This document preserves the original product problem and evaluation constraints
for the Carrier Pool project. The implementation-specific documentation lives in
`README.md`, `DECISIONS.md`, and `openspec/`.

## The World

A **freight broker** is a middleman:

- **Customers (shippers)** — companies that have goods to move.
- **Carriers** — trucking companies that move the goods.
- The customer pays the broker one amount (**customer rate**). The broker
  (ideally) pays the carrier a smaller amount (**carrier rate**). The broker
  keeps the difference (**margin**).

Each shipment is called a **load**: a pickup place, a delivery place, the truck
type needed (dry van, refrigerated, flatbed, etc.), dates, and weight.

A load goes through statuses as it moves through real life:

| Status | Plain meaning |
|---|---|
| `PLANNED` | The customer asked the broker to move this load; nothing has happened yet |
| `ACTIVE` | The broker is now searching for a carrier to take it |
| `COVERED` | A carrier said yes and is booked; the price the broker will pay them is now fixed |
| `IN_TRANSIT` | The truck is on the road |
| `DELIVERED` | The goods arrived |
| `COMPLETED` | All paperwork is done and the final money amounts are confirmed |

Loads can be updated or corrected at any point; freight data is messy.

Two more concepts:

- A **lane** is a from-to pair. A carrier that has handled many loads on or near
  a lane is likely to be a good fit for the next load on it.
- **Deadhead** is the empty distance a truck drives to reach a pickup. Carriers
  generally prefer to minimize it.

## The Problem

The platform serves **multiple freight brokers**:

- Each broker runs a different TMS (Transportation Management System), so each
  broker's data arrives in a different shape.
- Every day, each broker gets new loads and updates to existing loads.

For a broker's `ACTIVE` load, the platform must answer:

1. Which of the broker's carriers should be called first, and why?
2. What should the broker expect to pay a carrier for this load?

Both answers must come from the broker's own historical data. The broker must
be able to understand the explanation, not just see a score or price.

The optional shared carrier pool lets brokers opt into carefully bounded use of
carrier knowledge from other participating brokers. Any implementation must
clearly define what crosses the broker boundary and what remains private.

## Starting Data

Raw TMS exports are already present under `data/`. The repository contains three
fictional TMS schemas:

- `data/tms_a_freightflow/`
- `data/tms_b_hauldesk/`
- `data/tms_c_brokeros/`

The `example_sync.jsonc` files document each source schema. Generated sync files
are plain JSON named `{YYYY-MM-DD}T{HH-MM}_sync.json`.

## Constraints

- Do not build or fake the TMS APIs; process the downloaded files.
- Each TMS is synced every six hours at 00:00, 06:00, 12:00, and 18:00.
- Each sync contains one to three loads: everything created or changed since
  the previous sync.
- Synthetic data covers the Texas Triangle and is designed to exercise the
  system's behaviors rather than provide random noise.
- The data includes full lifecycles, corrections, rich and thin lane history,
  experienced and sparse carriers, and fresh uncovered target loads.
- Ingestion processes one sync file at a time in chronological order.
- Broker data must remain isolated. The shared pool is the only deliberate,
  opt-in cross-broker exception.
- The project must document how to run it and reproduce its results.

## Evaluation Focus

The important deliverable is the reasoning behind the implementation:

- How corrected loads affect historical analytics.
- How lanes are defined when stops are in nearby suburbs.
- How scoring remains useful for carriers with little history.
- How estimates behave when exact-lane evidence is sparse.
- What shared-pool data crosses the tenant boundary and how leakage is avoided.

`DECISIONS.md` records the choices, trade-offs, limitations, and deferred work
for this implementation.
