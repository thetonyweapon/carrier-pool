import React from "react";

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="state error" role="alert">
      <b>Could not load this panel</b>
      <span>{error instanceof Error ? error.message : "Unknown error"}</span>
    </div>
  );
}
export function AnalyticsError({ error }: { error: unknown }) {
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
export function Panel({
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
export function Status({ value }: { value: string }) {
  return (
    <span className={`status ${value}`}>{value.replaceAll("_", " ")}</span>
  );
}
