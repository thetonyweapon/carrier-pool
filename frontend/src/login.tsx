import React, { useEffect, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api, setAuthToken } from "./api";
import { AUTH_CLIENT_ID, AUTH_LOGIN_URL, AUTH_REDIRECT_URI, DEMO_MODE } from "./env";
import { buildAuthorizationUrl } from "./oidc";
import { ShellContext } from "./shell";

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

export function LoginPage() {
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
  if (!DEMO_MODE) {
    const beginLogin = async (event: React.MouseEvent<HTMLAnchorElement>) => {
      event.preventDefault();
      if (!AUTH_LOGIN_URL || !AUTH_CLIENT_ID || !AUTH_REDIRECT_URI) return;
      const verifier = base64Url(crypto.getRandomValues(new Uint8Array(32)));
      const challenge = base64Url(new Uint8Array(await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(verifier),
      )));
      const state = base64Url(crypto.getRandomValues(new Uint8Array(32)));
      window.sessionStorage.setItem("carrier-pool.oidc-state", state);
      window.sessionStorage.setItem("carrier-pool.oidc-verifier", verifier);
      window.location.assign(
        buildAuthorizationUrl(AUTH_LOGIN_URL, AUTH_CLIENT_ID, AUTH_REDIRECT_URI, state, challenge),
      );
    };
    return (
      <main id="main-content" className="empty">
        <p className="eyebrow">CARRIER POOL / SECURE ACCESS</p>
        <h1>Sign in to operations</h1>
        <p>Use your organization identity provider to access a broker workspace.</p>
        {AUTH_LOGIN_URL ? (
          <a className="primary" href={AUTH_LOGIN_URL || "#"} onClick={beginLogin}>Continue with organization sign-in</a>
        ) : (
          <div className="state error" role="alert">
            Production identity-provider login is not configured.
          </div>
        )}
      </main>
    );
  }
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
        const response = await api.signIn(brokerId, identifier, password);
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
          <small className="demo-hint">Sysadmin demo login: <b>{["admin", " / ", "admin"].join("")}</b>. This is an explicit demo-only exception.</small>
        </form>
      )}
    </main>
  );
}
