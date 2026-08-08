import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  Lane,
  Rate,
  Recommendation,
  Recs,
  SharedRate,
  SharedRecs,
} from "./api";
import { money } from "./formatters";
import { AnalyticsError, isAbortError, Panel } from "./ui";

export function Analytics({ b, l, sharedEnabled }: { b: string; l: string; sharedEnabled: boolean }) {
  const [lane, setLane] = useState<Lane>();
  const [rate, setRate] = useState<Rate>();
  const [recs, setRecs] = useState<Recs>();
  const [sharedRate, setSharedRate] = useState<SharedRate>();
  const [sharedRecs, setSharedRecs] = useState<SharedRecs>();
  const [errs, setErrs] = useState<Record<string, unknown>>({});
  useEffect(() => {
    const ctrl = new AbortController();
    let current = true;
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
      request.then((value) => current && setter(value)).catch((e) => {
        if (current && !isAbortError(e)) setErrs((x) => ({ ...x, [key]: e }));
      });
    };
    loadPanel("lane", api.lane(b, l, ctrl.signal), setLane);
    loadPanel("rate", api.rate(b, l, ctrl.signal), setRate);
    loadPanel("recs", api.recs(b, l, ctrl.signal), setRecs);
    if (sharedEnabled) {
      loadPanel("sharedRate", api.sharedRate(b, l, ctrl.signal), setSharedRate);
      loadPanel("sharedRecs", api.sharedRecs(b, l, ctrl.signal), setSharedRecs);
    }
    return () => {
      current = false;
      ctrl.abort();
    };
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
                      privacy-safe shared evidence
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
            <span className="tag">SHARED</span>
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
