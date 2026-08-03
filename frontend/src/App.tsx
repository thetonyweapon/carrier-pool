import React, { useEffect, useRef, useState } from "react";
import {
  Link,
  Outlet,
  useLocation,
  useNavigate,
  useOutletContext,
  useParams,
  useSearchParams,
  Routes as RouterRoutes,
  Route,
  Navigate,
} from "react-router-dom";
import {
  api,
  Carrier,
  Candidate,
  DemoBroker,
  Detail,
  Lane,
  Load,
  Profile,
  Rate,
  Recommendation,
  Recs,
  clearAuthToken,
  hasAuthToken,
  setAuthToken,
  SharedPolicy,
  SharedRate,
  SharedRecs,
} from "./api";
import { date, day, location, money, percentage } from "./formatters";
import {
  buildQueueSearchParams,
  EMPTY_QUEUE_FILTERS,
  parseQueueSearchParams,
  QueueFilters,
} from "./query";
import "./styles.css";

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="state error" role="alert">
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
type ShellContext = {
  brokers: DemoBroker[];
  brokerLoading: boolean;
  brokerError: unknown;
  retryBrokers: () => void;
  authBrokerId?: string;
  activeBrokerName?: string;
  authIsAdmin: boolean;
  authLoading: boolean;
  authError: unknown;
  sharedPolicy?: SharedPolicy;
  sharedPolicyUpdating: boolean;
  toggleSharedPolicy: () => void;
  logout: () => void;
};

