import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  useNavigate,
  useParams,
  useSearchParams,
  Routes as RouterRoutes,
  Route,
  Navigate,
} from "react-router-dom";
import { api, Carrier, Detail, Load, Recommendation } from "./api";
import "./styles.css";

const money = (v?: string | null) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(Number(v));
const date = (v?: string | null) => {
  if (!v) return "—";
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(v);
  return new Intl.DateTimeFormat(
    undefined,
    dateOnly
      ? { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }
      : { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" },
  ).format(new Date(dateOnly ? `${v}T00:00:00Z` : v));
};
const day = (v?: string | null) =>
  v
    ? new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(`${v.slice(0, 10)}T00:00:00Z`))
    : "—";
function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="state error">
      <b>Could not load this panel</b>
      <span>{error instanceof Error ? error.message : "Unknown error"}</span>
    </div>
  );
}
function AnalyticsError({ error }: { error: unknown }) {
  const status =
    error instanceof Error
      ? (error as Error & { status?: number }).status
      : undefined;
  return status === 409 ? (
    <div className="state">
      <b>Ineligible</b>
      <span>
        {error instanceof Error ? error.message : "This load is ineligible."}
      </span>
    </div>
  ) : status === 422 ? (
    <div className="state">
      <b>Not available for this load</b>
      <span>
        {error instanceof Error
          ? error.message
          : "Analytics are not available for this load."}
      </span>
    </div>
  ) : (
    <ErrorBox error={error} />
  );
}
function Panel({
  title,
  children,
  state,
}: {
  title: string;
  children?: React.ReactNode;
  state?: "loading" | "error" | "unavailable" | "ineligible";
}) {
  const labels = {
    loading: "Loading",
    error: "Error",
    unavailable: "Unavailable",
    ineligible: "Ineligible",
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
        {state && <span className={`signal ${state}`}>{labels[state]}</span>}
      </div>
      {children}
    </section>
  );
}
function Shell({ children }: { children: React.ReactNode }) {
  const [brokers, setBrokers] = useState<{ id: string; name: string }[]>([]);
  const p = useParams();
  const nav = useNavigate();
  useEffect(() => {
    api
      .brokers()
      .then(setBrokers)
      .catch(() => setBrokers([]));
  }, []);
  return (
    <div className="app">
      <header>
        <Link
          className="brand"
          to={`/brokers/${p.brokerId || brokers[0]?.id || ""}/loads`}
        >
          <b>CP</b>
          <span>
            CARRIER POOL<small>OPERATIONS DESK</small>
          </span>
        </Link>
        <div className="demo">DEMO MODE</div>
        <label className="switcher">
          BROKER{" "}
          <select
            value={p.brokerId || ""}
            onChange={(e) => nav(`/brokers/${e.target.value}/loads`)}
            aria-label="Select broker"
          >
            <option value="">Select broker</option>
            {brokers.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div className="notice">
        <strong>DEMO MODE</strong> Assignments are temporary platform overlays
        for evaluation. They do not update canonical TMS state.
      </div>
      {children}
    </div>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={`status ${value}`}>{value.replaceAll("_", " ")}</span>
  );
}
function Queue() {
  const { brokerId } = useParams();
  const [sp, setSp] = useSearchParams();
  const [data, setData] = useState<{
    items: Load[];
    total: number;
    page: number;
    page_size: number;
  } | null>(null);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    search: sp.get("search") || "",
    status: sp.get("status") || "",
    equipment: sp.get("equipment") || "",
    assignment_state: sp.get("assignment_state") || "",
  });
  const page = Number(sp.get("page") || 1);
  useEffect(() => {
    if (!brokerId) return;
    setLoading(true);
    api
      .loads(
        brokerId,
        new URLSearchParams({
          ...filters,
          page: String(page),
          page_size: "25",
        }).toString(),
      )
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [brokerId, sp.toString()]);
  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    setSp(new URLSearchParams({ ...filters, page: "1" }));
  };
  if (!brokerId)
    return (
      <main className="empty">
        <h1>Select a broker</h1>
        <p>
          Choose a broker from the DEMO MODE switcher to open the dispatch
          queue.
        </p>
      </main>
    );
  return (
    <main>
      <div className="page-title">
        <div>
          <p className="eyebrow">BROKER OPERATIONS / LOAD QUEUE</p>
          <h1>Dispatch board</h1>
        </div>
        <span className="count">{data?.total ?? "—"} loads in scope</span>
      </div>
      <form className="filters" onSubmit={apply}>
        <label>
          Search
          <input
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            placeholder="Load number or ID"
          />
        </label>
        <label>
          Status
          <select
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
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
              setFilters({ ...filters, equipment: e.target.value })
            }
          >
            <option value="">All equipment</option>
            <option>dry_van</option>
            <option>reefer</option>
            <option>flatbed</option>
          </select>
        </label>
        <label>
          Assignment
          <select
            value={filters.assignment_state}
            onChange={(e) =>
              setFilters({ ...filters, assignment_state: e.target.value })
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
        <div className="state">Loading queue…</div>
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
              <thead>
                <tr>
                  <th>Load / customer</th>
                  <th>Lane</th>
                  <th>Schedule</th>
                  <th>Equipment</th>
                  <th>Financials</th>
                  <th>Assignment</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((x) => (
                  <tr key={x.id}>
                    <td>
                      <Link
                        className="load-link"
                        to={`/brokers/${brokerId}/loads/${x.id}`}
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
                      {x.origin?.city}, {x.origin?.state}
                      <b> → </b>
                      {x.destination?.city}, {x.destination?.state}
                    </td>
                    <td>{date(x.next_schedule)}</td>
                    <td>
                      <Status value={x.equipment_type} />
                      <small>
                        {x.weight_lbs
                          ? `${Number(x.weight_lbs).toLocaleString()} lb`
                          : ""}{" "}
                        {x.distance_miles
                          ? `${Number(x.distance_miles).toLocaleString()} mi`
                          : ""}
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
              disabled={page <= 1}
              onClick={() =>
                setSp(
                  new URLSearchParams({ ...filters, page: String(page - 1) }),
                )
              }
            >
              ← Prev
            </button>
            <button
              disabled={page * data.page_size >= data.total}
              onClick={() =>
                setSp(
                  new URLSearchParams({ ...filters, page: String(page + 1) }),
                )
              }
            >
              Next →
            </button>
          </div>
        </>
      )}
    </main>
  );
}
function Financials({ load }: { load: Load }) {
  const margin = load.margin ? Number(load.margin) : null;
  const pct =
    margin !== null && Number(load.customer_rate)
      ? (margin / Number(load.customer_rate)) * 100
      : null;
  return (
    <div className="financials">
      <div>
        <small>CUSTOMER RATE</small>
        <b>{money(load.customer_rate)}</b>
      </div>
      <div>
        <small>CARRIER PAY</small>
        <b>{money(load.carrier_rate)}</b>
      </div>
      <div className="accent">
        <small>MARGIN</small>
        <b>{money(margin?.toFixed(2))}</b>
        <span>{pct === null ? "—" : `${pct.toFixed(1)}%`}</span>
      </div>
    </div>
  );
}
function Analytics({ b, l }: { b: string; l: string }) {
  const [lane, setLane] = useState<any>(null),
    [rate, setRate] = useState<any>(null),
    [recs, setRecs] = useState<any>(null);
  const [errs, setErrs] = useState<Record<string, unknown>>({});
  useEffect(() => {
    const ctrl = new AbortController();
    const requests: Array<[string, Promise<any>, (value: any) => void]> = [
      ["lane", api.lane(b, l, ctrl.signal), setLane],
      ["rate", api.rate(b, l, ctrl.signal), setRate],
      ["recs", api.recs(b, l, ctrl.signal), setRecs],
    ];
    requests.forEach(([key, p, setter]) => {
      p.then(setter).catch((e) => {
        if (e.name !== "AbortError") setErrs((x) => ({ ...x, [key]: e }));
      });
    });
    return () => ctrl.abort();
  }, [b, l]);
  const failure = (k: string) =>
    errs[k] ? (
      <AnalyticsError error={errs[k]} />
    ) : (
      <div className="state">Loading…</div>
    );
  return (
    <div className="analytics">
      <Panel title="Lane intelligence">
        {errs.lane ? (
          <AnalyticsError error={errs.lane} />
        ) : lane ? (
          <>
            <div className="lane-route">
              {lane.lane.origin.metro_name || lane.lane.origin.exact_key}
              <b>→</b>
              {lane.lane.destination.metro_name ||
                lane.lane.destination.exact_key}
            </div>
            <p className="muted">
              {lane.history.exact_count} exact · {lane.history.nearby_count}{" "}
              nearby historical loads
            </p>
            <span className="tag">{lane.history.data_sufficiency} data</span>
            {lane.history.fallback_reason && (
              <p className="note">{lane.history.fallback_reason}</p>
            )}
          </>
        ) : (
          failure("lane")
        )}
      </Panel>
      <Panel
        title="Carrier rate estimate"
        state={
          rate?.status?.toLowerCase() === "unavailable"
            ? "unavailable"
            : undefined
        }
      >
        {errs.rate ? (
          <AnalyticsError error={errs.rate} />
        ) : rate?.status?.toLowerCase() === "unavailable" ? (
          <div className="state">
            <b>Unavailable</b>
            <span>Rate estimate unavailable for this load.</span>
          </div>
        ) : rate ? (
          <>
            <div className="estimate">
              {money(rate.estimate.amount)}{" "}
              <span>
                {rate.estimate.low && rate.estimate.high
                  ? `${money(rate.estimate.low)}–${money(rate.estimate.high)}`
                  : ""}
              </span>
            </div>
            <p className="muted">
              {rate.confidence.level} confidence · {rate.population.sample_size}{" "}
              samples · {rate.population.lookback_days || "—"}d lookback
            </p>
            {rate.confidence.reasons?.map((x: string) => (
              <div className="reason" key={x}>
                + {x}
              </div>
            ))}
          </>
        ) : (
          failure("rate")
        )}
      </Panel>
      <Panel title="Carrier recommendations">
        {errs.recs ? (
          <AnalyticsError error={errs.recs} />
        ) : recs ? (
          <>
            <div className="rec-list">
              {recs.recommendations.map((x: Recommendation) => (
                <RecommendationRow key={x.candidate_id} item={x} b={b} l={l} />
              ))}
            </div>
            <h4 className="subhead">UNSCORED / INSUFFICIENT HISTORY</h4>
            {recs.unscored_carriers.map((x: any) => (
              <div className="unscored" key={x.candidate_id}>
                <span>{x.name}</span>
                <small>{x.reason}</small>
              </div>
            ))}
          </>
        ) : (
          failure("recs")
        )}
      </Panel>
    </div>
  );
}
function RecommendationRow({
  item,
  b,
  l,
}: {
  item: Recommendation;
  b: string;
  l: string;
}) {
  const nav = useNavigate();
  return (
    <button
      className="rec-row"
      onClick={() =>
        nav(
          `/brokers/${b}/loads/${l}?candidate=${encodeURIComponent(item.candidate_id)}`,
        )
      }
    >
      <strong>#{item.rank}</strong>
      <span>
        <b>{item.name}</b>
        <small>{item.factors[0]?.explanation || item.data_sufficiency}</small>
      </span>
      <em>{item.score}</em>
    </button>
  );
}
function DetailPage() {
  const { brokerId, loadId } = useParams();
  const [load, setLoad] = useState<Detail>();
  const [error, setError] = useState<unknown>();
  const [analyticsRefresh, setAnalyticsRefresh] = useState(0);
  const [sp, setSp] = useSearchParams();
  const candidate = sp.get("candidate");
  const refresh = () => {
    if (brokerId && loadId)
      api.detail(brokerId, loadId).then(setLoad).catch(setError);
  };
  useEffect(refresh, [brokerId, loadId]);
  if (error)
    return (
      <main>
        <ErrorBox error={error} />
      </main>
    );
  if (!load || !brokerId || !loadId)
    return <main className="state">Loading load context…</main>;
  return (
    <main>
      <Link className="back" to={`/brokers/${brokerId}/loads`}>
        ← Back to queue
      </Link>
      <div className="detail-title">
        <div>
          <p className="eyebrow">LOAD DETAIL / {load.source.name}</p>
          <h1>{load.display_number}</h1>
          <p>
            {load.customer.name} · <Status value={load.status} />
          </p>
        </div>
        <div className="detail-meta">
          <div className="assignment-summary">
            <small>EFFECTIVE PLATFORM ASSIGNMENT</small>
            <b><Status value={load.assignment.state} /></b>
            {load.assignment.state === "assigned" && (
              <span>Assigned carrier: {load.assignment.carrier?.name || "—"}</span>
            )}
            <small>CANONICAL TMS CARRIER</small>
            <span>{load.carrier?.name || "Unassigned"}</span>
          </div>
          <span>LAST SYNCED {date(load.freshness.last_synced_at)}</span>
          {load.freshness.age_seconds > 86400 && (
            <b className="stale">STALE DATA</b>
          )}
        </div>
      </div>
      <Financials load={load} />
      <section className="context">
        <div>
          <small>ORIGIN</small>
          <b>
            {load.origin?.city}, {load.origin?.state}
          </b>
        </div>
        <div>
          <small>DESTINATION</small>
          <b>
            {load.destination?.city}, {load.destination?.state}
          </b>
        </div>
        <div>
          <small>EQUIPMENT</small>
          <b>{load.equipment_type}</b>
        </div>
        <div>
          <small>WEIGHT / DISTANCE</small>
          <b>
            {load.weight_lbs
              ? `${Number(load.weight_lbs).toLocaleString()} lb`
              : "—"}{" "}
            /{" "}
            {load.distance_miles
              ? `${Number(load.distance_miles).toLocaleString()} mi`
              : "—"}
          </b>
        </div>
        <div>
          <small>EFFECTIVE PLATFORM ASSIGNMENT</small>
          <b><Status value={load.assignment.state} /></b>
        </div>
        {load.assignment.state === "assigned" && (
          <div>
            <small>ASSIGNED CARRIER (PLATFORM)</small>
            <b>{load.assignment.carrier?.name || "—"}</b>
          </div>
        )}
        <div>
          <small>CANONICAL TMS CARRIER</small>
          <b>{load.carrier?.name || "Unassigned"}</b>
        </div>
      </section>
      <Panel title="Stop timeline">
        <div className="timeline">
          {load.stops.map((s) => (
            <div className="stop" key={s.id}>
              <i></i>
              <div>
                <small>
                  {s.stop_type.toUpperCase()} · STOP {s.sequence_number}
                </small>
                <b>
                  {s.location_name || `${s.city}, ${s.state} ${s.postal_code}`}
                </b>
                <span>
                  {day(s.scheduled_date)}{" "}
                  {s.scheduled_start_at
                    ? `· ${date(s.scheduled_start_at)}`
                    : ""}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
      <Analytics key={analyticsRefresh} b={brokerId} l={loadId} />
      {candidate && (
        <CandidateDrawer
          b={brokerId}
          l={loadId}
          candidate={candidate}
          version={load.assignment.assignment_version}
          onClose={() => setSp({})}
          onAssigned={() => {
            refresh();
            setAnalyticsRefresh((x) => x + 1);
          }}
        />
      )}
    </main>
  );
}
function CandidateDrawer({
  b,
  l,
  candidate,
  version,
  onClose,
  onAssigned,
}: {
  b: string;
  l: string;
  candidate: string;
  version: number;
  onClose: () => void;
  onAssigned: () => void;
}) {
  const [data, setData] = useState<any>();
  const [err, setErr] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string>();
  useEffect(() => {
    api.candidate(b, candidate).then(setData).catch(setErr);
  }, [b, candidate]);
  useEffect(() => {
    const f = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, [onClose]);
  const assign = async (carrier?: Carrier) => {
    setBusy(true);
    try {
      await api.assign(b, l, {
        carrier_id: carrier?.id,
        candidate_id: candidate,
        expected_assignment_version: version,
        demo_actor: "demo-user",
      });
      setResult("Assignment overlay created");
      onAssigned();
    } catch (e) {
      setResult(e instanceof Error ? e.message : "Assignment failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <aside
        className="drawer"
        aria-label="Carrier candidate details"
        tabIndex={-1}
      >
        <button
          className="close"
          onClick={onClose}
          aria-label="Close carrier details"
        >
          ×
        </button>
        {err ? (
          <ErrorBox error={err} />
        ) : !data ? (
          <div className="state">Loading carrier…</div>
        ) : (
          <>
            <p className="eyebrow">CANDIDATE DETAIL</p>
            <h2>{data.name}</h2>
            <div className="identity">
              <b>MC {data.mc_number || "—"}</b>
              <b>DOT {data.dot_number || "—"}</b>
            </div>
            <h4>CONTACT / MEMBER RECORDS</h4>
            {data.carriers.map((c: any) => (
              <div className="member" key={c.id}>
                <b>{c.name}</b>
                <span>
                  {c.home_city || "—"}, {c.home_state || "—"} ·{" "}
                  {c.phone_number || "No phone"}
                </span>
                <small>
                  MC {c.mc_number || "—"} · DOT {c.dot_number || "—"} · Source{" "}
                  {c.source_id}
                </small>
                <button
                  className="primary full"
                  disabled={busy}
                  onClick={() => assign(c)}
                >
                  Assign overlay to this carrier
                </button>
              </div>
            ))}
            {result && (
              <div className={result.includes("created") ? "success" : "error"}>
                {result}
              </div>
            )}
            <p className="disclaimer">
              Demo assignment only. This writes a platform overlay and does not
              alter canonical TMS carrier or load state.
            </p>
          </>
        )}
      </aside>
    </div>
  );
}
function BrokerLanding() {
  const [brokers, setBrokers] = useState<{ id: string; name: string }[]>([]);
  const nav = useNavigate();
  useEffect(() => {
    api
      .brokers()
      .then(setBrokers)
      .catch(() => setBrokers([]));
  }, []);
  return (
    <main className="empty">
      <p className="eyebrow">CARRIER POOL / DEMO ACCESS</p>
      <h1>Choose an operations desk</h1>
      <p>
        Select a broker workspace to review loads, evidence, and carrier
        decisions.
      </p>
      <div className="broker-choices">
        {brokers.map((b) => (
          <button
            key={b.id}
            className="choice"
            onClick={() => nav(`/brokers/${b.id}/loads`)}
          >
            <b>{b.name}</b>
            <span>{b.id}</span>
          </button>
        ))}
      </div>
      {brokers.length === 0 && (
        <div className="state error">
          No demo brokers are available. Start the backend with DEMO_MODE
          enabled and load the demo dataset.
        </div>
      )}
    </main>
  );
}
function App() {
  return (
    <Shell>
      <RouterRoutes>
        <Route path="/brokers" element={<BrokerLanding />} />
        <Route path="/brokers/:brokerId/loads" element={<Queue />} />
        <Route
          path="/brokers/:brokerId/loads/:loadId"
          element={<DetailPage />}
        />
        <Route path="*" element={<Navigate to="/brokers" replace />} />
      </RouterRoutes>
    </Shell>
  );
}
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);
