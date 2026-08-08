import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { Analytics } from "./analytics";
import { api, Candidate, Carrier, Detail, Load } from "./api";
import { DEMO_MODE } from "./env";
import { date, day, location, money, percentage } from "./formatters";
import { ShellContext } from "./shell";
import { ErrorBox, isAbortError, Panel, Status } from "./ui";

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
    let current = true;
    setLoad(undefined);
    setError(undefined);
    api
      .detail(brokerId, loadId, controller.signal)
      .then((nextLoad) => current && setLoad(nextLoad))
      .catch((nextError) => {
        if (current && !isAbortError(nextError)) setError(nextError);
      });
    return () => {
      current = false;
      controller.abort();
    };
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
    let current = true;
    setData(undefined);
    setErr(undefined);
    setResult(undefined);
    api
      .candidate(b, l, candidate, controller.signal)
      .then((nextData) => current && setData(nextData))
      .catch((nextError) => {
        if (current && !isAbortError(nextError)) setErr(nextError);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [b, l, candidate]);
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
                {DEMO_MODE && <button
                  className="primary full"
                  disabled={busy}
                  onClick={() => assign(c)}
                >
                  Assign overlay to this carrier
                </button>}
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
            {DEMO_MODE && <p className="disclaimer">
              Demo assignment only. This writes a platform overlay and does not
              alter canonical TMS carrier or load state.
            </p>}
          </>
        )}
      </aside>
    </div>
  );
}