function Shell() {
  const [brokers, setBrokers] = useState<DemoBroker[]>([]);
  const [brokerLoading, setBrokerLoading] = useState(true);
  const [brokerError, setBrokerError] = useState<unknown>();
  const [brokerAttempt, setBrokerAttempt] = useState(0);
  const [authBrokerId, setAuthBrokerId] = useState<string>();
  const [authIsAdmin, setAuthIsAdmin] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<unknown>();
  const [sharedPolicy, setSharedPolicy] = useState<SharedPolicy>();
  const [sharedPolicyUpdating, setSharedPolicyUpdating] = useState(false);
  const nav = useNavigate();
  const routeLocation = useLocation();
  const routeBrokerId = routeLocation.pathname.match(/^\/brokers\/([^/]+)/)?.[1];
  const retryBrokers = () => setBrokerAttempt((attempt) => attempt + 1);
  useEffect(() => {
    const controller = new AbortController();
    setBrokerLoading(true);
    setBrokerError(undefined);
    api
      .brokers(controller.signal)
      .then(setBrokers)
      .catch((error) => {
        if (!isAbortError(error)) setBrokerError(error);
      })
      .finally(() => setBrokerLoading(false));
    return () => controller.abort();
  }, [brokerAttempt]);
  useEffect(() => {
    const controller = new AbortController();
    setAuthLoading(true);
    setAuthError(undefined);
    setSharedPolicy(undefined);
    if (!hasAuthToken()) {
      setAuthBrokerId(undefined);
      setAuthIsAdmin(false);
      setSharedPolicy(undefined);
      setAuthLoading(false);
      return () => controller.abort();
    }
    api
      .me(routeBrokerId, controller.signal)
      .then((profile) => {
        setAuthBrokerId(profile.broker_id);
        setAuthIsAdmin(profile.is_admin);
        return api.sharedPolicy(profile.broker_id, controller.signal).catch(() => undefined);
      })
      .then(setSharedPolicy)
      .catch((error) => {
        if (!isAbortError(error)) {
          clearAuthToken();
          setAuthBrokerId(undefined);
          setAuthIsAdmin(false);
          setAuthError(error);
        }
      })
      .finally(() => setAuthLoading(false));
    return () => controller.abort();
  }, [routeBrokerId]);
  const toggleSharedPolicy = () => {
    if (!routeBrokerId || !sharedPolicy || sharedPolicyUpdating) return;
    setSharedPolicyUpdating(true);
    api
      .updateSharedPolicy(routeBrokerId, !sharedPolicy.enabled)
      .then(setSharedPolicy)
      .catch(setAuthError)
      .finally(() => setSharedPolicyUpdating(false));
  };
  const logout = () => {
    clearAuthToken();
    setAuthBrokerId(undefined);
    setAuthIsAdmin(false);
    setSharedPolicy(undefined);
    nav("/login", { replace: true });
  };
  const selectableBrokers = authIsAdmin || !authBrokerId
    ? brokers
    : brokers.filter((broker) => broker.id === authBrokerId);
  const activeBrokerName = brokers.find((broker) => broker.id === routeBrokerId)?.name;
  if (routeBrokerId && !authLoading && !authBrokerId && !authError) {
    return <Navigate to="/login" replace />;
  }
  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header>
          <Link
          className="brand"
            to={routeBrokerId ? `/brokers/${routeBrokerId}/loads` : "/brokers"}
        >
          <b>CP</b>
          <span>
            CARRIER POOL<small>OPERATIONS DESK</small>
          </span>
        </Link>
        <div className="demo">DEMO MODE</div>
        {authBrokerId && (
          <label className="switcher">
            BROKER{" "}
            <select
              value={routeBrokerId || authBrokerId}
              onChange={(e) => e.target.value && nav(`/brokers/${e.target.value}/loads`)}
              aria-label="Select broker"
            >
              {selectableBrokers.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {routeBrokerId && (authIsAdmin || authBrokerId === routeBrokerId) && sharedPolicy && (
          <button
            className={`pool-toggle ${sharedPolicy.enabled ? "enabled" : ""}`}
            aria-pressed={sharedPolicy.enabled}
            disabled={sharedPolicyUpdating}
            aria-busy={sharedPolicyUpdating}
            onClick={toggleSharedPolicy}
          >
            SHARED POOL {sharedPolicy.enabled ? "ON" : "OFF"}
          </button>
        )}
        {authBrokerId && <Link className="profile-link" to="/profile">PROFILE</Link>}
        {authBrokerId && <button className="logout" onClick={logout}>LOG OUT</button>}
      </header>
      <div className="notice">
        <strong>DEMO MODE</strong> Assignments are temporary platform overlays
        for evaluation. They do not update canonical TMS state.
      </div>
      <Outlet
        context={{
          brokers,
          brokerLoading,
          brokerError,
          retryBrokers,
          authBrokerId,
          activeBrokerName,
          authIsAdmin,
          authLoading,
          authError,
          sharedPolicy,
          sharedPolicyUpdating,
          toggleSharedPolicy,
          logout,
        }}
      />
    </div>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={`status ${value}`}>{value.replaceAll("_", " ")}</span>
  );
}
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
    setLoading(true);
    setData(null);
    setError(undefined);
    const params = buildQueueSearchParams(applied.filters, applied.page);
    params.set("page_size", "25");
    api
      .loads(brokerId, params.toString(), controller.signal)
      .then(setData)
      .catch((nextError) => {
        if (!isAbortError(nextError)) setError(nextError);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
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
          Choose a broker from the DEMO MODE switcher to open the dispatch
          queue.
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
function Financials({ load }: { load: Load }) {
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
         <b>{money(load.margin)}</b>
         <span>{percentage(load.margin, load.customer_rate)}</span>
      </div>
    </div>
  );
}
export function Analytics({ b, l, sharedEnabled }: { b: string; l: string; sharedEnabled: boolean }) {
  const [lane, setLane] = useState<Lane>();
  const [rate, setRate] = useState<Rate>();
  const [recs, setRecs] = useState<Recs>();
  const [sharedRate, setSharedRate] = useState<SharedRate>();
  const [sharedRecs, setSharedRecs] = useState<SharedRecs>();
  const [errs, setErrs] = useState<Record<string, unknown>>({});
  useEffect(() => {
    const ctrl = new AbortController();
    setLane(undefined);
    setRate(undefined);
    setRecs(undefined);
    setSharedRate(undefined);
    setSharedRecs(undefined);
    setErrs({});
    const loadPanel = <T,>(
      key: string,
      request: Promise<T>,
      setter: React.Dispatch<React.SetStateAction<T | undefined>>,
    ) => {
      request.then(setter).catch((e) => {
        if (!isAbortError(e)) setErrs((x) => ({ ...x, [key]: e }));
      });
    };
    loadPanel("lane", api.lane(b, l, ctrl.signal), setLane);
    loadPanel("rate", api.rate(b, l, ctrl.signal), setRate);
    loadPanel("recs", api.recs(b, l, ctrl.signal), setRecs);
    if (sharedEnabled) {
      loadPanel("sharedRate", api.sharedRate(b, l, ctrl.signal), setSharedRate);
      loadPanel("sharedRecs", api.sharedRecs(b, l, ctrl.signal), setSharedRecs);
    }
    return () => ctrl.abort();
  }, [b, l, sharedEnabled]);
  const failure = (k: string) =>
    errs[k] ? (
      <AnalyticsError error={errs[k]} />
    ) : (
          <div className="state" role="status">Loading…</div>
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
              nearby historical loads in the latest {lane.history.history_limit}
            </p>
            {lane.typical_travel_time && (
              <p className="travel-time">
                <b>Typical travel time</b> {lane.typical_travel_time.label}
              </p>
            )}
            <span className="tag">{lane.history.data_sufficiency} data</span>
            {lane.history.history_truncated && (
              <p className="note">History is capped at the most recent eligible loads.</p>
            )}
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
              samples · {rate.population.lookback_days ?? "—"}d lookback
            </p>
              {rate.confidence.reasons?.map((x: string, index: number) => (
              <div className="reason" key={`${x}-${index}`}>
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
            {recs.recommendations.length ? <div className="rec-list">
              {recs.recommendations.map((x: Recommendation) => (
                <RecommendationRow key={x.candidate_id} item={x} b={b} l={l} />
              ))}
            </div> : <div className="state">No scored carrier recommendations.</div>}
            <h4 className="subhead">UNSCORED / INSUFFICIENT HISTORY</h4>
            {recs.unscored_carriers.length ? recs.unscored_carriers.map((x, index) => (
              <div className="unscored" key={x.candidate_id}>
                <span>{x.name}</span>
                <small>{x.reason}</small>
              </div>
            )) : <div className="state">No unscored carriers.</div>}
          </>
        ) : (
          failure("recs")
        )}
      </Panel>
      <Panel title="Shared carrier pool">
        {!sharedEnabled ? (
          <div className="state">
            <b>Opted out</b>
            <span>Enable shared-pool participation from the workspace header.</span>
          </div>
        ) : errs.sharedRecs ? (
          <AnalyticsError error={errs.sharedRecs} />
        ) : sharedRecs ? (
          sharedRecs.recommendations.length ? (
            <div className="rec-list">
              {sharedRecs.recommendations.map((item) => (
                <div className="shared-rec-row" key={item.candidate_id}>
                  <strong>#{item.rank}</strong>
                  <span>
                    <b>{item.name}</b>
                    <small>
                      {item.match_quality.replace("_", " ")} · {item.equipment_type}
                    </small>
                  </span>
                  <em>{item.contributing_broker_count_bucket} brokers</em>
                </div>
              ))}
            </div>
          ) : (
            <div className="state">No privacy-safe shared matches meet the threshold.</div>
          )
        ) : (
          failure("sharedRecs")
        )}
      </Panel>
      <Panel title="Shared rate estimate">
        {!sharedEnabled ? (
          <div className="state">Enable shared-pool participation to view market range.</div>
        ) : errs.sharedRate ? (
          <AnalyticsError error={errs.sharedRate} />
        ) : sharedRate?.status === "unavailable" ? (
          <div className="state">
            <b>Unavailable</b>
            <span>No three-broker privacy-safe rate population is available.</span>
          </div>
        ) : sharedRate ? (
          <>
            <div className="estimate">{money(sharedRate.estimate.amount)} <span>
              {sharedRate.estimate.low && sharedRate.estimate.high
                ? `${money(sharedRate.estimate.low)}–${money(sharedRate.estimate.high)}`
                : ""}
            </span></div>
            <p className="muted">
              {sharedRate.confidence} confidence · {sharedRate.sample_count_bucket} samples · {sharedRate.contributing_broker_count_bucket} brokers
            </p>
            <span className="tag">SHARED / {sharedRate.match_scope || "market"}</span>
          </>
        ) : (
          failure("sharedRate")
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
export function DetailPage() {
  const { brokerId, loadId } = useParams();
  const { authBrokerId, authIsAdmin, authLoading, activeBrokerName, authError, sharedPolicy } = useOutletContext<ShellContext>();
  const routeLocation = useLocation();
  const [load, setLoad] = useState<Detail>();
  const [error, setError] = useState<unknown>();
  const [analyticsRefresh, setAnalyticsRefresh] = useState(0);
  const [reload, setReload] = useState(0);
  const [sp, setSp] = useSearchParams();
  const candidate = sp.get("candidate");
  useEffect(() => {
    if (!brokerId || !loadId || (!authIsAdmin && authBrokerId !== brokerId)) return;
    const controller = new AbortController();
    setLoad(undefined);
    setError(undefined);
    api
      .detail(brokerId, loadId, controller.signal)
      .then(setLoad)
      .catch((nextError) => {
        if (!isAbortError(nextError)) setError(nextError);
      });
    return () => controller.abort();
  }, [brokerId, loadId, reload, authBrokerId, authIsAdmin]);
  const refresh = () => setReload((value) => value + 1);
  const backTarget = (routeLocation.state as { from?: string } | null)?.from;
  if (error)
    return (
      <main id="main-content">
        <ErrorBox error={error} />
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
  if (!load || !brokerId || !loadId)
      return <main className="state" role="status">Loading load context…</main>;
  return (
    <main id="main-content">
      <Link className="back" to={backTarget || `/brokers/${brokerId}/loads`}>
        ← Back to queue
      </Link>
      <div className="detail-title">
        <div>
          <p className="eyebrow">{activeBrokerName || brokerId} / LOAD DETAIL / {load.source.name}</p>
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
             {location(load.origin)}
          </b>
        </div>
        <div>
          <small>DESTINATION</small>
          <b>
             {location(load.destination)}
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
          <Analytics
            key={analyticsRefresh}
            b={brokerId}
            l={loadId}
            sharedEnabled={sharedPolicy?.enabled ?? false}
          />
      {candidate && (
        <CandidateDrawer
          b={brokerId}
          l={loadId}
          candidate={candidate}
          version={load.assignment.assignment_version}
           onClose={() => {
             const next = new URLSearchParams(sp);
             next.delete("candidate");
             setSp(next, { replace: true });
           }}
           onAssigned={() => {
             refresh();
             setAnalyticsRefresh((x) => x + 1);
            const next = new URLSearchParams(sp);
            next.delete("candidate");
             setSp(next, { replace: true });
           }}
           onConflict={refresh}
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
  onConflict,
}: {
  b: string;
  l: string;
  candidate: string;
  version: number;
  onClose: () => void;
  onAssigned: () => void;
  onConflict: () => void;
}) {
  const [data, setData] = useState<Candidate>();
  const [err, setErr] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ kind: "success" | "error"; message: string }>();
  const drawerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setErr(undefined);
    setResult(undefined);
    api
      .candidate(b, l, candidate, controller.signal)
      .then(setData)
      .catch((nextError) => {
        if (!isAbortError(nextError)) setErr(nextError);
      });
    return () => controller.abort();
  }, [b, candidate]);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    drawerRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);
  const assign = async (carrier?: Carrier) => {
    setBusy(true);
    try {
      await api.assign(b, l, {
        carrier_id: carrier?.id,
        candidate_id: candidate,
        idempotency_key: crypto.randomUUID(),
        expected_assignment_version: version,
      });
       setResult({ kind: "success", message: "Assignment overlay created" });
       onAssigned();
     } catch (e) {
       if (e instanceof Error && "status" in e && e.status === 409) onConflict();
       setResult({
         kind: "error",
         message: e instanceof Error ? e.message : "Assignment failed",
       });
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
        role="dialog"
        aria-modal="true"
        aria-labelledby="candidate-drawer-title"
        tabIndex={-1}
        ref={drawerRef}
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
          <div className="state" role="status">Loading carrier…</div>
        ) : (
          <>
            <p className="eyebrow">CANDIDATE DETAIL</p>
             <h2 id="candidate-drawer-title">{data.name}</h2>
            <div className="identity">
              <b>MC {data.mc_number || "—"}</b>
              <b>DOT {data.dot_number || "—"}</b>
            </div>
            <h4>CONTACT / MEMBER RECORDS</h4>
             {data.carriers.map((c) => (
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
             <h4>PRIVACY-SAFE CONTRIBUTING TRIPS</h4>
             {data.evidence.length ? data.evidence.map((item, index) => (
               <div className="evidence" key={`${item.origin.postal_code}-${item.destination.postal_code}-${index}`}>
                 <b>{item.origin.city}, {item.origin.state} {item.origin.postal_code} → {item.destination.city}, {item.destination.state} {item.destination.postal_code}</b>
                 <span>{item.completed_month || "Completion month unavailable"} · {item.outcome}</span>
               </div>
             )) : <p className="muted">No contributing trip details are available.</p>}
             {result && (
               <div className={result.kind === "success" ? "success" : "error"} role="status">
                 {result.message}
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
function LoginPage() {
  const { brokers, brokerLoading, brokerError, retryBrokers, authBrokerId } =
    useOutletContext<ShellContext>();
  const nav = useNavigate();
  const [createMode, setCreateMode] = useState(false);
  const [brokerId, setBrokerId] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    if (!brokerId && brokers.length) setBrokerId(brokers[0].id);
    if (authBrokerId) nav(`/brokers/${authBrokerId}/loads`, { replace: true });
  }, [brokers, brokerId, authBrokerId, nav]);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    setMessage(undefined);
    try {
      if (createMode) {
        await api.createAccount(brokerId, name, email, password);
        setIdentifier(email);
        setCreateMode(false);
        setMessage("Account created. Sign in with the new local account.");
      } else {
        const response = await api.demoAuth(brokerId, identifier, password);
        setAuthToken(response.access_token);
        nav(`/brokers/${response.broker_id}/loads`, { replace: true });
      }
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  };
  const toggleCreateMode = () => {
    setCreateMode((value) => {
      const next = !value;
      if (next) setBrokerId(brokers.find((broker) => !broker.is_demo)?.id || brokerId);
      return next;
    });
    setError(undefined);
    setMessage(undefined);
  };
  return (
    <main id="main-content" className="empty">
      <p className="eyebrow">CARRIER POOL / LOCAL DEMO ACCESS</p>
      <h1>{createMode ? "Create a local account" : "Sign in to operations"}</h1>
      <p>Select a broker workspace. Accounts are memory-only and reset when the backend restarts.</p>
      {brokerLoading ? (
        <div className="state" role="status">Loading demo brokers…</div>
      ) : brokerError ? (
        <div className="state error" role="alert">
          <b>Could not load demo brokers.</b>
          <button className="primary" onClick={retryBrokers}>Retry</button>
        </div>
      ) : !brokers.length ? <div className="state">No brokers are available.</div> : (
        <form className="login-form" onSubmit={submit}>
          {Boolean(error) && <div className="state error" role="alert">{error instanceof Error ? error.message : "Request failed"}</div>}
          {message && <div className="state success" role="status">{message}</div>}
          <label>Broker<select value={brokerId} onChange={(event) => setBrokerId(event.target.value)}>
            {brokers.map((broker) => <option key={broker.id} value={broker.id}>{broker.name}{broker.is_demo ? " · DEMO LOCKED" : " · LOCAL"}</option>)}
          </select></label>
          {createMode && <label>Name<input value={name} onChange={(event) => setName(event.target.value)} required /></label>}
          <label>{createMode ? "Email" : "Email or username"}<input value={createMode ? email : identifier} onChange={(event) => createMode ? setEmail(event.target.value) : setIdentifier(event.target.value)} required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          <button className="primary" type="submit" disabled={busy}>{busy ? "Working…" : createMode ? "Create account" : "Sign in"}</button>
          <button className="link-button" type="button" onClick={toggleCreateMode}>
            {createMode ? "Back to sign in" : "Create a local account"}
          </button>
          <small className="demo-hint">Sysadmin demo login: <b>admin / admin</b>. This is an explicit demo-only exception.</small>
        </form>
      )}
    </main>
  );
}

function ProfilePage() {
  const { authBrokerId, authLoading, authError, logout } = useOutletContext<ShellContext>();
  const [profile, setProfile] = useState<Profile>();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState<string>();
  const [resetOpen, setResetOpen] = useState(false);
  useEffect(() => {
    if (!authBrokerId) return;
    const controller = new AbortController();
    api.me(authBrokerId, controller.signal).then((next) => {
      setProfile(next);
      setName(next.name);
      setEmail(next.email || "");
    }).catch((nextError) => {
      if (!isAbortError(nextError)) setError(nextError);
    });
    return () => controller.abort();
  }, [authBrokerId]);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(undefined);
    setMessage(undefined);
    try {
      const next = await api.updateProfile({ name, email, password: password || undefined });
      setProfile(next);
      setPassword("");
      setMessage("Profile updated for this demo run.");
    } catch (nextError) {
      setError(nextError);
    }
  };
  if (authError) return <main id="main-content"><ErrorBox error={authError} /></main>;
  if (authLoading || !profile) return <main className="state" role="status">Loading profile…</main>;
  return (
    <main id="main-content" className="profile-page">
      <p className="eyebrow">ACCOUNT / PROFILE</p>
      <h1>{profile.name}</h1>
      <p>{profile.broker_name} · {profile.is_admin ? "Sysadmin" : profile.is_demo ? "Demo broker" : "Local broker"}</p>
      {Boolean(error) && <div className="state error" role="alert">{error instanceof Error ? error.message : "Could not update profile"}</div>}
      {message && <div className="state success" role="status">{message}</div>}
      <form className="profile-form" onSubmit={save}>
        <label>Name<input value={name} onChange={(event) => setName(event.target.value)} disabled={profile.profile_locked} /></label>
        <label>Email<input value={email} onChange={(event) => setEmail(event.target.value)} disabled={profile.profile_locked || profile.is_admin} /></label>
        <label>New password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={profile.profile_locked || profile.is_admin} placeholder="6-12 chars + symbol" /></label>
        <button className="primary" type="submit" disabled={profile.profile_locked}>Save changes</button>
      </form>
      {profile.profile_locked && <p className="note">Demo broker profiles are locked. Local accounts reset when the backend restarts.</p>}
      <button className="link-button" onClick={() => setResetOpen(true)}>Forgot password?</button>
      <button className="logout-button" onClick={logout}>Log out</button>
      {resetOpen && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setResetOpen(false)}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="reset-title"><h2 id="reset-title">Password reset unavailable</h2><p>Email delivery is not connected in this demo. Create a new local account instead.</p><button className="primary" onClick={() => setResetOpen(false)}>Close</button></div></div>}
    </main>
  );
}
export function App() {
  return (
    <RouterRoutes>
      <Route element={<Shell />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/brokers" element={<Navigate to="/login" replace />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/brokers/:brokerId/loads" element={<Queue />} />
        <Route
          path="/brokers/:brokerId/loads/:loadId"
          element={<DetailPage />}
        />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Route>
    </RouterRoutes>
  );
}
