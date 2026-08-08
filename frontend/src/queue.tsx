import React, { useEffect, useState } from "react";
import { Link, useLocation, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { api, Load } from "./api";
import { DEMO_LABEL, DEMO_MODE } from "./env";
import { date, location, money } from "./formatters";
import {
  buildQueueSearchParams,
  parseQueueSearchParams,
  QueueFilters,
} from "./query";
import { ShellContext } from "./shell";
import { ErrorBox, isAbortError, Status } from "./ui";

export function Queue() {
  const { brokerId } = useParams();
  const { authBrokerId, authIsAdmin, authLoading, activeBrokerName, authError } = useOutletContext<ShellContext>();
  const [sp, setSp] = useSearchParams();
  const routeLocation = useLocation();
  const applied = parseQueueSearchParams(sp);
  const [data, setData] = useState<{
    items: Load[];
    total: number;
    page: number;
    page_size: number;
  } | null>(null);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<QueueFilters>(applied.filters);
  useEffect(() => {
    setFilters(applied.filters);
  }, [sp.toString()]);
  useEffect(() => {
    if (!brokerId || (!authIsAdmin && authBrokerId !== brokerId)) return;
    const controller = new AbortController();
    let current = true;
    setLoading(true);
    setData(null);
    setError(undefined);
    const params = buildQueueSearchParams(applied.filters, applied.page);
    params.set("page_size", "25");
    api
      .loads(brokerId, params.toString(), controller.signal)
      .then((nextData) => current && setData(nextData))
      .catch((nextError) => {
        if (current && !isAbortError(nextError)) setError(nextError);
      })
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
      controller.abort();
    };
  }, [brokerId, authBrokerId, authIsAdmin, sp.toString()]);
  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    setSp(buildQueueSearchParams(filters, 1));
  };
  if (!brokerId)
    return (
      <main id="main-content" className="empty">
        <h1>Select a broker</h1>
        <p>
          {DEMO_MODE
            ? `Choose a broker from the ${DEMO_LABEL} switcher to open the dispatch queue.`
            : "Choose a broker workspace to open the dispatch queue."}
        </p>
      </main>
    );
  if (authError)
    return (
      <main id="main-content">
        <ErrorBox error={authError} />
      </main>
    );
  if (authLoading || (!authIsAdmin && authBrokerId !== brokerId))
    return <main className="state" role="status">Authenticating broker workspace…</main>;
  return (
    <main id="main-content">
      <div className="page-title">
        <div>
          <p className="eyebrow">BROKER OPERATIONS / {activeBrokerName || brokerId} / LOAD QUEUE</p>
          <h1>Dispatch board</h1>
        </div>
        <span className="count">{data?.total ?? "—"} loads in scope</span>
      </div>
      <form className="filters" onSubmit={apply}>
        <label>
          Search
          <input
            value={filters.search}
            onChange={(e) => setFilters((current) => ({ ...current, search: e.target.value }))}
            placeholder="Load number or ID"
          />
        </label>
        <label>
          Status
          <select
            value={filters.status}
            onChange={(e) => setFilters((current) => ({ ...current, status: e.target.value }))}
          >
            <option value="">All lifecycle</option>
            {[
              "planned",
              "active",
              "covered",
              "in_transit",
              "delivered",
              "completed",
            ].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
        <label>
          Equipment
          <select
            value={filters.equipment}
            onChange={(e) =>
              setFilters((current) => ({ ...current, equipment: e.target.value }))
            }
          >
            <option value="">All equipment</option>
            <option>dry_van</option>
            <option>reefer</option>
            <option>flatbed</option>
            <option>unknown</option>
          </select>
        </label>
        <label>
          Assignment
          <select
            value={filters.assignment_state}
            onChange={(e) =>
              setFilters((current) => ({ ...current, assignment_state: e.target.value }))
            }
          >
            <option value="">Any assignment</option>
            <option value="assigned">Assigned overlay</option>
            <option value="unassigned">Unassigned</option>
          </select>
        </label>
        <button className="primary">Apply filters</button>
      </form>
      {loading ? (
        <div className="state" role="status">Loading queue…</div>
      ) : error ? (
        <ErrorBox error={error} />
      ) : !data?.items.length ? (
        <div className="state">
          <b>No loads match this view.</b>
          <span>Try clearing one or more filters.</span>
        </div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">Dispatch loads</caption>
              <thead>
                <tr>
                  <th scope="col">Load / customer</th>
                  <th scope="col">Lane</th>
                  <th scope="col">Schedule</th>
                  <th scope="col">Equipment</th>
                  <th scope="col">Financials</th>
                  <th scope="col">Assignment</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((x) => (
                  <tr key={x.id}>
                    <td>
                      <Link
                        className="load-link"
                        to={`/brokers/${brokerId}/loads/${x.id}`}
                        state={{ from: `${routeLocation.pathname}${routeLocation.search}` }}
                      >
                        {x.display_number}
                      </Link>
                      <small>{x.customer.name}</small>
                      {x.freshness.age_seconds > 86400 && (
                        <span className="stale">
                          STALE {Math.floor(x.freshness.age_seconds / 86400)}d
                        </span>
                      )}
                    </td>
                    <td>
                      {location(x.origin)}
                      <b> → </b>
                      {location(x.destination)}
                    </td>
                    <td>{date(x.next_schedule)}</td>
                    <td>
                      <Status value={x.equipment_type} />
                      <small>
                        {x.weight_lbs ? `${Number(x.weight_lbs).toLocaleString()} lb` : "—"}{" "}
                        {x.distance_miles ? `${Number(x.distance_miles).toLocaleString()} mi` : "—"}
                      </small>
                    </td>
                    <td>
                      <b>{money(x.customer_rate)}</b>
                      <small>
                        Pay {money(x.carrier_rate)} ·{" "}
                        <em>{money(x.margin)} margin</em>
                      </small>
                    </td>
                    <td>
                      {x.assignment.state === "assigned" ? (
                        <>
                          <Status value="assigned" />
                          <small>
                            {x.assignment.carrier?.name || "Overlay"}
                          </small>
                        </>
                      ) : (
                        <span className="muted">Unassigned</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <span>
              Page {data.page} of{" "}
              {Math.max(1, Math.ceil(data.total / data.page_size))}
            </span>
            <button
              disabled={applied.page <= 1}
              onClick={() => setSp(buildQueueSearchParams(applied.filters, applied.page - 1))}
            >
              ← Prev
            </button>
            <button
              disabled={applied.page * data.page_size >= data.total}
              onClick={() => setSp(buildQueueSearchParams(applied.filters, applied.page + 1))}
            >
              Next →
            </button>
          </div>
        </>
      )}
    </main>
  );
}
