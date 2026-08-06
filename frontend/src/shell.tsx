import { useEffect, useState } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  api,
  DemoBroker,
  SharedPolicy,
  clearAuthToken,
  hasAuthToken,
  setAuthToken,
} from "./api";
import { DEMO_LABEL, DEMO_MODE } from "./env";
import { cleanAuthorizationSearch, readAuthorizationResponse } from "./oidc";
import { isAbortError } from "./ui";

export type ShellContext = {
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

export function Shell() {
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
    if (DEMO_MODE || (!window.location.search && !window.location.hash)) return;
    const { code, state: returnedState } = readAuthorizationResponse(
      window.location.search,
      window.location.hash,
    );
    const cleanSearch = cleanAuthorizationSearch(window.location.search);
    window.history.replaceState(
      {},
      document.title,
      `${window.location.pathname}${cleanSearch}`,
    );
    const expectedState = window.sessionStorage.getItem("carrier-pool.oidc-state");
    const verifier = window.sessionStorage.getItem("carrier-pool.oidc-verifier");
    const clearCallbackState = () => {
      window.sessionStorage.removeItem("carrier-pool.oidc-state");
      window.sessionStorage.removeItem("carrier-pool.oidc-verifier");
    };
    if (!code || !returnedState || returnedState !== expectedState || !verifier) {
      clearCallbackState();
      return;
    }
    api.exchangeOidcCode(code, verifier).then(({ access_token: accessToken }) => {
      clearCallbackState();
      setAuthToken(accessToken);
      window.location.reload();
    }).catch(() => {
      clearCallbackState();
    });
  }, []);
  useEffect(() => {
    if (!DEMO_MODE) {
      setBrokers([]);
      setBrokerLoading(false);
      return;
    }
    const controller = new AbortController();
    let current = true;
    setBrokerLoading(true);
    setBrokerError(undefined);
    api
      .brokers(controller.signal)
      .then((nextBrokers) => current && setBrokers(nextBrokers))
      .catch((error) => {
        if (current && !isAbortError(error)) setBrokerError(error);
      })
      .finally(() => current && setBrokerLoading(false));
    return () => {
      current = false;
      controller.abort();
    };
  }, [brokerAttempt]);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
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
        if (!current) return undefined;
        setAuthBrokerId(profile.broker_id);
        setAuthIsAdmin(profile.is_admin);
        if (!DEMO_MODE && !routeBrokerId && routeLocation.pathname === "/login") {
          nav(`/brokers/${profile.broker_id}/loads`, { replace: true });
        }
        return api.sharedPolicy(profile.broker_id, controller.signal).catch(() => undefined);
      })
      .then((nextPolicy) => current && setSharedPolicy(nextPolicy))
      .catch((error) => {
        if (current && !isAbortError(error)) {
          clearAuthToken();
          setAuthBrokerId(undefined);
          setAuthIsAdmin(false);
          setAuthError(error);
        }
      })
      .finally(() => current && setAuthLoading(false));
    return () => {
      current = false;
      controller.abort();
    };
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
        {DEMO_MODE && <div className="demo">{DEMO_LABEL}</div>}
        {DEMO_MODE && authBrokerId && (
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
      {DEMO_MODE && (
        <div className="notice">
          <strong>{DEMO_LABEL}</strong> Assignments are temporary platform overlays
          for evaluation. They do not update canonical TMS state.
        </div>
      )}
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
